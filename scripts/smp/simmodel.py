from __future__ import annotations

import argparse
import html
import json
import random
import math
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

# Projection engine (faithful zengm port + Monte Carlo). Imported defensively so
# the site still builds if numpy / projections.py is unavailable -- in that case
# projection charts gracefully fall back to the static development chart.
try:
    import projections as _proj
except Exception:  # pragma: no cover - degraded build path
    _proj = None

from .core import (
    SITE_META,
    active_players,
    completed_game_items,
    fmt_number,
    generated_schedule_items,
    is_completed_game_item,
    latest_rating,
    latest_team_season,
    latest_team_stat,
    raw_schedule_items,
    regular_season_length,
    safe_float,
    safe_int,
    score_items_for_page,
    season_regular_stat,
    standings_order,
    stat_gp,
    team_mov,
)


# Free-agent asking-salary model (from the user's UFA formula). Maps a player's
# ovr/pot/age to a "salary score", then interpolates that score on an anchor curve
# to a dollar figure. All salary values are in $M; BBGM stores thousands (×1000).
FA_SALARY_ANCHORS = [
    (52, 1), (55, 3), (58, 8), (60, 12), (62, 16), (64, 20), (66, 24),
    (68, 28), (70, 32), (72, 35), (74, 39), (76, 43), (78, 47), (80, 50),
]


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def fa_salary_score(ovr: int, pot: int, age: int) -> float:
    """UFA salary score: ovr adjusted for upside, decline risk, prime, and age."""
    upside_gap = max(pot - ovr, 0)
    if age <= 21:
        upside_bonus = min(0.38 * upside_gap, 8.0)
    elif age <= 24:
        upside_bonus = min(0.28 * upside_gap, 6.0)
    elif age <= 27:
        upside_bonus = min(0.15 * upside_gap, 3.5)
    elif age <= 30:
        upside_bonus = min(0.05 * upside_gap, 1.5)
    else:
        upside_bonus = 0.0
    decline_gap = max(ovr - pot, 0)
    decline_penalty = min((0.12 if age <= 30 else 0.22) * decline_gap, 4.0)
    prime_bonus = 1.0 if 24 <= age <= 29 else 0.0
    veteran_penalty = 1.25 * max(age - 32, 0)
    return ovr + upside_bonus - decline_penalty + prime_bonus - veteran_penalty


def _salary_score_to_millions(score: float) -> float:
    anchors = FA_SALARY_ANCHORS
    if score <= anchors[0][0]:
        return float(anchors[0][1])
    if score >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (s0, m0), (s1, m1) in zip(anchors, anchors[1:]):
        if s0 <= score <= s1:
            return m0 + (score - s0) / (s1 - s0) * (m1 - m0)
    return float(anchors[-1][1])


def fa_salary_millions(ovr: int, pot: int, age: int) -> int:
    """Single-year UFA asking salary in $M (rounded half-up, clamped to 1..50)."""
    raw = _salary_score_to_millions(fa_salary_score(ovr, pot, age))
    return max(1, min(50, _round_half_up(raw)))


def fa_salary_by_length(ovr: int, pot: int, age: int) -> list[int]:
    """Annual asking salary ($M) for 1..5-year deals. The formula is age-based, so a
    longer deal averages the yearly figure as the player ages across it (ovr/pot held)."""
    out = []
    for length in range(1, 6):
        raws = [_salary_score_to_millions(fa_salary_score(ovr, pot, age + i)) for i in range(length)]
        out.append(max(1, min(50, _round_half_up(sum(raws) / len(raws)))))
    return out


# --- projection-backed development chart ------------------------------------
PROJ_SEASONS_AHEAD = 6
PROJ_N_SIMS = 1000
PROJ_MASTER_SEED = 8675309


def _player_projection(player: dict[str, Any], season: int) -> dict[str, Any] | None:
    """Monte Carlo OVR projection for a player from the current season forward.

    Returns None (caller falls back to the static chart) when projections are
    unavailable: the projection engine/numpy is not importable, the player is
    retired, or there is no current rating row carrying all 15 subratings.
    The seed is derived from the pid so rebuilds are byte-identical.
    """
    if _proj is None:
        return None
    if player.get("retiredYear") is not None:
        return None
    born_year = (player.get("born") or {}).get("year")
    if born_year is None:
        return None
    rows = [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)]
    if not rows:
        return None
    rows.sort(key=lambda r: r["season"])
    cur = next((r for r in rows if r["season"] == season), rows[-1])
    if not all(k in cur for k in _proj.RATINGS):
        return None
    cur_season = int(cur["season"])
    age = cur_season - int(born_year)
    if age < 14 or age > 50:
        return None
    seed = PROJ_MASTER_SEED * 100003 + safe_int(player.get("pid"), 0)
    try:
        sim = _proj.simulate_player(
            cur, age, cur_season,
            seasons_ahead=PROJ_SEASONS_AHEAD, n_sims=PROJ_N_SIMS, seed=seed,
        )
    except Exception:
        return None
    return {"cur_season": cur_season, "age": age, "sim": sim}


# --- team projection --------------------------------------------------------
REPLACEMENT_OVR = 40.0  # roster-construction floor: a freely-available filler

# Games at which current-season scoring margin carries half the strength weight:
# weight = gp / (gp + SIM_MOV_BLEND_K). At gp=0 (fresh season) strength is 100%
# roster-based; by a full 45-game season MOV carries ~82%.
SIM_MOV_BLEND_K = 10.0


def _player_current_ovr(player: dict[str, Any], season: int) -> int | None:
    """The player's overall this season (the stored value, == player_ovr)."""
    rows = [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)]
    if not rows:
        return None
    rows.sort(key=lambda r: r["season"])
    cur = next((r for r in rows if r["season"] == season), rows[-1])
    v = cur.get("ovr")
    return safe_int(v) if v is not None else None


def current_team_ovr(roster: list[dict[str, Any]], season: int) -> int | None:
    """Raw engine team OVR from a roster's current player overalls (unclamped)."""
    if _proj is None:
        return None
    ovrs = [o for o in (_player_current_ovr(p, season) for p in roster) if o is not None]
    if not ovrs:
        return None
    return _proj.team_ovr(ovrs)


def player_game_impact(player: dict[str, Any], season: int) -> float:
    """Estimated per-game scoring-margin impact versus a replacement player."""
    stat = season_regular_stat(player, season)
    gp = stat_gp(stat)
    mpg = (safe_float(stat.get("min")) / gp) if gp else 0.0
    if gp >= 3 and mpg >= 8:
        bpm = safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))
        impact = (bpm + 2.0) * (mpg / 48.0)  # replacement level is roughly -2 BPM
    else:
        rating = latest_rating(player, season)
        impact = max(0.0, (safe_float(rating.get("ovr"), 40.0) - 50.0) * 0.12)
    return max(-2.0, min(10.0, impact))


def simulate_league(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, sims: int = 10000) -> dict[str, Any]:
    """Monte Carlo the rest of the season and the playoffs.

    Team strength is a roster signal from the CURRENT roster — top-10 per-game
    player impact, centered on the league mean — blended with THIS season's
    scoring margin only as games accumulate (MOV weight = gp/(gp+SIM_MOV_BLEND_K)).
    A season with no games played is 100% roster-based; last season's margin is
    never used. Players who are injured subtract their impact until their
    expected return, so odds dip while stars are out and recover as they heal.
    Trades are picked up automatically because strength comes from the roster
    as it stands today.

    A season that hasn't been played yet starts every team at 0-0 and runs over
    the exported schedule when the export carries one, else a projected
    round-robin.
    """
    fresh = not completed_game_items(data, season, playoffs=False)
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    wins0: dict[int, float] = {}
    mov_now: dict[int, float] = {}
    gp_now: dict[int, float] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins0[tid] = 0.0 if fresh else safe_float(team_season.get("won"))
        # latest_team_stat falls back to an earlier season's row when this season
        # has no stats yet — never seed strength from last season's margin.
        if safe_int(stat.get("season")) == season:
            gp_now[tid] = safe_float(stat.get("gp"))
            mov_now[tid] = team_mov(stat) or 0.0
        else:
            gp_now[tid] = 0.0
            mov_now[tid] = 0.0

    # Roster strength (healthy) and per-team injured list (impact, games remaining).
    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid >= 0:
            roster_by_tid[tid].append(player)
    roster_strength: dict[int, float] = {}
    injured_by_tid: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for tid in tids:
        roster = roster_by_tid.get(tid, [])
        rotation = sorted(roster, key=lambda p: -player_game_impact(p, season))[:10]
        roster_strength[tid] = sum(player_game_impact(p, season) for p in rotation)
        for player in roster:
            injury = player.get("injury") or {}
            games_out = safe_int(injury.get("gamesRemaining"))
            if injury.get("type") and injury.get("type") != "Healthy" and games_out > 0:
                impact = player_game_impact(player, season)
                if impact > 0.2:
                    injured_by_tid[tid].append((impact, games_out))
    mean_roster = sum(roster_strength.values()) / len(roster_strength) if roster_strength else 0.0
    base_strength: dict[int, float] = {}
    for tid in tids:
        mov_weight = gp_now[tid] / (gp_now[tid] + SIM_MOV_BLEND_K)
        roster_signal = roster_strength.get(tid, 0.0) - mean_roster
        base_strength[tid] = (1.0 - mov_weight) * roster_signal + mov_weight * mov_now[tid]

    # Remaining schedule in chronological order. Prefer the exported schedule;
    # an unplayed season with none is projected over a generated round-robin.
    remaining: list[tuple[int, int, int, str]] = []

    def collect(items: Iterable[dict[str, Any]]) -> None:
        for item in items:
            if is_completed_game_item(item) or safe_int(item.get("season")) != season:
                continue
            home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
            if home in wins0 and away in wins0:
                remaining.append((safe_int(item.get("day")), home, away, str(item.get("gid"))))

    collect(score_items_for_page(data, teams)[0])
    if fresh and not remaining:
        collect(generated_schedule_items(data, teams, schedule_season=season))
    remaining.sort(key=lambda g: (g[0], g[3]))
    games_left = defaultdict(int)
    for _, home, away, _ in remaining:
        games_left[home] += 1
        games_left[away] += 1

    # Injury penalty by "games into the rest of the season" — deterministic per team.
    max_left = max(games_left.values()) if games_left else 0
    penalty_at: dict[int, list[float]] = {}
    for tid in tids:
        series = []
        for k in range(max_left + 1):
            series.append(sum(impact for impact, games_out in injured_by_tid.get(tid, []) if k < games_out))
        penalty_at[tid] = series

    first_day = remaining[0][0] if remaining else None
    stakes_games = [g for g in remaining if g[0] == first_day] if first_day is not None else []
    stake_counts: dict[str, dict[str, list[int]]] = {
        gid: {"home_win": [0, 0], "home_loss": [0, 0], "away_win": [0, 0], "away_loss": [0, 0]}
        for _, _, _, gid in stakes_games
    }

    def win_prob(home: int, away: int, k_home: int, k_away: int) -> float:
        # The module-level logistic (strength gap + SIM_HCA home edge) over the
        # injury-adjusted strengths k games into the rest of the season.
        return game_win_prob(
            base_strength[home] - penalty_at[home][min(k_home, max_left)],
            base_strength[away] - penalty_at[away][min(k_away, max_left)],
        )

    rng = random.Random(20290101)
    playoff_count = defaultdict(int)
    finals_count = defaultdict(int)
    champ_count = defaultdict(int)
    seed_counts: dict[int, list[int]] = {tid: [0] * len(tids) for tid in tids}
    win_total = defaultdict(float)

    def sim_series(a: int, b: int, length: int = 7) -> int:
        """Best-of-`length`; team `a` has home court. Returns the winner."""
        needed = length // 2 + 1
        a_wins = b_wins = 0
        home_pattern = [True, True, False, False, True, False, True]
        for game_index in range(length):
            a_home = home_pattern[game_index % 7]
            prob = win_prob(a, b, max_left, max_left) if a_home else 1.0 - win_prob(b, a, max_left, max_left)
            if rng.random() < prob:
                a_wins += 1
            else:
                b_wins += 1
            if a_wins == needed:
                return a
            if b_wins == needed:
                return b
        return a if a_wins > b_wins else b

    for _ in range(sims):
        wins = dict(wins0)
        played = {tid: 0 for tid in tids}
        results_first_day: dict[str, bool] = {}
        for day, home, away, gid in remaining:
            home_won = rng.random() < win_prob(home, away, played[home], played[away])
            if home_won:
                wins[home] += 1
            else:
                wins[away] += 1
            played[home] += 1
            played[away] += 1
            if gid in stake_counts:
                results_first_day[gid] = home_won
        order = sorted(tids, key=lambda tid: (-wins[tid], rng.random()))
        made_playoffs = set(order[:4])
        for seed, tid in enumerate(order, 1):
            if seed <= 4:
                playoff_count[tid] += 1
            seed_counts[tid][seed - 1] += 1
        for tid in tids:
            win_total[tid] += wins[tid]
        # playoffs: 1v4 and 2v3, then the final; higher seed has home court
        finalist_a = sim_series(order[0], order[3])
        finalist_b = sim_series(order[1], order[2])
        finals_count[finalist_a] += 1
        finals_count[finalist_b] += 1
        if order.index(finalist_a) <= order.index(finalist_b):
            champ = sim_series(finalist_a, finalist_b)
        else:
            champ = sim_series(finalist_b, finalist_a)
        champ_count[champ] += 1
        # what's-at-stake bookkeeping for the next game day
        for _, home, away, gid in stakes_games:
            home_won = results_first_day.get(gid, False)
            key_home = "home_win" if home_won else "home_loss"
            key_away = "away_loss" if home_won else "away_win"
            stake_counts[gid][key_home][0] += 1
            stake_counts[gid][key_home][1] += 1 if home in made_playoffs else 0
            stake_counts[gid][key_away][0] += 1
            stake_counts[gid][key_away][1] += 1 if away in made_playoffs else 0

    results: dict[int, dict[str, Any]] = {}
    for tid in tids:
        results[tid] = {
            "po": playoff_count[tid] / sims,
            "finals": finals_count[tid] / sims,
            "champ": champ_count[tid] / sims,
            "seeds": [count / sims for count in seed_counts[tid]],
            "proj_w": win_total[tid] / sims,
            "games_left": games_left[tid],
        }

    # Per-game projection payload for the next slate. Win probability and
    # spread reuse the exact strengths the Monte Carlo fed win_prob for these
    # games (injury-adjusted at k=0), so any display built on this payload
    # agrees with the sim; the conditional playoff odds are tallied inside
    # the same sims.
    stakes = []
    for day, home, away, gid in stakes_games:
        counts = stake_counts[gid]

        def rate(key: str) -> float | None:
            total, made = counts[key][0], counts[key][1]
            return made / total if total else None

        eff_home = base_strength[home] - penalty_at[home][0]
        eff_away = base_strength[away] - penalty_at[away][0]
        stakes.append({
            "gid": gid, "day": day, "home_tid": home, "away_tid": away,
            "home_wp": game_win_prob(eff_home, eff_away),
            "spread": projected_spread(eff_home, eff_away),
            "home_po_win": rate("home_win"), "home_po_loss": rate("home_loss"),
            "away_po_win": rate("away_win"), "away_po_loss": rate("away_loss"),
        })
    return {"teams": results, "stakes": stakes, "day": first_day, "fresh": fresh}


def league_sim(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[str, Any]:
    """League simulation, cached per season (each season is simulated once per build)."""
    cache = SITE_META.setdefault("sim", {})
    if season not in cache:
        cache[season] = simulate_league(data, teams, active_players(data), season)
    return cache[season]


# --- shared game model (consumed by simulate_league, appdata.py, pages) ------
# simulate_league decides every game with
#     p(home) = 1 / (1 + exp(-(strength_diff + SIM_HCA) * SIM_LOGISTIC_K))
# The constants and the helpers below ARE that model: simulate_league's inner
# win_prob calls game_win_prob, and the client-side simulator (Win-Out Machine /
# Lineup Lab) mirrors the same constants. Tests assert projected-win parity.
SIM_HCA = 1.5
SIM_LOGISTIC_K = 0.16


def game_win_prob(home_strength: float, away_strength: float) -> float:
    """Home team's single-game win probability from two team strengths.

    This is THE formula the Monte Carlo (simulate_league) decides games with:
    a logistic over the projected home scoring margin — the strength gap plus
    the +1.5-point home-court edge (SIM_HCA), scaled by SIM_LOGISTIC_K::

        p(home) = 1 / (1 + exp(-((home - away) + SIM_HCA) * SIM_LOGISTIC_K))

    Read-only consumers (home-page game cards, game previews) call this so
    their displayed probabilities agree with the sim exactly. Strengths are
    per-game scoring-margin signals from sim_client_inputs / simulate_league.
    """
    return 1.0 / (1.0 + math.exp(-(home_strength - away_strength + SIM_HCA) * SIM_LOGISTIC_K))


def projected_margin(home_strength: float, away_strength: float) -> float:
    """Projected home scoring margin, in points, for a single game.

    Team strengths are per-game scoring-margin signals, so the expected margin
    is simply ``(home_strength - away_strength) + SIM_HCA`` — the same quantity
    the win-probability logistic is applied to. Positive means the home team is
    projected to win by that many points.
    """
    return (home_strength - away_strength) + SIM_HCA


def projected_spread(home_strength: float, away_strength: float) -> float:
    """Sportsbook-style point spread for the HOME team, in half-point steps.

    The projected home margin (projected_margin) is quoted the way a book
    lists a line: negated (the favorite "lays" points) and rounded half-up to
    the nearest 0.5. A +4.4-point home margin returns -4.5 ("HOME -4.5"); a
    2.1-point away edge returns +2.0 ("AWAY -2.0"); a dead-even matchup
    returns 0.0 (a pick'em). Sign only says which side is favored — negative
    is the home team.
    """
    margin = projected_margin(home_strength, away_strength)
    return -math.floor(margin * 2.0 + 0.5) / 2.0


def sim_strengths(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> dict[int, float]:
    """Read-only team strengths, exactly as the sim computes them.

    Convenience view over sim_client_inputs (which documents the model:
    current-roster impact blended with current-season MOV, never last
    season's margin). Feed pairs of these to game_win_prob / projected_spread
    for displays that must agree with simulate_league's Monte Carlo.
    """
    return sim_client_inputs(data, teams, players, season)["strengths"]


def sim_client_inputs(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> dict[str, Any]:
    """Team strengths + remaining schedule for the client-side simulator.

    Mirrors the strength model and remaining-schedule selection at the top of
    simulate_league exactly (fresh-season detection, current-roster top-10
    impact centered on the league mean, blended with CURRENT-season MOV at
    weight gp/(gp+SIM_MOV_BLEND_K) — never last season's margin) so that a
    client sim over this payload agrees with the server-side Monte Carlo. Injury
    penalties are intentionally left out of the payload — they decay per game and
    matter only mid-season; the client sims the healthy baseline.

    Returns {"strengths": {tid: float}, "hca", "logistic_k",
             "schedule": [[day, home_tid, away_tid], ...], "fresh": bool,
             "wins": {tid: int}, "losses": {tid: int}}.
    """
    fresh = not completed_game_items(data, season, playoffs=False)
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    mov_now: dict[int, float] = {}
    gp_now: dict[int, float] = {}
    wins: dict[int, int] = {}
    losses: dict[int, int] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins[tid] = 0 if fresh else safe_int(team_season.get("won"))
        losses[tid] = 0 if fresh else safe_int(team_season.get("lost"))
        # latest_team_stat falls back to an earlier season's row when this season
        # has no stats yet — never seed strength from last season's margin.
        if safe_int(stat.get("season")) == season:
            gp_now[tid] = safe_float(stat.get("gp"))
            mov_now[tid] = team_mov(stat) or 0.0
        else:
            gp_now[tid] = 0.0
            mov_now[tid] = 0.0

    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid >= 0:
            roster_by_tid[tid].append(player)
    roster_strength: dict[int, float] = {}
    for tid in tids:
        rotation = sorted(roster_by_tid.get(tid, []), key=lambda p: -player_game_impact(p, season))[:10]
        roster_strength[tid] = sum(player_game_impact(p, season) for p in rotation)
    mean_roster = sum(roster_strength.values()) / len(roster_strength) if roster_strength else 0.0
    strengths: dict[int, float] = {}
    for tid in tids:
        mov_weight = gp_now[tid] / (gp_now[tid] + SIM_MOV_BLEND_K)
        roster_signal = roster_strength.get(tid, 0.0) - mean_roster
        strengths[tid] = (1.0 - mov_weight) * roster_signal + mov_weight * mov_now[tid]

    # Mirrors simulate_league: exported schedule first, generated round-robin
    # only for an unplayed season with no exported schedule.
    remaining: list[tuple[int, int, int, str]] = []

    def collect(items: Iterable[dict[str, Any]]) -> None:
        for item in items:
            if is_completed_game_item(item) or safe_int(item.get("season")) != season:
                continue
            home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
            if home in strengths and away in strengths:
                remaining.append((safe_int(item.get("day")), home, away, str(item.get("gid"))))

    collect(score_items_for_page(data, teams)[0])
    if fresh and not remaining:
        collect(generated_schedule_items(data, teams, schedule_season=season))
    remaining.sort(key=lambda g: (g[0], g[3]))

    return {
        "strengths": strengths,
        "hca": SIM_HCA,
        "logistic_k": SIM_LOGISTIC_K,
        "schedule": [[day, home, away] for day, home, away, _ in remaining],
        "fresh": fresh,
        "wins": wins,
        "losses": losses,
    }


def league_bench_ovrs(players: list[dict[str, Any]], season: int) -> list[float]:
    """League-average 6th..10th-best current-roster OVRs, sorted desc (5 floats, 1dp).

    Emitted as app-data.json's sim.bench_ovrs; Lineup Lab pads a five-man
    selection with these instead of a flat replacement OVR. Rank-wise mean
    across the current rosters: a team with fewer than ten players simply
    doesn't count toward the deeper ranks; a rank no team fills falls back
    to REPLACEMENT_OVR.
    """
    by_tid: dict[int, list[int]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid < 0:
            continue
        ovr = latest_rating(player, season).get("ovr")
        if ovr is not None:
            by_tid[tid].append(safe_int(ovr))
    rosters = [sorted(ovrs, reverse=True) for ovrs in by_tid.values()]
    out: list[float] = []
    for rank in range(5, 10):
        values = [ovrs[rank] for ovrs in rosters if len(ovrs) > rank]
        avg = sum(values) / len(values) if values else REPLACEMENT_OVR
        out.append(round(avg, 1) + 0.0)
    return sorted(out, reverse=True)


def magic_elimination(teams: list[dict[str, Any]], season: int, season_len: int = 45) -> dict[int, str]:
    """Magic number to clinch top 4, or elimination number, per team."""
    rows = []
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        won = safe_float(team_season.get("won"))
        lost = safe_float(team_season.get("lost"))
        gp = safe_float(stat.get("gp"))
        rows.append({"tid": tid, "won": won, "lost": lost, "gp": gp})
    if not rows:
        return {}
    order = standings_order(teams, season)
    by_tid = {row["tid"]: row for row in rows}
    out: dict[int, str] = {}
    if len(order) < 5:
        return {tid: "—" for tid in order}
    fourth = by_tid[order[3]]
    fifth = by_tid[order[4]]
    for rank, tid in enumerate(order, 1):
        row = by_tid[tid]
        remaining = max(0.0, season_len - row["won"] - row["lost"])
        if rank <= 4:
            rival = fifth
            rival_remaining = max(0.0, season_len - rival["won"] - rival["lost"])
            magic = rival["won"] + rival_remaining - row["won"] + 1
            out[tid] = "Clinched" if magic <= 0 else f"M {fmt_number(magic, 0)}"
        else:
            rival = fourth
            tragic = row["won"] + remaining - rival["won"] + 1
            out[tid] = "Eliminated" if tragic <= 0 else f"E {fmt_number(tragic, 0)}"
    return out


def playoff_clinch_marks(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[int, str]:
    """Computed clinch ("x") / elimination ("e") marks for a top-4 playoff cut.

    Uses each team's record plus its remaining schedule (games not yet played).
    Conservative pairwise math: a team is marked clinched only when fewer than
    four rivals can still reach its current win total, and eliminated only when
    at least four rivals already exceed its maximum possible win total. Ties
    count against clinching and for survival, so ambiguous cases get no mark.
    """
    rows: dict[int, dict[str, float]] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        rows[tid] = {
            "won": safe_float(team_season.get("won")),
            "lost": safe_float(team_season.get("lost")),
            "rem": 0.0,
        }
    if len(rows) < 5:
        return {}

    # Remaining games per team, counted from the exported schedule.
    scheduled = 0
    for item in raw_schedule_items(data, teams):
        if is_completed_game_item(item) or item.get("playoffs") or safe_int(item.get("season"), season) != season:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        if home in rows and away in rows:
            rows[home]["rem"] += 1
            rows[away]["rem"] += 1
            scheduled += 1
    if not scheduled:
        # No schedule export: fall back to the season length, or skip if unknown.
        season_len = regular_season_length(data, season)
        if season_len <= 0:
            return {}
        for row in rows.values():
            row["rem"] = max(0.0, season_len - row["won"] - row["lost"])

    out: dict[int, str] = {}
    for tid, row in rows.items():
        max_wins = row["won"] + row["rem"]
        can_catch = sum(1 for o_tid, o in rows.items() if o_tid != tid and o["won"] + o["rem"] >= row["won"])
        already_ahead = sum(1 for o_tid, o in rows.items() if o_tid != tid and o["won"] > max_wins)
        if can_catch <= 3:
            out[tid] = "x"
        elif already_ahead >= 4:
            out[tid] = "e"
    return out
