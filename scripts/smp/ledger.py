"""Odds-history ledger for the playoff-odds river chart.

Every CI build simulates the league once (``simulate_league`` in simmodel.py) and
renders the current playoff odds on the home page. This module persists one
snapshot of those odds per build into ``league-data/odds_history.json`` so the
home page can draw how each team's odds moved over the season (PLAN idea B14).

File format (human-readable, chronological, deterministic):

    [
      {
        "season": 2031,
        "phase": 1,
        "games_played": 120,
        "teams": {
          "0": {"po": 0.4213, "finals": 0.1902, "title": 0.0885,
                "proj_w": 24.3, "proj_l": 20.7},
          ...
        }
      },
      ...
    ]

Guard semantics: a snapshot is appended only when its ``(season, phase,
games_played)`` key is strictly greater (tuple compare) than the key of the
last snapshot in the file. Re-running the build on the same export is therefore
a no-op (idempotent), and a stale/older export can never corrupt the
chronological order. An empty or missing file always accepts the first
snapshot.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .core import current_season, phase_value, regular_season_length, safe_float, safe_int

DEFAULT_LEDGER_PATH = "league-data/odds_history.json"


def _snapshot_key(snapshot: dict[str, Any]) -> tuple[int, int, int]:
    """Orderable identity of a snapshot: (season, phase, games_played)."""
    return (
        safe_int(snapshot.get("season"), -1),
        safe_int(snapshot.get("phase"), -1),
        safe_int(snapshot.get("games_played"), -1),
    )


def load_odds_history(path: str = DEFAULT_LEDGER_PATH) -> list[dict[str, Any]]:
    """Read the ledger. Returns [] when the file is missing or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(history, list):
        return []
    return [snap for snap in history if isinstance(snap, dict)]


def _team_odds_map(odds: dict[str, Any]) -> dict[Any, Any]:
    """Accept either the full simulate_league result or its "teams" mapping."""
    if isinstance(odds, dict) and isinstance(odds.get("teams"), dict):
        return odds["teams"]
    return odds if isinstance(odds, dict) else {}


def build_snapshot(data: dict[str, Any], odds: dict[str, Any]) -> dict[str, Any]:
    """One ledger entry from an export + the simulate_league odds for it."""
    season = current_season(data)
    season_len = regular_season_length(data, season) or 45
    teams: dict[str, dict[str, float]] = {}
    for tid, entry in _team_odds_map(odds).items():
        if not isinstance(entry, dict):
            continue
        proj_w = safe_float(entry.get("proj_w"))
        teams[str(safe_int(tid))] = {
            "po": round(safe_float(entry.get("po")), 4),
            "finals": round(safe_float(entry.get("finals")), 4),
            "title": round(safe_float(entry.get("champ", entry.get("title"))), 4),
            "proj_w": round(proj_w, 1),
            "proj_l": round(season_len - proj_w, 1),
        }
    return {
        "season": season,
        "phase": phase_value(data),
        "games_played": len(data.get("games") or []),
        "teams": teams,
    }


def update_odds_ledger(data: dict[str, Any], odds: dict[str, Any], path: str = DEFAULT_LEDGER_PATH) -> bool:
    """Append the current odds snapshot to the ledger when it advances.

    ``odds`` is the structure returned by simulate_league (or just its "teams"
    mapping). Returns True when a snapshot was appended, False on no-op.
    Idempotent: rebuilding the same export (same season/phase/games_played)
    leaves the file byte-identical.
    """
    snapshot = build_snapshot(data, odds)
    if not snapshot["teams"]:
        return False
    history = load_odds_history(path)
    if history:
        latest_key = max(_snapshot_key(snap) for snap in history)
        if _snapshot_key(snapshot) < latest_key:
            return False
        if _snapshot_key(snapshot) == latest_key:
            # Same key: refresh the entry in place if the odds changed (e.g. a
            # re-export at the same day after a roster move). Same export ->
            # identical snapshot -> byte-identical no-op.
            last = history[-1]
            if _snapshot_key(last) == _snapshot_key(snapshot) and last != snapshot:
                history[-1] = snapshot
            else:
                return False
        else:
            history.append(snapshot)
    else:
        history.append(snapshot)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return True
