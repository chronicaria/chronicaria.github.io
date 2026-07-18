from __future__ import annotations

"""Shared client payload: assets/app-data.json.

One compact, deterministic JSON blob per build, consumed by the client-side
apps (Compare, Trade Machine, Lineup Lab, Win-Out Machine) instead of each page
embedding its own player JSON. Schema (see PLAN.md):

    { "season": int,
      "players": [{pid,name,pos,age,tid,jersey,ovr,pot,salary,exp,value,
                   pg:{pts,trb,ast,stl,blk,tov,min,fg_pct,tp_pct,ft_pct,fpts},
                   ratings:{15 subratings}, skills:[...]}],
      "teams": [{tid,abbrev,region,name,colors:{primary,secondary,chart},
                 strength,payroll,record:{w,l}}],
      "sim": {"strengths":{tid:num}, "hca":num, "logistic_k":num,
              "schedule":[[day,home_tid,away_tid],...]},
      "finance": {"tax_line":300000, "notes":"thousands"} }

All money is in Basketball GM "thousands" units. The sim block mirrors
simulate_league's win-probability model (see simmodel.sim_client_inputs) so
client sims agree with the server-side Monte Carlo.
"""

import json
from pathlib import Path
from typing import Any

from .core import (
    ALL_PLAYERS_BY_PID,
    RATING_LABELS,
    active_players,
    current_season,
    draft_prospects,
    latest_rating,
    latest_regular_stat,
    made_pct,
    per_game,
    player_name,
    safe_float,
    safe_int,
    stat_gp,
    team_payroll,
    team_sort_key,
    total_rebounds,
)
from .derived import fantasy_pts
from .finance import FIN_SOFT_CAP, team_dead_money, team_retention_delta
from .simmodel import sim_client_inputs

# Fallback team identity colors (from the PLAN's hand-curated TEAM_IDENTITY
# registry). identity.py is the canonical owner; appdata prefers importing it
# and only uses this copy when that module is not present yet.
_FALLBACK_COLORS: dict[int, dict[str, str]] = {
    0: {"primary": "#1B2440", "secondary": "#E0531F", "chart": "#E0531F"},
    1: {"primary": "#4A3B5C", "secondary": "#C13B33", "chart": "#9966CC"},
    2: {"primary": "#2C5545", "secondary": "#EAE4C8", "chart": "#2F8C57"},
    3: {"primary": "#23305A", "secondary": "#F58426", "chart": "#F5A623"},
    4: {"primary": "#1D4F91", "secondary": "#6FA8DC", "chart": "#4C8CE0"},
    5: {"primary": "#1F2E4E", "secondary": "#F2A900", "chart": "#56719F"},
    6: {"primary": "#1E4230", "secondary": "#E8B321", "chart": "#8B5E34"},
    7: {"primary": "#1C5E52", "secondary": "#2FA98C", "chart": "#2FA98C"},
    8: {"primary": "#1C3557", "secondary": "#C8102E", "chart": "#D22B3E"},
    9: {"primary": "#232F55", "secondary": "#FFC72C", "chart": "#FFD23F"},
}


def _team_colors(tid: int, team: dict[str, Any]) -> dict[str, str]:
    """Identity colors for a team: identity.py registry, else the PLAN fallback,
    else the export's own colors (keeps the payload data-driven for new teams)."""
    try:
        from .identity import TEAM_IDENTITY  # created by the identity agent

        ident = TEAM_IDENTITY.get(tid)
        if ident:
            return {
                "primary": str(ident.get("primary", "#1B2440")),
                "secondary": str(ident.get("secondary", "#E0531F")),
                "chart": str(ident.get("chart", ident.get("secondary", "#E0531F"))),
            }
    except Exception:
        pass
    if tid in _FALLBACK_COLORS:
        return dict(_FALLBACK_COLORS[tid])
    export_colors = [c for c in (team.get("colors") or []) if isinstance(c, str)]
    primary = export_colors[0] if export_colors else "#39424f"
    secondary = export_colors[1] if len(export_colors) > 1 else "#8899aa"
    return {"primary": primary, "secondary": secondary, "chart": secondary}


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    # round() then re-add 0.0 to normalize -0.0 -> 0.0 for deterministic JSON
    return round(float(value), digits) + 0.0


def _player_entry(player: dict[str, Any], season: int, start_season: int) -> dict[str, Any]:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    contract = player.get("contract") or {}
    fpts_total = fantasy_pts(stat)
    born_year = (player.get("born") or {}).get("year")
    jersey = player.get("jerseyNumber")
    return {
        "pid": safe_int(player.get("pid"), -1),
        "name": player_name(player),
        "pos": str(rating.get("pos") or ""),
        "age": (season - born_year) if isinstance(born_year, int) else None,
        "tid": safe_int(player.get("tid"), -1),
        "jersey": str(jersey) if jersey not in (None, "") else None,
        "ovr": safe_int(rating.get("ovr")),
        "pot": safe_int(rating.get("pot")),
        "salary": int(round(safe_float(contract.get("amount")))),
        "exp": safe_int(contract.get("exp")) if contract.get("exp") is not None else None,
        "value": _round(safe_float(player.get("value")), 1),
        "pg": {
            "pts": _round(per_game(stat, "pts")),
            "trb": _round(total_rebounds(stat) / gp if gp else 0.0),
            "ast": _round(per_game(stat, "ast")),
            "stl": _round(per_game(stat, "stl")),
            "blk": _round(per_game(stat, "blk")),
            "tov": _round(per_game(stat, "tov")),
            "min": _round(per_game(stat, "min")),
            "fg_pct": _round(made_pct(stat.get("fg"), stat.get("fga"))),
            "tp_pct": _round(made_pct(stat.get("tp"), stat.get("tpa"))),
            "ft_pct": _round(made_pct(stat.get("ft"), stat.get("fta"))),
            "fpts": _round(fpts_total / gp) if (fpts_total is not None and gp) else None,
        },
        "ratings": {key: safe_int(rating.get(key)) for key in RATING_LABELS},
        "skills": [str(s) for s in (rating.get("skills") or [])],
    }


def build_app_data(
    data: dict[str, Any],
    teams: list[dict[str, Any]] | None = None,
    players: list[dict[str, Any]] | None = None,
    season: int | None = None,
    start_season: int = 2026,
) -> dict[str, Any]:
    """Build the shared client payload dict from a league export.

    ``teams``/``players``/``season`` default to the same selections build.py
    makes, so the standalone call and the build-time call produce identical
    payloads. Deterministic: same export in, same dict out (all floats rounded,
    no wall-clock reads, no RNG).
    """
    if season is None:
        season = current_season(data)
    if teams is None:
        teams = sorted(data.get("teams", []), key=team_sort_key)
    if players is None:
        players = active_players(data)
    if not ALL_PLAYERS_BY_PID:
        # finance retention lookups resolve pids through this registry; build.py
        # populates it, standalone callers (tests) may not have.
        ALL_PLAYERS_BY_PID.update(
            {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
        )

    sim = sim_client_inputs(data, teams, players, season)
    fresh = bool(sim.get("fresh"))

    pool = sorted(
        players + draft_prospects(data),
        key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), player_name(p), safe_int(p.get("pid"))),
    )
    player_entries = [_player_entry(p, season, start_season) for p in pool]

    team_entries: list[dict[str, Any]] = []
    for team in sorted(teams, key=lambda t: safe_int(t.get("tid"), 10**9)):
        tid = safe_int(team.get("tid"), -1)
        if tid < 0 or team.get("disabled"):
            continue
        roster = [p for p in players if safe_int(p.get("tid"), -9) == tid]
        payroll = (
            team_payroll(roster, season)
            + team_dead_money(data, tid, season)
            + team_retention_delta(tid, season)
        )
        team_entries.append({
            "tid": tid,
            "abbrev": str(team.get("abbrev") or f"T{tid}"),
            "region": str(team.get("region") or ""),
            "name": str(team.get("name") or ""),
            "colors": _team_colors(tid, team),
            "strength": _round(sim["strengths"].get(tid, 0.0), 4),
            "payroll": int(round(payroll)),
            "record": {
                "w": 0 if fresh else safe_int(sim["wins"].get(tid)),
                "l": 0 if fresh else safe_int(sim["losses"].get(tid)),
            },
        })

    return {
        "season": season,
        "players": player_entries,
        "teams": team_entries,
        "sim": {
            "strengths": {str(tid): _round(value, 4) for tid, value in sim["strengths"].items()},
            "hca": sim["hca"],
            "logistic_k": sim["logistic_k"],
            "schedule": [[safe_int(day), safe_int(home), safe_int(away)] for day, home, away in sim["schedule"]],
        },
        "finance": {"tax_line": FIN_SOFT_CAP, "notes": "thousands"},
    }


def write_app_data(
    out_dir: Path,
    data: dict[str, Any],
    teams: list[dict[str, Any]] | None = None,
    players: list[dict[str, Any]] | None = None,
    season: int | None = None,
    start_season: int = 2026,
) -> Path:
    """Build and write <out>/assets/app-data.json (compact, sorted keys, deterministic)."""
    app = build_app_data(data, teams=teams, players=players, season=season, start_season=start_season)
    path = Path(out_dir) / "assets" / "app-data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(app, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    path.write_text(payload, encoding="utf-8")
    return path
