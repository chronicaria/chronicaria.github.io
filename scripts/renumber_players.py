#!/usr/bin/env python3
"""Renumber players in a Basketball-GM export to realistic jersey numbers.

Rules (deterministic, idempotent — safe to rerun on its own output):

* Real NBA players (non-empty ``imgURL``) keep their existing number when it is
  a plain 0–99 numeral and does not collide with a teammate's kept number.
* Fictional players (no ``imgURL``) — and any real player whose number is
  missing, malformed, or collides — draw a number from a realistic weighted
  pool (0–35 common, 36–45 less so, 50–55 occasional, "00"/77/88/91/95/98/99
  rare), seeded per-pid so the same export always renumbers identically.
* Numbers are unique within each roster (``tid >= 0``).  Free agents,
  prospects and retired players (``tid < 0``) carry no uniqueness constraint.
* The new number is propagated to ``player.jerseyNumber``, to every one of the
  player's ``stats`` rows that already carries a ``jerseyNumber`` key, and to
  the matching (by pid) box-score rows in ``games[].teams[].players[]``.

Usage:
    python3 scripts/renumber_players.py league-data/EXPORT.json --in-place
    python3 scripts/renumber_players.py league-data/EXPORT.json --out other.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict

# Weighted pool of realistic jersey numbers (values are the strings stored in
# the export).  Weights approximate the shape of real NBA number usage.
_POOL: list = []
for _n in range(0, 36):
    _POOL.append((str(_n), 60))
for _n in range(36, 46):
    _POOL.append((str(_n), 30))
for _n in range(50, 56):
    _POOL.append((str(_n), 15))
_POOL.append(("00", 5))
for _n in (77, 88, 91, 95, 98, 99):
    _POOL.append((str(_n), 3))

POOL_VALUES = [v for v, _w in _POOL]
POOL_WEIGHTS = [_w for _v, _w in _POOL]


def is_keepable(number) -> bool:
    """True when an existing number is a plain 0-99 numeral (incl. '00')."""
    if not isinstance(number, str) or not number.isdigit():
        return False
    return 0 <= int(number) <= 99


def draw(pid: int, used) -> str:
    """Deterministically draw a realistic number for pid, avoiding `used`."""
    rng = random.Random("smp-jersey-%d" % pid)
    for _ in range(1000):
        number = rng.choices(POOL_VALUES, weights=POOL_WEIGHTS, k=1)[0]
        if number not in used:
            return number
    # Pool exhausted for this roster (cannot happen with 15-man rosters, but
    # stay total): fall back to the first unused numeral 0-99.
    for n in range(100):
        if str(n) not in used:
            return str(n)
    raise RuntimeError("no jersey numbers left for pid %d" % pid)


def renumber(data: dict) -> dict:
    """Assign numbers in-place; return a stats dict for reporting."""
    players = data.get("players", [])
    by_team = defaultdict(list)
    for player in players:
        by_team[player.get("tid", -1)].append(player)

    assigned = {}  # pid -> new number (str)
    kept_real = reassigned_real = drawn_fictional = 0

    for tid in sorted(by_team):
        roster = sorted(by_team[tid], key=lambda p: p["pid"])
        unique = tid >= 0
        used = set()
        pending = []
        # Pass 1: real players claim their existing numbers.
        for player in roster:
            current = player.get("jerseyNumber")
            if player.get("imgURL") and is_keepable(current) and (
                    not unique or current not in used):
                assigned[player["pid"]] = current
                if unique:
                    used.add(current)
                kept_real += 1
            else:
                pending.append(player)
        # Pass 2: everyone else draws, in pid order.
        for player in pending:
            number = draw(player["pid"], used if unique else set())
            assigned[player["pid"]] = number
            if unique:
                used.add(number)
            if player.get("imgURL"):
                reassigned_real += 1
            else:
                drawn_fictional += 1

    changed = 0
    for player in players:
        number = assigned[player["pid"]]
        if player.get("jerseyNumber") != number:
            changed += 1
        player["jerseyNumber"] = number
        for row in player.get("stats", []):
            if "jerseyNumber" in row:
                row["jerseyNumber"] = number

    box_rows = 0
    for game in data.get("games", []):
        for team in game.get("teams", []):
            for row in team.get("players", []):
                pid = row.get("pid")
                if pid in assigned and "jerseyNumber" in row:
                    row["jerseyNumber"] = assigned[pid]
                    box_rows += 1

    return {
        "players": len(players),
        "changed": changed,
        "kept_real": kept_real,
        "reassigned_real": reassigned_real,
        "drawn_fictional": drawn_fictional,
        "box_rows": box_rows,
        "distribution": Counter(assigned.values()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Renumber players in a BBGM export to realistic jerseys.")
    parser.add_argument("input", help="path to the league export JSON")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--in-place", action="store_true",
                       help="overwrite the input file")
    group.add_argument("--out", help="write the renumbered export here")
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as fh:
        data = json.load(fh)

    report = renumber(data)

    out_path = args.input if args.in_place else args.out
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    dist = report.pop("distribution")
    for key, value in report.items():
        print("%s: %s" % (key, value))
    ordered = sorted(dist.items(), key=lambda kv: (kv[0] != "00", int(kv[0])))
    print("distribution: " + ", ".join("%s×%d" % (k, v) for k, v in ordered))
    return 0


if __name__ == "__main__":
    sys.exit(main())
