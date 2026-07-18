#!/usr/bin/env python3
"""Materialize the 2031 offseason roster and contract moves into a BBGM export.

This is a one-time data migration.  The source export predates the website's
hand-maintained Gooners waivers/trades, so those moves are baked in first.  It
then records the fill draft and awarded free-agent contracts requested for the
2031 season.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
from pathlib import Path
from typing import Any

import league_generator as lg


TEAM_TIDS = {
    "Durham": 0,
    "Rochester": 1,
    "Cambridge": 2,
    "Queens": 3,
    "Toronto": 4,
    "Gooning": 5,
    "Waltham": 6,
    "Stony Brook": 7,
    "Manhattan": 8,
    "Ithaca": 9,
}

PRE_FA_COUNTS = {
    0: 4,
    1: 10,
    2: 11,
    3: 6,
    4: 14,
    5: 9,
    6: 11,
    7: 8,
    8: 8,
    9: 11,
}

# One-time website overlays that were not yet present in the raw export.
GOONERS_KEEP_PIDS = {113, 1284, 1293, 1304, 1663, 1729}
GOONERS_RELEASE_PIDS = {1218, 1287, 1386, 1419, 1469, 1694, 1751, 1789, 1857}
TRADE_MOVES = {
    118: 5,   # Espoir Ndinga: Toronto -> Gooning
    1765: 5,  # Ajay Mitchell: Waltham -> Gooning
    1325: 5,  # Trae Young: Waltham -> Gooning
}
TRADE_PICKS = {(2032, 5): 6}  # Gooning's 2032 first -> Waltham


# (round, team, player, annual salary in $M).  Every fill deal is one year.
FILL_SIGNINGS = [
    (1, "Waltham", "Shaedon Sharpe", 35),
    (1, "Rochester", "Cade Cunningham", 32),
    (1, "Gooning", "Grayson Allen", 6),
    (1, "Durham", "Isaiah Evans", 29),
    (1, "Manhattan", "Evan Mobley", 26),
    (1, "Ithaca", "Ed Johnson", 19),
    (1, "Stony Brook", "Asa Newell", 28),
    (1, "Queens", "Devin Booker", 14),
    (2, "Waltham", "Derrick White", 1),
    (2, "Rochester", "Cody Williams", 42),
    (2, "Gooning", "Stephen Curry", 1),
    (2, "Durham", "Nikola Jovic", 25),
    (2, "Manhattan", "OG Anunoby", 22),
    (2, "Ithaca", "Noa Essengue", 1),
    (2, "Stony Brook", "Collin Murray-Boyles", 23),
    (2, "Queens", "Bub Carrington", 1),
    (3, "Rochester", "Jarace Walker", 25),
    (3, "Gooning", "Joel Embiid", 1),
    (3, "Durham", "Josh Giddey", 32),
    (3, "Manhattan", "Walter Clayton Jr.", 21),
    (3, "Ithaca", "Dominic Sims", 1),
    (3, "Stony Brook", "Anthony Edwards", 20),
    (3, "Queens", "Braylon Mullins", 1),
    (4, "Rochester", "Christian Braun", 20),
    (4, "Gooning", "Tahaad Pettiford", 1),
    (4, "Durham", "Jalen Suggs", 20),
    (4, "Manhattan", "Gradey Dick", 17),
    (4, "Ithaca", "Cameron Carr", 1),
    (4, "Stony Brook", "Tyrese Proctor", 17),
    (4, "Queens", "Mouhamed Faye", 1),
    (5, "Rochester", "LaMelo Ball", 16),
    (5, "Gooning", "Cam Whitmore", 1),
    (5, "Durham", "Oso Ighodaro", 16),
    (5, "Manhattan", "Jayson Tatum", 14),
    (5, "Stony Brook", "Mikal Bridges", 12),
    (5, "Queens", "Artrel Roberson", 1),
    (6, "Gooning", "Brayden Burries", 1),
    (6, "Durham", "Kyle Taylor", 17),
    (6, "Manhattan", "Nolan Traore", 17),
    (6, "Stony Brook", "Christian Bell", 15),
    (7, "Durham", "Cam Thomas", 14),
    (7, "Manhattan", "Cedric Coward", 15),
    (7, "Stony Brook", "Ben Sheppard", 14),
    (8, "Durham", "Isaiah Hartenstein", 12),
    (9, "Durham", "Jaren Jackson Jr.", 12),
    (10, "Durham", "Ace Bailey", 30),
    (11, "Durham", "Ante Masic", 14),
]

# (team, player, annual salary in $M, years).
# Josh Adcock remains on his submitted $36M/1-year award; he is the 58th
# signing required for every roster to reach 15.
AWARDED_SIGNINGS = [
    ("Queens", "AJ Dybantsa", 138, 4),
    ("Queens", "Nikola Jokic", 34, 3),
    ("Waltham", "Josh Adcock", 36, 1),
    ("Queens", "Alperen Sengun", 32, 4),
    ("Queens", "Scottie Barnes", 29, 4),
    ("Toronto", "Tyler Tanner", 23, 4),
    ("Waltham", "Tidjane Salaun", 20, 3),
    ("Cambridge", "Zack Braden", 18, 5),
    ("Cambridge", "Matthew Black", 12, 3),
    ("Cambridge", "Quinten Joyner", 3, 3),
    ("Cambridge", "Nikola Topic", 2, 2),
]


def player_name(player: dict[str, Any]) -> str:
    return f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()


def current_rating(player: dict[str, Any], season: int) -> dict[str, Any]:
    rows = [row for row in player.get("ratings", []) if isinstance(row, dict)]
    eligible = [row for row in rows if row.get("season") == season]
    return eligible[-1] if eligible else (rows[-1] if rows else {})


def materialize_website_baseline(data: dict[str, Any], season: int, phase: int) -> None:
    by_pid = {int(player["pid"]): player for player in data.get("players", [])}

    released = set()
    for player in data.get("players", []):
        pid = int(player.get("pid", -1))
        if int(player.get("tid", -99)) == 5 and pid not in GOONERS_KEEP_PIDS:
            player["_fa_bid"] = float((player.get("contract") or {}).get("amount", 0))
            player["tid"] = lg.FREE_AGENT_TID
            released.add(pid)

        draft = player.get("draft") or {}
        if int(draft.get("year", -1)) == season and int(player.get("tid", -99)) >= 0:
            rating = current_rating(player, season)
            born = (player.get("born") or {}).get("year")
            age = season - born if isinstance(born, int) else 22
            salary_m = lg.fa_salary_by_length(
                int(rating.get("ovr", 0)), int(rating.get("pot", 0)), age
            )[0]
            salary = salary_m * 1000
            player.setdefault("contract", {})["amount"] = salary
            for row in player.get("salaries", []):
                if isinstance(row, dict):
                    row["amount"] = salary

    if released != GOONERS_RELEASE_PIDS:
        raise ValueError(f"Unexpected Gooners waiver set: {sorted(released)}")

    for pid, destination in TRADE_MOVES.items():
        player = by_pid[pid]
        from_tid = int(player.get("tid", -1))
        if from_tid == destination:
            raise ValueError(f"Trade for pid {pid} was already materialized")
        player["tid"] = destination
        player.setdefault("transactions", []).append(
            {
                "season": season,
                "phase": phase,
                "tid": destination,
                "type": "trade",
                "fromTid": from_tid,
            }
        )

    matched_picks = set()
    for pick in data.get("draftPicks", []):
        key = (int(pick.get("season", -1)), int(pick.get("originalTid", -1)))
        if key in TRADE_PICKS:
            pick["tid"] = TRADE_PICKS[key]
            matched_picks.add(key)
    if matched_picks != set(TRADE_PICKS):
        raise ValueError(f"Missing trade picks: {sorted(set(TRADE_PICKS) - matched_picks)}")


def event_score(player: dict[str, Any]) -> int:
    raw = max(float(player.get("valueFuzz") or 0) - 45.0, 0.0)
    return int(math.floor(raw + 0.5))


def sign_player(
    data: dict[str, Any],
    by_name: dict[str, dict[str, Any]],
    team: str,
    name: str,
    salary_m: int,
    years: int,
    season: int,
    phase: int,
    eid: int,
) -> None:
    player = by_name[name]
    if int(player.get("tid", -99)) != lg.FREE_AGENT_TID:
        raise ValueError(f"{name} is not a free agent before signing: tid={player.get('tid')}")

    tid = TEAM_TIDS[team]
    amount = salary_m * 1000
    exp = season + years
    contract = {"amount": amount, "exp": exp}

    player["tid"] = tid
    player["contract"] = dict(contract)
    historical = [
        row
        for row in player.get("salaries", [])
        if isinstance(row, dict)
        and isinstance(row.get("season"), int)
        and int(row["season"]) <= season
    ]
    player["salaries"] = historical + [
        {"season": salary_season, "amount": amount}
        for salary_season in range(season + 1, exp + 1)
    ]
    player["numDaysFreeAgent"] = 0
    player["yearsFreeAgent"] = 0
    player["gamesUntilTradable"] = round(0.17 * 45)
    player.pop("numPlayersTradedAwayNormalized", None)
    player.pop("_fa_bid", None)

    transaction = {
        "season": season,
        "phase": phase,
        "tid": tid,
        "type": "freeAgent",
        "eid": eid,
    }
    player.setdefault("transactions", []).append(transaction)
    data.setdefault("events", []).append(
        {
            "type": "freeAgent",
            "pids": [int(player["pid"])],
            "tids": [tid],
            "score": event_score(player),
            "contract": dict(contract),
            "season": season,
            "eid": eid,
        }
    )


def normalize_roster_order(data: dict[str, Any], season: int) -> None:
    for tid in TEAM_TIDS.values():
        roster = [player for player in data.get("players", []) if player.get("tid") == tid]
        roster.sort(
            key=lambda player: (
                -float(player.get("valueNoPot") or 0),
                -int(current_rating(player, season).get("ovr", 0)),
                player_name(player),
            )
        )
        for order, player in enumerate(roster):
            player["rosterOrder"] = order


def validate_final_state(data: dict[str, Any], season: int) -> None:
    counts = {
        tid: sum(1 for player in data.get("players", []) if player.get("tid") == tid)
        for tid in TEAM_TIDS.values()
    }
    if counts != {tid: 15 for tid in TEAM_TIDS.values()}:
        raise ValueError(f"Final roster counts are not all 15: {counts}")

    events = [event for event in data.get("events", []) if isinstance(event.get("eid"), int)]
    eids = [event["eid"] for event in events]
    if len(eids) != len(set(eids)):
        raise ValueError("Duplicate top-level event IDs detected")

    by_name = {player_name(player): player for player in data.get("players", [])}
    expected = [
        (team, name, amount, 1) for _, team, name, amount in FILL_SIGNINGS
    ] + AWARDED_SIGNINGS
    if len(expected) != 58 or len({name for _, name, _, _ in expected}) != 58:
        raise ValueError("Signing manifest must contain 58 unique players")

    for team, name, salary_m, years in expected:
        player = by_name[name]
        amount = salary_m * 1000
        exp = season + years
        if player.get("tid") != TEAM_TIDS[team]:
            raise ValueError(f"Wrong destination for {name}: {player.get('tid')}")
        if player.get("contract") != {"amount": amount, "exp": exp}:
            raise ValueError(f"Wrong contract for {name}: {player.get('contract')}")
        future = [
            row
            for row in player.get("salaries", [])
            if isinstance(row, dict) and int(row.get("season", -1)) > season
        ]
        wanted = [
            {"season": salary_season, "amount": amount}
            for salary_season in range(season + 1, exp + 1)
        ]
        if future != wanted:
            raise ValueError(f"Wrong future salary schedule for {name}: {future}")

    for tid in TEAM_TIDS.values():
        orders = sorted(
            int(player.get("rosterOrder", -1))
            for player in data.get("players", [])
            if player.get("tid") == tid
        )
        if orders != list(range(15)):
            raise ValueError(f"Non-contiguous roster order for tid {tid}: {orders}")


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.setdefault("meta", {})
    if meta.get("offseasonMovesMaterialized"):
        raise ValueError("This export already has materialized offseason moves")

    season = lg.current_season(data)
    phase = lg.phase_value(data)
    if (season, phase) != (2030, 8):
        raise ValueError(f"Expected season 2030/phase 8, got {season}/{phase}")

    materialize_website_baseline(data, season, phase)
    counts = {
        tid: sum(1 for player in data.get("players", []) if player.get("tid") == tid)
        for tid in TEAM_TIDS.values()
    }
    if counts != PRE_FA_COUNTS:
        raise ValueError(f"Website baseline does not match expected rosters: {counts}")

    manifest_names = [name for _, _, name, _ in FILL_SIGNINGS] + [
        name for _, name, _, _ in AWARDED_SIGNINGS
    ]
    players = data.get("players", [])
    matches = {
        name: [player for player in players if player_name(player) == name]
        for name in manifest_names
    }
    missing = sorted(name for name, candidates in matches.items() if not candidates)
    if missing:
        raise ValueError(f"Missing players: {missing}")
    ambiguous = sorted(
        name for name, candidates in matches.items() if len(candidates) != 1
    )
    if ambiguous:
        raise ValueError(f"Ambiguous signing target names: {ambiguous}")
    by_name = {name: candidates[0] for name, candidates in matches.items()}

    eid = max(int(event.get("eid", 0)) for event in data.get("events", [])) + 1
    for _, team, name, salary_m in FILL_SIGNINGS:
        sign_player(data, by_name, team, name, salary_m, 1, season, phase, eid)
        eid += 1
    for team, name, salary_m, years in AWARDED_SIGNINGS:
        sign_player(data, by_name, team, name, salary_m, years, season, phase, eid)
        eid += 1

    normalize_roster_order(data, season)
    meta["offseasonMovesMaterialized"] = True
    meta["offseasonSigningCount"] = 58
    validate_final_state(data, season)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source_mode = args.input.stat().st_mode
    data = json.loads(args.input.read_text(encoding="utf-8"))
    migrated = migrate(data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_text(
        json.dumps(migrated, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.chmod(temp, stat.S_IMODE(source_mode))
    temp.replace(args.output)


if __name__ == "__main__":
    main()
