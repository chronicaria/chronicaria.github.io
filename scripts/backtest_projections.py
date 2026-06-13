"""
backtest_projections.py -- Back-test / calibration harness for the projection engine.

Validates that the Monte Carlo bands produced by scripts/projections.py are calibrated,
by projecting forward FROM A PAST SEASON and comparing the projected bands to what
actually happened (the realized later rating rows already stored in the league export).

METHOD (per the calibration spec):
  - Load league-data/day20.json. For each player, take the ratings[] rows sorted by
    season. age in season S = S - born.year.
  - For each player with >= 4 rating rows, pick an anchor season that leaves >= 3 future
    realized rows. Stand at the anchor ratings/age and call simulate_player with
    seasons_ahead = min(6, available_future_rows), n_sims = 1000, seed derived per pid.
  - For each future horizon h (1..6) and each metric (ovr + the 15 subratings), compare
    the REALIZED value at anchor+h to the projected band:
      coverage80 : fraction of realized within [p10, p90]   (target ~0.80)
      coverage50 : fraction within [p25, p75]                (target ~0.50)
      bias       : mean(realized - p50)                       (target ~0)
      MAE        : mean(|realized - p50|)
  - Aggregate across ALL players, broken down by horizon h and by age bucket
    (<=21, 22-25, 26-29, 30-33, 34+). Report OVR calibration prominently.

The realized path is a SINGLE stochastic draw, so per-player it can fall outside the
band; calibration is judged in AGGREGATE. coverage80 materially below ~0.7 or above ~0.9
suggests the variance model is mis-tuned (likely the correlation structure).

Python 3.9 compatible. numpy only.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

# Make scripts/ importable, then import the engine.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import projections  # noqa: E402
from projections import RATINGS, simulate_player  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO = "/Users/andrewpark/Desktop/Code/chronicaria.github.io"
EXPORT_PATH = os.path.join(REPO, "league-data", "day20.json")
SUMMARY_PATH = os.path.join(REPO, "scripts", "backtest_summary.json")

N_SIMS = 1000
MASTER_SEED = 20240613  # arbitrary fixed master seed -> deterministic backtest
MAX_HORIZON = 6
MIN_RATING_ROWS = 4
MIN_FUTURE_ROWS = 3

# Metrics tracked: ovr first, then the 15 subratings.
METRICS = ["ovr"] + list(RATINGS)

AGE_BUCKETS = [
    ("<=21", lambda a: a <= 21),
    ("22-25", lambda a: 22 <= a <= 25),
    ("26-29", lambda a: 26 <= a <= 29),
    ("30-33", lambda a: 30 <= a <= 33),
    ("34+", lambda a: a >= 34),
]


def age_bucket(age: int) -> str:
    for name, pred in AGE_BUCKETS:
        if pred(age):
            return name
    return "?"


# ---------------------------------------------------------------------------
# Accumulator: for a given grouping key, collect per-comparison stats so we can
# compute coverage/bias/MAE at the end.
# ---------------------------------------------------------------------------
class StatAcc:
    """Accumulates the four calibration numbers over many (realized, band) points."""

    __slots__ = ("n", "in80", "in50", "sum_signed", "sum_abs")

    def __init__(self) -> None:
        self.n = 0
        self.in80 = 0
        self.in50 = 0
        self.sum_signed = 0.0
        self.sum_abs = 0.0

    def add(self, realized: float, p10: float, p25: float, p50: float,
            p75: float, p90: float) -> None:
        self.n += 1
        if p10 <= realized <= p90:
            self.in80 += 1
        if p25 <= realized <= p75:
            self.in50 += 1
        diff = realized - p50
        self.sum_signed += diff
        self.sum_abs += abs(diff)

    def result(self) -> Dict[str, Optional[float]]:
        if self.n == 0:
            return {"n": 0, "coverage80": None, "coverage50": None,
                    "bias": None, "mae": None}
        return {
            "n": self.n,
            "coverage80": self.in80 / self.n,
            "coverage50": self.in50 / self.n,
            "bias": self.sum_signed / self.n,
            "mae": self.sum_abs / self.n,
        }


def _new_metric_accs() -> Dict[str, StatAcc]:
    return {m: StatAcc() for m in METRICS}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_players(path: str) -> Tuple[List[dict], int]:
    with open(path) as f:
        data = json.load(f)
    ga = data.get("gameAttributes", {})
    season = ga.get("season") if isinstance(ga, dict) else None
    if season is None:
        season = 2029
    return data["players"], int(season)


def usable_rows(player: dict) -> List[dict]:
    """Rating rows that have all 15 keys + ovr + season, sorted ascending by season."""
    rows = []
    for rr in player.get("ratings", []):
        if "season" not in rr or "ovr" not in rr:
            continue
        if not all(k in rr for k in RATINGS):
            continue
        rows.append(rr)
    rows.sort(key=lambda r: r["season"])
    return rows


def realized_value(row: dict, metric: str) -> float:
    if metric == "ovr":
        return float(row["ovr"])
    return float(row[metric])


def projected_bands(sim: Dict[str, object], metric: str
                    ) -> Tuple[List[float], List[float], List[float],
                               List[float], List[float]]:
    """Return (p10, p25, p50, p75, p90) lists for the metric across horizons."""
    if metric == "ovr":
        b = sim["ovr"]  # type: ignore[index]
    else:
        b = sim["subratings"][metric]  # type: ignore[index]
    return b["p10"], b["p25"], b["p50"], b["p75"], b["p90"]


# ---------------------------------------------------------------------------
# Core backtest
# ---------------------------------------------------------------------------
def retention_by_age(players: List[dict]) -> Dict[str, Dict[str, float]]:
    """Survivorship measure: of all player-seasons at each age that have a usable
    rating row, what fraction still have a rating row 3 seasons later?

    This quantifies the censoring that biases the old-age back-test: hard
    decliners retire and leave no future rows, so the realized future sample is
    selected toward players who aged well. Low retention at old ages is the
    mechanism behind the positive (realized - p50) bias there.
    """
    have: Dict[int, int] = {}
    surv: Dict[int, int] = {}
    for p in players:
        born_year = p.get("born", {}).get("year")
        if born_year is None:
            continue
        seasons = set()
        for rr in p.get("ratings", []):
            if "season" in rr and "ovr" in rr and all(k in rr for k in RATINGS):
                seasons.add(int(rr["season"]))
        for s in seasons:
            age = s - int(born_year)
            have[age] = have.get(age, 0) + 1
            if (s + 3) in seasons:
                surv[age] = surv.get(age, 0) + 1
    out: Dict[str, Dict[str, float]] = {}
    for age in sorted(have):
        n = have[age]
        out[str(age)] = {
            "n_seasons": n,
            "retained_3yr": surv.get(age, 0),
            "retention_rate": (surv.get(age, 0) / n) if n else None,
        }
    return out


def run_backtest() -> Dict[str, object]:
    players, cur_season = load_players(EXPORT_PATH)

    # Grouped accumulators.
    by_horizon: Dict[int, Dict[str, StatAcc]] = {
        h: _new_metric_accs() for h in range(1, MAX_HORIZON + 1)
    }
    by_age: Dict[str, Dict[str, StatAcc]] = {
        name: _new_metric_accs() for name, _ in AGE_BUCKETS
    }
    overall: Dict[str, StatAcc] = _new_metric_accs()

    # ovr-only: horizon x age cross-tab for a richer OVR view.
    ovr_by_age_horizon: Dict[str, Dict[int, StatAcc]] = {
        name: {h: StatAcc() for h in range(1, MAX_HORIZON + 1)}
        for name, _ in AGE_BUCKETS
    }

    n_players_tested = 0
    n_anchors = 0
    n_comparisons = 0

    for p in players:
        rows = usable_rows(p)
        if len(rows) < MIN_RATING_ROWS:
            continue
        born_year = p.get("born", {}).get("year")
        if born_year is None:
            continue
        pid = p.get("pid", 0)

        # Use EVERY anchor row that leaves >= MIN_FUTURE_ROWS future rows, not
        # just the player's earliest season. Anchoring only at the youngest row
        # would leave the decline phase (ages 30+) with no samples, yet team
        # projections lean heavily on veterans aging correctly -- so we want the
        # whole curve calibrated. Anchors within a player are independent draws
        # (seed varies with anchor_idx) and the run stays fully deterministic.
        last_anchor_idx = len(rows) - MIN_FUTURE_ROWS - 1
        if last_anchor_idx < 0:
            continue

        used_player = False
        for anchor_idx in range(0, last_anchor_idx + 1):
            anchor_row = rows[anchor_idx]
            anchor_season = int(anchor_row["season"])
            anchor_age = anchor_season - int(born_year)

            # Future realized rows after the anchor.
            future_rows = rows[anchor_idx + 1:]
            available = len(future_rows)
            seasons_ahead = min(MAX_HORIZON, available)
            if seasons_ahead < 1:
                continue

            # Map realized rows by their horizon (season offset from anchor).
            # Future rows may skip seasons; we only compare where a realized row
            # exists at exactly anchor_season + h.
            realized_by_h: Dict[int, dict] = {}
            for rr in future_rows:
                h = int(rr["season"]) - anchor_season
                if 1 <= h <= seasons_ahead and h not in realized_by_h:
                    realized_by_h[h] = rr
            if not realized_by_h:
                continue

            seed = MASTER_SEED * 100003 + pid * 131 + anchor_idx
            sim = simulate_player(
                anchor_row, anchor_age, anchor_season,
                seasons_ahead=seasons_ahead, n_sims=N_SIMS, seed=seed,
            )

            bucket = age_bucket(anchor_age)
            n_anchors += 1
            used_player = True

            for metric in METRICS:
                p10, p25, p50, p75, p90 = projected_bands(sim, metric)
                for h, rr in realized_by_h.items():
                    # band index h == year h in the path (index 0 == anchor)
                    rv = realized_value(rr, metric)
                    args = (rv, p10[h], p25[h], p50[h], p75[h], p90[h])
                    overall[metric].add(*args)
                    by_horizon[h][metric].add(*args)
                    by_age[bucket][metric].add(*args)
                    if metric == "ovr":
                        ovr_by_age_horizon[bucket][h].add(*args)
                        n_comparisons += 1

        if used_player:
            n_players_tested += 1

    # ----- assemble machine-readable summary -----
    summary: Dict[str, object] = {
        "config": {
            "export": EXPORT_PATH,
            "current_season": cur_season,
            "n_sims": N_SIMS,
            "master_seed": MASTER_SEED,
            "max_horizon": MAX_HORIZON,
            "min_rating_rows": MIN_RATING_ROWS,
            "min_future_rows": MIN_FUTURE_ROWS,
            "anchor": "every usable anchor row per player (>= min_future_rows ahead)",
        },
        "n_players_tested": n_players_tested,
        "n_anchors": n_anchors,
        "n_ovr_comparisons": n_comparisons,
        "metrics": METRICS,
        "overall": {m: overall[m].result() for m in METRICS},
        "by_horizon": {
            str(h): {m: by_horizon[h][m].result() for m in METRICS}
            for h in range(1, MAX_HORIZON + 1)
        },
        "by_age_bucket": {
            name: {m: by_age[name][m].result() for m in METRICS}
            for name, _ in AGE_BUCKETS
        },
        "ovr_by_age_and_horizon": {
            name: {
                str(h): ovr_by_age_horizon[name][h].result()
                for h in range(1, MAX_HORIZON + 1)
            }
            for name, _ in AGE_BUCKETS
        },
        "retention_by_age": retention_by_age(players),
    }
    return summary


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt(v: Optional[float], nd: int = 3) -> str:
    if v is None:
        return "  -  "
    return ("{:." + str(nd) + "f}").format(v)


def print_report(summary: Dict[str, object]) -> None:
    cfg = summary["config"]  # type: ignore[index]
    print("=" * 78)
    print("PROJECTION ENGINE BACK-TEST / CALIBRATION REPORT")
    print("=" * 78)
    print("export           : {}".format(cfg["export"]))
    print("current season   : {}".format(cfg["current_season"]))
    print("n_sims           : {}   master_seed: {}".format(
        cfg["n_sims"], cfg["master_seed"]))
    print("anchor rule      : {} (>= {} future rows required)".format(
        cfg["anchor"], cfg["min_future_rows"]))
    print("players tested   : {}".format(summary["n_players_tested"]))
    print("anchors used     : {}".format(summary.get("n_anchors", "-")))
    print("OVR comparisons  : {}".format(summary["n_ovr_comparisons"]))
    print()
    print("INTERPRETATION: the realized path is a SINGLE stochastic draw, so any one")
    print("player can fall outside the band. Calibration is judged IN AGGREGATE:")
    print("coverage80 across many players should sit near 0.80 (coverage50 near 0.50).")
    print("Coverage materially below ~0.70 or above ~0.90 indicates the variance model")
    print("is mis-tuned -- most likely the development correlation structure.")
    print()

    # --- Headline: OVR overall ---
    ovr_all = summary["overall"]["ovr"]  # type: ignore[index]
    print("-" * 78)
    print("HEADLINE -- OVR CALIBRATION (all horizons, all ages pooled)")
    print("-" * 78)
    print("  samples    : {}".format(ovr_all["n"]))
    print("  coverage80 : {}   (target 0.80)".format(_fmt(ovr_all["coverage80"])))
    print("  coverage50 : {}   (target 0.50)".format(_fmt(ovr_all["coverage50"])))
    print("  bias       : {}   (target 0.00; realized - p50)".format(
        _fmt(ovr_all["bias"])))
    print("  MAE        : {}".format(_fmt(ovr_all["mae"])))
    print()

    # --- OVR by horizon ---
    print("-" * 78)
    print("OVR CALIBRATION BY HORIZON h (seasons ahead)")
    print("-" * 78)
    hdr = "  {:>3} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
        "h", "n", "cover80", "cover50", "bias", "MAE")
    print(hdr)
    for h in range(1, MAX_HORIZON + 1):
        r = summary["by_horizon"][str(h)]["ovr"]  # type: ignore[index]
        print("  {:>3} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
            h, r["n"], _fmt(r["coverage80"]), _fmt(r["coverage50"]),
            _fmt(r["bias"]), _fmt(r["mae"])))
    print()

    # --- OVR by age bucket ---
    print("-" * 78)
    print("OVR CALIBRATION BY ANCHOR-AGE BUCKET")
    print("-" * 78)
    print("  {:>6} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
        "age", "n", "cover80", "cover50", "bias", "MAE"))
    for name, _ in AGE_BUCKETS:
        r = summary["by_age_bucket"][name]["ovr"]  # type: ignore[index]
        print("  {:>6} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
            name, r["n"], _fmt(r["coverage80"]), _fmt(r["coverage50"]),
            _fmt(r["bias"]), _fmt(r["mae"])))
    print()

    # --- All metrics overall (subratings) ---
    print("-" * 78)
    print("ALL METRICS -- OVERALL (pooled over horizon & age)")
    print("-" * 78)
    print("  {:>6} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
        "metric", "n", "cover80", "cover50", "bias", "MAE"))
    for m in METRICS:
        r = summary["overall"][m]  # type: ignore[index]
        print("  {:>6} {:>7} {:>10} {:>10} {:>9} {:>8}".format(
            m, r["n"], _fmt(r["coverage80"]), _fmt(r["coverage50"]),
            _fmt(r["bias"]), _fmt(r["mae"])))
    print()

    # --- Survivorship / retention by age ---
    ret = summary.get("retention_by_age", {})  # type: ignore[assignment]
    if ret:
        print("-" * 78)
        print("SURVIVORSHIP -- 3-YEAR RETENTION BY AGE (why old-age bias is positive)")
        print("-" * 78)
        print("  fraction of player-seasons at each age that still have a rating row")
        print("  3 seasons later. Low retention => realized old-age sample is censored")
        print("  toward players who aged well, inflating realized-minus-p50 bias.")
        print("  {:>4} {:>11} {:>11}".format("age", "n_seasons", "retain_3yr"))
        for age_str in sorted(ret, key=lambda a: int(a)):
            row = ret[age_str]
            if row["n_seasons"] < 15:
                continue
            rr = row["retention_rate"]
            print("  {:>4} {:>11} {:>11}".format(
                age_str, row["n_seasons"],
                _fmt(rr, 2) if rr is not None else "  -  "))
        print()

    print("Machine-readable summary written to:")
    print("  {}".format(SUMMARY_PATH))
    print("=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    summary = run_backtest()
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print_report(summary)


if __name__ == "__main__":
    main()
