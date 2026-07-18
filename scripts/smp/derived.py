from __future__ import annotations

"""Derived metrics computed from a Basketball GM export.

Everything here is pure computation over the export dict — no HTML. Pages
(player/game/classics/home) and the shared client payload (appdata.py) consume
these helpers:

    fantasy_pts(stat_row)                fantasy-points score for a raw-total row
    player_shot_zones(data, pid, season) per-player-season shot-zone splits + league pct
    four_factors(team_stat_row)          Dean Oliver four factors (+ opp mirrors)
    drama_index(game, feats_by_gid)      0-100 "how dramatic was this game" score
    feats_index(data)                    gid -> playerFeats rows (drama_index input)
    led_league(data)                     season -> stat key -> league-leading value
"""

import math
from collections import defaultdict
from typing import Any

from .core import safe_float, safe_int

# ---------------------------------------------------------------------------
# Fantasy points
# ---------------------------------------------------------------------------

# Points-league scoring weights, applied to raw totals:
#   PTS +1, 3PM +1, FGM +2, FGA -1, FTM +1, FTA -1, REB +1, AST +2,
#   STL +4, BLK +4, TOV -2
FANTASY_WEIGHTS = [
    ("pts", 1.0),
    ("tp", 1.0),
    ("fg", 2.0),
    ("fga", -1.0),
    ("ft", 1.0),
    ("fta", -1.0),
    ("ast", 2.0),
    ("stl", 4.0),
    ("blk", 4.0),
    ("tov", -2.0),
]

# A row must carry the core shooting/scoring inputs to be scoreable at all.
_FANTASY_REQUIRED = ("pts", "fg", "fga")


def _rebounds(stat_row: dict[str, Any]) -> float:
    """Total rebounds from either a trb field or orb+drb (box rows split them)."""
    if stat_row.get("trb") is not None:
        return safe_float(stat_row.get("trb"))
    return safe_float(stat_row.get("orb")) + safe_float(stat_row.get("drb"))


def fantasy_pts(stat_row: dict[str, Any] | None) -> float | None:
    """Fantasy-points total for a raw-total stat row.

    Works on both per-game box rows (games[].teams[].players) and season
    aggregate rows (players[].stats) — raw totals in, totals out. Returns
    None when the row is missing its core inputs (empty rows, DNPs exported
    without shooting fields).
    """
    if not stat_row:
        return None
    if any(stat_row.get(key) is None for key in _FANTASY_REQUIRED):
        return None
    total = sum(weight * safe_float(stat_row.get(key)) for key, weight in FANTASY_WEIGHTS)
    return total + _rebounds(stat_row)


# ---------------------------------------------------------------------------
# Shot zones
# ---------------------------------------------------------------------------

# (zone key, made field, attempted field) in court order, from the box-score
# shot-location fields BBGM records.
SHOT_ZONES = [
    ("rim", "fgAtRim", "fgaAtRim"),
    ("lowpost", "fgLowPost", "fgaLowPost"),
    ("mid", "fgMidRange", "fgaMidRange"),
    ("three", "tp", "tpa"),
]

ZONE_LABELS = {"rim": "At Rim", "lowpost": "Low Post", "mid": "Mid-Range", "three": "Three"}

# Per-export cache: aggregating every box row is O(games × players), so do it
# once per build. Keyed by id(data); a build only ever loads one export.
_ZONE_CACHE: dict[int, dict[str, Any]] = {}


def _shot_zone_index(data: dict[str, Any]) -> dict[str, Any]:
    """Aggregate box-score shot-zone totals per (pid, season) + league totals per season."""
    cached = _ZONE_CACHE.get(id(data))
    if cached is not None:
        return cached
    players: dict[tuple[int, int], dict[str, dict[str, float]]] = {}
    league: dict[int, dict[str, dict[str, float]]] = {}
    for game in data.get("games", []):
        season = safe_int(game.get("season"), -1)
        if season < 0:
            continue
        lg = league.setdefault(season, {zone: {"fg": 0.0, "fga": 0.0} for zone, _, _ in SHOT_ZONES})
        for team_box in game.get("teams", []) or []:
            for box in team_box.get("players", []) or []:
                pid = safe_int(box.get("pid"), -1)
                if pid < 0:
                    continue
                zones = players.setdefault(
                    (pid, season), {zone: {"fg": 0.0, "fga": 0.0} for zone, _, _ in SHOT_ZONES}
                )
                for zone, made_key, att_key in SHOT_ZONES:
                    made = safe_float(box.get(made_key))
                    att = safe_float(box.get(att_key))
                    zones[zone]["fg"] += made
                    zones[zone]["fga"] += att
                    lg[zone]["fg"] += made
                    lg[zone]["fga"] += att
    index = {"players": players, "league": league}
    _ZONE_CACHE.clear()  # only ever one export per process; don't hoard old ones
    _ZONE_CACHE[id(data)] = index
    return index


def league_zone_pct(data: dict[str, Any], season: int) -> dict[str, float | None]:
    """League-average FG% per shot zone for a season (0-100 scale, None if no attempts)."""
    lg = _shot_zone_index(data)["league"].get(season) or {}
    out: dict[str, float | None] = {}
    for zone, _, _ in SHOT_ZONES:
        totals = lg.get(zone) or {}
        fga = safe_float(totals.get("fga"))
        out[zone] = (100.0 * safe_float(totals.get("fg")) / fga) if fga > 0 else None
    return out


def player_shot_zones(data: dict[str, Any], pid: int, season: int) -> dict[str, dict[str, Any]] | None:
    """Per-player-season shot-zone splits aggregated from game box rows.

    Returns {zone: {"fg", "fga", "pct", "lg_pct"}} in SHOT_ZONES order — pct is
    0-100 (None with no attempts) and lg_pct is the league-average pct for the
    same zone/season, for comparison tinting. Returns None when the player has
    no box rows in that season (the export only retains recent seasons' games).
    """
    index = _shot_zone_index(data)
    zones = index["players"].get((safe_int(pid, -1), season))
    if zones is None:
        return None
    lg = league_zone_pct(data, season)
    out: dict[str, dict[str, Any]] = {}
    for zone, _, _ in SHOT_ZONES:
        fg = zones[zone]["fg"]
        fga = zones[zone]["fga"]
        out[zone] = {
            "fg": fg,
            "fga": fga,
            "pct": (100.0 * fg / fga) if fga > 0 else None,
            "lg_pct": lg.get(zone),
        }
    return out


# ---------------------------------------------------------------------------
# Four factors
# ---------------------------------------------------------------------------

def _four_factor_values(fg: float, tp: float, fga: float, tov: float, fta: float,
                        ft: float, orb: float, opp_drb: float) -> dict[str, float | None]:
    efg = (100.0 * (fg + 0.5 * tp) / fga) if fga > 0 else None
    tov_denom = fga + 0.44 * fta + tov
    tov_pct = (100.0 * tov / tov_denom) if tov_denom > 0 else None
    orb_denom = orb + opp_drb
    orb_pct = (100.0 * orb / orb_denom) if orb_denom > 0 else None
    ft_rate = (ft / fga) if fga > 0 else None
    return {"efg": efg, "tov_pct": tov_pct, "orb_pct": orb_pct, "ft_rate": ft_rate}


def four_factors(team_stat_row: dict[str, Any]) -> dict[str, float | None]:
    """Dean Oliver's four factors for a team season-stat row, plus opponent mirrors.

    Standard formulas:
        eFG%    = (FG + 0.5 * 3P) / FGA          (0-100 scale)
        TOV%    = TOV / (FGA + 0.44 * FTA + TOV) (0-100 scale)
        ORB%    = ORB / (ORB + opp DRB)          (0-100 scale)
        FT rate = FT / FGA                       (ratio, e.g. 0.20)

    Opponent mirrors use the row's opp* fields (opp ORB% is against our DRB).
    Missing denominators yield None. Keys: efg, tov_pct, orb_pct, ft_rate and
    opp_efg, opp_tov_pct, opp_orb_pct, opp_ft_rate.
    """
    row = team_stat_row or {}
    own = _four_factor_values(
        safe_float(row.get("fg")), safe_float(row.get("tp")), safe_float(row.get("fga")),
        safe_float(row.get("tov")), safe_float(row.get("fta")), safe_float(row.get("ft")),
        safe_float(row.get("orb")), safe_float(row.get("oppDrb")),
    )
    opp = _four_factor_values(
        safe_float(row.get("oppFg")), safe_float(row.get("oppTp")), safe_float(row.get("oppFga")),
        safe_float(row.get("oppTov")), safe_float(row.get("oppFta")), safe_float(row.get("oppFt")),
        safe_float(row.get("oppOrb")), safe_float(row.get("drb")),
    )
    out: dict[str, float | None] = dict(own)
    for key, value in opp.items():
        out[f"opp_{key}"] = value
    return out


# ---------------------------------------------------------------------------
# Drama index
# ---------------------------------------------------------------------------

def feats_index(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """playerFeats grouped by game id (stringified gid), for drama_index."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feat in data.get("playerFeats", []) or []:
        if isinstance(feat, dict) and feat.get("gid") is not None:
            out[str(feat.get("gid"))].append(feat)
    return dict(out)


def _quarter_margins(game: dict[str, Any]) -> list[float]:
    """Cumulative home-minus-away margin at each period boundary, from ptsQtrs."""
    boxes = game.get("teams") or []
    if len(boxes) < 2:
        return []
    home_q = boxes[0].get("ptsQtrs") or []
    away_q = boxes[1].get("ptsQtrs") or []
    margins: list[float] = []
    running = 0.0
    for h, a in zip(home_q, away_q):
        running += safe_float(h) - safe_float(a)
        margins.append(running)
    return margins


def comeback_size(game: dict[str, Any]) -> float:
    """Largest period-boundary deficit the eventual winner overcame (points).

    ptsQtrs only records period totals, so this is the deficit as of the end of
    a period — a conservative floor on the true in-game comeback.
    """
    boxes = game.get("teams") or []
    if len(boxes) < 2:
        return 0.0
    home_pts = safe_float(boxes[0].get("pts"))
    away_pts = safe_float(boxes[1].get("pts"))
    if home_pts == away_pts:
        return 0.0
    home_won = home_pts > away_pts
    deficit = 0.0
    for margin in _quarter_margins(game):
        trailing_by = -margin if home_won else margin
        deficit = max(deficit, trailing_by)
    return deficit


def drama_index(game: dict[str, Any], feats_by_gid: dict[str, list[dict[str, Any]]] | None = None) -> float:
    """How dramatic a completed game was, on a 0-100 scale.

    Weighted sum of five components (weights sum to 100 at saturation):

        closeness  30 * clamp((16 - final_margin) / 15, 0, 1)
                       a 1-point final is worth the full 30; 16+ points worth 0
        overtimes  20 * min(overtimes, 2) / 2
                       one OT scores 10, double-OT or more the full 20
        comeback   25 * min(comeback, 20) / 20
                       comeback = the winner's largest period-boundary deficit
                       (from ptsQtrs running margins); a 20-point rally saturates
        clutch     15 * min(len(clutchPlays), 3) / 3
                       exported late-game clutch-play blurbs
        feats      10 * min(feats_in_game, 2) / 2
                       playerFeats rows for this gid (pass feats_index(data))

    Scheduled/unfinished games (no two team boxes with points) score 0.
    """
    boxes = game.get("teams") or []
    if len(boxes) < 2 or boxes[0].get("pts") is None or boxes[1].get("pts") is None:
        return 0.0
    margin = abs(safe_float(boxes[0].get("pts")) - safe_float(boxes[1].get("pts")))
    closeness = 30.0 * max(0.0, min(1.0, (16.0 - margin) / 15.0))
    overtime = 20.0 * min(safe_int(game.get("overtimes")), 2) / 2.0
    comeback = 25.0 * min(comeback_size(game), 20.0) / 20.0
    clutch_plays = game.get("clutchPlays") or []
    clutch = 15.0 * min(len(clutch_plays), 3) / 3.0
    n_feats = len((feats_by_gid or {}).get(str(game.get("gid"))) or [])
    feats = 10.0 * min(n_feats, 2) / 2.0
    total = closeness + overtime + comeback + clutch + feats
    return max(0.0, min(100.0, total))


# ---------------------------------------------------------------------------
# Led-league lookup
# ---------------------------------------------------------------------------

def led_league(data: dict[str, Any]) -> dict[int, dict[str, float]]:
    """League-leading regular-season values per season, from seasonLeaders.

    Returns {season: {stat_key: leading_value}} using the stat keys BBGM stores
    in each seasonLeaders row's regularSeason dict (per-game/percentage keys like
    pts, trb, ast, stl, blk, min, fgp, tpp, ftp, per, ws, bpm, vorp, and the
    *Max single-game keys). A player's season cell gets gold styling when its
    value matches the stored leading value for that season and stat.
    """
    out: dict[int, dict[str, float]] = {}
    for row in data.get("seasonLeaders", []) or []:
        if not isinstance(row, dict):
            continue
        season = safe_int(row.get("season"), -1)
        if season < 0:
            continue
        leaders = row.get("regularSeason") or {}
        stats: dict[str, float] = {}
        for key, value in leaders.items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                stats[key] = float(value)
        out[season] = stats
    return out


def led_league_stats(led: dict[int, dict[str, float]], season: int, stat_row: dict[str, Any],
                     keys: list[str], tol: float = 1e-6) -> set[str]:
    """Which of ``keys`` in a per-game stat row match the season's leading value."""
    leaders = led.get(season) or {}
    out: set[str] = set()
    for key in keys:
        lead = leaders.get(key)
        value = stat_row.get(key)
        if lead is None or value is None:
            continue
        if abs(safe_float(value) - lead) <= tol:
            out.add(key)
    return out
