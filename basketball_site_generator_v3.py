#!/usr/bin/env python3
"""
Generate a simple static HTML basketball league site from a Basketball GM-style JSON export.

Usage:
    python3 basketball_site_generator_v3.py 2029preseason.json --out docs

The generated site is static HTML/CSS/JS. Re-run this script whenever the JSON changes.
"""

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

FREE_AGENT_TID = -1
DRAFT_PROSPECT_TID = -2
RETIRED_TID = -3
TOTALS_TID = -7

RATING_LABELS = {
    "hgt": "Height",
    "stre": "Strength",
    "spd": "Speed",
    "jmp": "Jumping",
    "endu": "Endurance",
    "ins": "Inside",
    "dnk": "Dunks/Layups",
    "ft": "Free Throws",
    "fg": "Mid Range",
    "tp": "Three Pointers",
    "oiq": "Offensive IQ",
    "diq": "Defensive IQ",
    "drb": "Dribbling",
    "pss": "Passing",
    "reb": "Rebounding",
}

RATING_GROUPS = [
    ("Physical", ["hgt", "stre", "spd", "jmp", "endu"]),
    ("Shooting", ["ins", "dnk", "ft", "fg", "tp"]),
    ("Skill", ["oiq", "diq", "drb", "pss", "reb"]),
]

TEAM_RATING_RANK_KEYS = [
    ("hgt", "Hgt"),
    ("stre", "Str"),
    ("spd", "Spd"),
    ("jmp", "Jmp"),
    ("endu", "End"),
    ("ins", "Ins"),
    ("dnk", "Dnk"),
    ("ft", "FT"),
    ("fg", "2Pt"),
    ("tp", "3Pt"),
    ("oiq", "oIQ"),
    ("diq", "dIQ"),
    ("drb", "Drb"),
    ("pss", "Pss"),
    ("reb", "Reb"),
]

AWARD_ROWS = [
    ("mvp", "MVP", "Most Valuable Player"),
    ("dpoy", "DPOY", "Defensive Player of the Year"),
    ("smoy", "6MOY", "Sixth Man of the Year"),
    ("roy", "ROY", "Rookie of the Year"),
    ("mip", "MIP", "Most Improved Player"),
]

DEFAULT_SALARY_CAP = 225000

SCATTER_METRICS = [
    ("pts", "PTS/G"), ("trb", "TRB/G"), ("ast", "AST/G"), ("stl", "STL/G"), ("blk", "BLK/G"),
    ("tov", "TOV/G"), ("min", "MP/G"), ("fgp", "FG%"), ("tpp", "3P%"), ("ftp", "FT%"),
    ("ts", "TS%"), ("efg", "eFG%"), ("usg", "USG%"), ("per", "PER"), ("ortg", "ORtg"), ("drtg", "DRtg"),
    ("obpm", "OBPM"), ("dbpm", "DBPM"), ("bpm", "BPM"), ("vorp", "VORP"), ("ws", "WS"),
    ("age", "Age"), ("ovr", "Ovr"), ("pot", "Pot"),
]

TEAM_PALETTE = [
    "#5b9dff", "#ff7e67", "#3fbf72", "#f2c14e", "#b78aff",
    "#4fd8d2", "#ff8ad4", "#c0d860", "#ff9f40", "#9aa7ff",
]

# Set by generate_site; used for footers and page chrome.
SITE_META: dict[str, Any] = {"season": None, "day": None}

# Set by generate_site; lets deep render helpers resolve any pid (incl. retired/prospects).
ALL_PLAYERS_BY_PID: dict[int, dict[str, Any]] = {}

FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<text y='.9em' font-size='90'>🏀</text></svg>"
)


def team_palette_by_tid(teams: list[dict[str, Any]]) -> dict[int, str]:
    """Stable distinct color per team (the JSON's own colors are not distinct)."""
    ordered = sorted(
        (t for t in teams if t.get("tid") is not None and not t.get("disabled")),
        key=lambda t: team_abbrev(t),
    )
    return {int(t["tid"]): TEAM_PALETTE[i % len(TEAM_PALETTE)] for i, t in enumerate(ordered)}

def team_dot(tid: Any, palette: dict[int, str]) -> str:
    color = palette.get(safe_int(tid, -1), "#666")
    return f'<span class="team-dot" style="background:{color}" aria-hidden="true"></span>'


PER_GAME_FIELDS = [
    "fg", "fga", "tp", "tpa", "ft", "fta", "orb", "drb", "ast", "tov",
    "stl", "blk", "ba", "pf", "pts",
]

SHOT_FIELDS = [
    "fgAtRim", "fgaAtRim", "fgLowPost", "fgaLowPost", "fgMidRange", "fgaMidRange",
    "tp", "tpa", "dd", "td", "qd", "fxf",
]

TOTAL_STAT_FIELDS = sorted(set(PER_GAME_FIELDS + SHOT_FIELDS + ["gp", "gs", "min", "pm"]))


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def slugify(value: str, fallback: str = "item") -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or fallback


def get_attr_value(value: Any, season: int | None = None) -> Any:
    """Basketball GM exports sometimes store attributes as [{start, value}, ...]."""
    if isinstance(value, list) and value and all(isinstance(x, dict) and "value" in x for x in value):
        chosen = value[0].get("value")
        chosen_start = -10**9
        for item in value:
            start = item.get("start")
            start_cmp = -10**9 if start is None else int(start)
            if season is None or start_cmp <= season:
                if start_cmp >= chosen_start:
                    chosen = item.get("value")
                    chosen_start = start_cmp
        return chosen
    return value


def current_season(data: dict[str, Any]) -> int:
    ga = data.get("gameAttributes", {})
    if isinstance(ga.get("season"), int):
        return ga["season"]

    seasons: list[int] = []
    for player in data.get("players", []):
        seasons.extend(r.get("season") for r in player.get("ratings", []) if isinstance(r.get("season"), int))
        seasons.extend(s.get("season") for s in player.get("stats", []) if isinstance(s.get("season"), int))
    return max(seasons) if seasons else 0


def fmt_number(value: Any, digits: int = 1, blank_zero: bool = False) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if not math.isfinite(number):
        return "—"
    if blank_zero and abs(number) < 1e-12:
        return "—"
    if digits == 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else fmt_number(value, digits)


def fmt_ratio(value: float | None, digits: int = 3) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    out = f"{value:.{digits}f}"
    if out.startswith("0"):
        out = out[1:]
    elif out.startswith("-0"):
        out = "-" + out[2:]
    return out


def fmt_money(amount: Any) -> str:
    if amount is None:
        return "—"
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return esc(amount)

    # Basketball GM salaries are stored in thousands of dollars: 26000 -> $26M.
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)
    if magnitude >= 1000:
        millions = magnitude / 1000
        if abs(millions - round(millions)) < 1e-9:
            return f"{sign}${int(round(millions))}M"
        return sign + f"${millions:.2f}M".rstrip("0").rstrip(".")
    return f"{sign}${int(round(magnitude))}K"


def fmt_contract(player: dict[str, Any], compact: bool = False) -> str:
    contract = player.get("contract") or {}
    amount = contract.get("amount")
    exp = contract.get("exp")
    if amount is None and exp is None:
        return "—"
    if compact:
        return fmt_money(amount)
    if exp is None:
        return fmt_money(amount)
    return f"{fmt_money(amount)}/{esc(exp)}"


def fmt_height(inches: Any) -> str:
    try:
        inches = int(inches)
    except (TypeError, ValueError):
        return "—"
    return f"{inches // 12}'{inches % 12}\""


def player_name(player: dict[str, Any]) -> str:
    return f"{player.get('firstName', '').strip()} {player.get('lastName', '').strip()}".strip() or f"Player {player.get('pid', '')}"


def team_full_name(team: dict[str, Any]) -> str:
    return f"{team.get('region', '').strip()} {team.get('name', '').strip()}".strip() or f"Team {team.get('tid', '')}"


def team_sort_key(team: dict[str, Any]) -> tuple[str, int]:
    return (team_full_name(team).lower(), int(team.get("tid", 10**9)))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def get_salary_cap(data: dict[str, Any]) -> float:
    cap = (data.get("gameAttributes") or {}).get("salaryCap")
    try:
        cap = float(cap)
    except (TypeError, ValueError):
        cap = DEFAULT_SALARY_CAP
    return cap if cap > 0 else DEFAULT_SALARY_CAP


def player_current_salary(player: dict[str, Any], season: int | None = None) -> float:
    """Return the player's current annual salary in Basketball GM salary units."""
    contract = player.get("contract") or {}
    amount = contract.get("amount")
    if amount is not None:
        try:
            return float(amount)
        except (TypeError, ValueError):
            pass

    salaries = [x for x in player.get("salaries", []) if isinstance(x, dict)]
    if salaries:
        chosen = None
        if season is not None:
            exact = [salary for salary in salaries if salary.get("season") == season]
            if exact:
                chosen = exact[-1]
            else:
                future = [salary for salary in salaries if isinstance(salary.get("season"), int) and salary.get("season") >= season]
                chosen = min(future, key=lambda salary: salary.get("season", 10**9), default=None)
        if chosen is None:
            chosen = max(salaries, key=lambda salary: salary.get("season", -10**9))
        try:
            return float(chosen.get("amount") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def team_payroll(roster: Iterable[dict[str, Any]], season: int | None = None) -> float:
    return sum(player_current_salary(player, season) for player in roster)


def salary_cap_html(payroll: float, cap: float) -> str:
    pct = 0.0 if cap <= 0 else max(0.0, min(100.0, 100.0 * payroll / cap))
    floor = SITE_META.get("min_payroll")
    status = "over" if cap > 0 and payroll > cap else "under"
    note = ""
    floor_mark = ""
    if floor and cap > 0:
        floor_pct = max(0.0, min(100.0, 100.0 * floor / cap))
        floor_mark = f'<i class="floor-mark" style="left: {floor_pct:.1f}%" title="Salary floor {fmt_money(floor)}"></i>'
        if payroll < floor:
            note = f'<p class="salary-note delta-down">{fmt_money(floor - payroll)} below the {fmt_money(floor)} salary floor</p>'
    if cap > 0 and payroll > cap:
        note = f'<p class="salary-note delta-down">{fmt_money(payroll - cap)} over the cap</p>'
    elif not note and cap > 0:
        note = f'<p class="salary-note muted">{fmt_money(cap - payroll)} in cap space</p>'
    return f"""
    <div class="salary-summary {status}">
      <div class="salary-copy"><span>Payroll</span><strong>{fmt_money(payroll)} / {fmt_money(cap)}</strong></div>
      <div class="salary-bar" aria-hidden="true"><span style="width: {pct:.1f}%"></span>{floor_mark}</div>
      {note}
    </div>
    """


def latest_team_season(team: dict[str, Any], season: int | None = None) -> dict[str, Any]:
    seasons = [row for row in team.get("seasons", []) if isinstance(row, dict)]
    if season is not None:
        same = [row for row in seasons if row.get("season") == season]
        if same:
            return same[-1]
        eligible = [row for row in seasons if isinstance(row.get("season"), int) and row.get("season") <= season]
        if eligible:
            seasons = eligible
    return max(seasons, key=lambda row: row.get("season", -10**9), default={})


def latest_team_stat(team: dict[str, Any], season: int | None = None, playoffs: bool = False) -> dict[str, Any]:
    rows = [row for row in team.get("stats", []) if isinstance(row, dict) and bool(row.get("playoffs")) == playoffs]
    if season is not None:
        same = [row for row in rows if row.get("season") == season]
        if same:
            return same[-1]
        eligible = [row for row in rows if isinstance(row.get("season"), int) and row.get("season") <= season]
        if eligible:
            rows = eligible
    return max(rows, key=lambda row: row.get("season", -10**9), default={})


def team_has_exact_season_data(team: dict[str, Any], season: int) -> bool:
    has_season_row = any(isinstance(row, dict) and row.get("season") == season for row in team.get("seasons", []))
    has_stat_row = any(
        isinstance(row, dict) and row.get("season") == season and not row.get("playoffs")
        for row in team.get("stats", [])
    )
    return has_season_row or has_stat_row


def active_teams_for_season(teams: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    active = [team for team in teams if team_has_exact_season_data(team, season)]
    return active or teams


def win_pct(won: Any, lost: Any) -> float | None:
    try:
        won = float(won or 0)
        lost = float(lost or 0)
    except (TypeError, ValueError):
        return None
    games = won + lost
    if games <= 0:
        return None
    return won / games


def fmt_win_pct(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    text = f"{value:.3f}"
    if text.startswith("0"):
        text = text[1:]
    return text


def fmt_record(won: Any, lost: Any) -> str:
    if won is None and lost is None:
        return "—"
    return f"{fmt_number(safe_float(won), 0)}-{fmt_number(safe_float(lost), 0)}"


def plus_minus_class(value: Any) -> str:
    number = safe_float(value, 0.0)
    if number > 0:
        return "delta-up"
    if number < 0:
        return "delta-down"
    return ""


def fmt_signed(value: Any, digits: int = 1) -> str:
    number = safe_float(value, float("nan"))
    if not math.isfinite(number):
        return "—"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{digits}f}"


def team_conference_name(team_or_season: dict[str, Any], confs_by_cid: dict[int, str]) -> str:
    cid = team_or_season.get("cid")
    return confs_by_cid.get(cid, f"Conference {cid}" if cid is not None else "Independent")


def team_division_name(team_or_season: dict[str, Any], divs_by_did: dict[int, str]) -> str:
    did = team_or_season.get("did")
    return divs_by_did.get(did, f"Division {did}" if did is not None else "Division")


def initials(player: dict[str, Any]) -> str:
    parts = [player.get("firstName", ""), player.get("lastName", "")]
    letters = "".join(part[:1] for part in parts if part)
    return esc((letters or "?").upper())


def latest_rating(player: dict[str, Any], season: int | None = None) -> dict[str, Any]:
    ratings = [r for r in player.get("ratings", []) if isinstance(r, dict)]
    if season is not None:
        eligible = [r for r in ratings if r.get("season", -10**9) <= season]
        if eligible:
            ratings = eligible
    return max(ratings, key=lambda r: r.get("season", -10**9), default={})


def previous_rating(player: dict[str, Any], rating: dict[str, Any]) -> dict[str, Any]:
    season = rating.get("season")
    ratings = [r for r in player.get("ratings", []) if isinstance(r, dict) and r.get("season", -10**9) < season]
    return max(ratings, key=lambda r: r.get("season", -10**9), default={})


def rating_delta_html(player: dict[str, Any], key: str, rating: dict[str, Any]) -> str:
    value = rating.get(key)
    if value is None:
        return "—"
    prev = previous_rating(player, rating).get(key)
    delta = None if prev is None else value - prev
    body = esc(value)
    if delta:
        klass = "delta-up" if delta > 0 else "delta-down"
        sign = "+" if delta > 0 else ""
        body += f" <span class=\"{klass}\">({sign}{delta})</span>"
    return body


def age(player: dict[str, Any], season: int) -> str:
    year = (player.get("born") or {}).get("year")
    if not isinstance(year, int):
        return "—"
    return str(season - year)


def active_players(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        p for p in data.get("players", [])
        if p.get("retiredYear") is None and p.get("tid", RETIRED_TID) >= FREE_AGENT_TID
    ]


def free_agents(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in active_players(data) if p.get("tid") == FREE_AGENT_TID]


def regular_stats_since(player: dict[str, Any], start_season: int) -> list[dict[str, Any]]:
    return sorted(
        [s for s in player.get("stats", []) if not s.get("playoffs") and s.get("season", -10**9) >= start_season],
        key=lambda s: (s.get("season", 0), s.get("tid", 0)),
    )


def playoff_stats_since(player: dict[str, Any], start_season: int) -> list[dict[str, Any]]:
    return sorted(
        [s for s in player.get("stats", []) if s.get("playoffs") and s.get("season", -10**9) >= start_season],
        key=lambda s: (s.get("season", 0), s.get("tid", 0)),
    )


def latest_regular_stat(player: dict[str, Any], start_season: int, season: int | None = None) -> dict[str, Any]:
    rows = regular_stats_since(player, start_season)
    if season is not None:
        same_season = [s for s in rows if s.get("season") == season]
        if same_season:
            rows = same_season
    return max(rows, key=lambda s: (s.get("season", -10**9), s.get("gp", 0)), default={})


def stat_gp(stat: dict[str, Any]) -> float:
    try:
        return float(stat.get("gp") or 0)
    except (TypeError, ValueError):
        return 0.0


def per_game(stat: dict[str, Any], key: str) -> float | None:
    gp = stat_gp(stat)
    if gp <= 0:
        return 0.0
    return float(stat.get(key) or 0) / gp


def per36(stat: dict[str, Any], key: str) -> float | None:
    minutes = safe_float(stat.get("min"))
    if minutes <= 0:
        return None
    return 36.0 * safe_float(stat.get(key)) / minutes


def per36_trb(stat: dict[str, Any]) -> float | None:
    minutes = safe_float(stat.get("min"))
    if minutes <= 0:
        return None
    return 36.0 * total_rebounds(stat) / minutes


def made_pct(made: Any, attempts: Any) -> float | None:
    try:
        made = float(made or 0)
        attempts = float(attempts or 0)
    except (TypeError, ValueError):
        return None
    if attempts <= 0:
        return None
    return 100 * made / attempts


def efg_pct(stat: dict[str, Any]) -> float | None:
    fga = float(stat.get("fga") or 0)
    if fga <= 0:
        return None
    return 100 * (float(stat.get("fg") or 0) + 0.5 * float(stat.get("tp") or 0)) / fga


def ts_pct(stat: dict[str, Any]) -> float | None:
    denom = 2 * (float(stat.get("fga") or 0) + 0.44 * float(stat.get("fta") or 0))
    if denom <= 0:
        return None
    return 100 * float(stat.get("pts") or 0) / denom


def ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        numerator = float(numerator or 0)
        denominator = float(denominator or 0)
    except (TypeError, ValueError):
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


def turnover_pct(stat: dict[str, Any]) -> float | None:
    denom = float(stat.get("fga") or 0) + 0.44 * float(stat.get("fta") or 0) + float(stat.get("tov") or 0)
    if denom <= 0:
        return None
    return 100 * float(stat.get("tov") or 0) / denom


def total_rebounds(stat: dict[str, Any]) -> float:
    return float(stat.get("orb") or 0) + float(stat.get("drb") or 0)


def total_2p(stat: dict[str, Any]) -> float:
    return float(stat.get("fg") or 0) - float(stat.get("tp") or 0)


def total_2pa(stat: dict[str, Any]) -> float:
    return float(stat.get("fga") or 0) - float(stat.get("tpa") or 0)


def combine_stat_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    combined: dict[str, Any] = {"season": "Career", "tid": TOTALS_TID, "playoffs": rows[0].get("playoffs") if rows else False}
    for key in TOTAL_STAT_FIELDS:
        combined[key] = sum(float(s.get(key) or 0) for s in rows)

    total_min = float(combined.get("min") or 0)
    weighted = ["per", "astp", "blkp", "drbp", "orbp", "stlp", "trbp", "usgp", "drtg", "ortg", "pm100", "onOff100", "obpm", "dbpm"]
    for key in weighted:
        if total_min > 0:
            combined[key] = sum(float(s.get(key) or 0) * float(s.get("min") or 0) for s in rows) / total_min
        else:
            combined[key] = 0

    for key in ["ewa", "ows", "dws", "vorp"]:
        combined[key] = sum(float(s.get(key) or 0) for s in rows)
    return combined


def sort_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return str(value)
    return esc(value)


def td(content: Any, sort: Any = None, cls: str = "", html_content: bool = True, style: str = "") -> str:
    sort_attr = f' data-sort="{sort_value(sort)}"' if sort is not None else ""
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    style_attr = f' style="{esc(style)}"' if style else ""
    body = str(content) if html_content else esc(content)
    return f"<td{cls_attr}{sort_attr}{style_attr}>{body}</td>"


GLOSSARY = {
    "SOS": "Strength of schedule: average win% of remaining opponents",
    "MOV": "Margin of victory per game",
    "GB": "Games behind the leader",
    "PS": "Points scored per game",
    "PA": "Points allowed per game",
    "PER": "Player Efficiency Rating (league average is 15)",
    "WS": "Win Shares: estimated wins contributed",
    "VORP": "Value Over Replacement Player",
    "OBPM": "Offensive Box Plus/Minus per 100 possessions",
    "DBPM": "Defensive Box Plus/Minus per 100 possessions",
    "BPM": "Box Plus/Minus per 100 possessions vs league average",
    "USG%": "Usage: share of team possessions used while on the floor",
    "ORtg": "Points produced per 100 possessions",
    "DRtg": "Points allowed per 100 possessions",
    "eFG%": "Effective FG%: counts threes as 1.5 field goals",
    "TS%": "True shooting: efficiency including threes and free throws",
    "TOV%": "Turnovers per 100 plays",
    "ORB%": "Share of available offensive rebounds grabbed",
    "FT/FGA": "Free throws made per field-goal attempt",
    "GmSc": "Game Score: single-game performance rating",
    "Pace": "Possessions per game",
    "Net": "Net rating: ORtg minus DRtg",
    "PO%": "Simulated chance to finish top 4 and make the playoffs",
    "Seed 1%": "Simulated chance to finish with the best record",
    "Magic#": "Wins (or 5th-place losses) needed to clinch a playoff spot",
    "Elim#": "Losses (or 4th-place wins) until playoff elimination",
    "Value": "Basketball GM trade value (higher = more coveted)",
    "Cap%": "Share of the salary cap",
    "WS/$M": "Win Shares per million of current salary",
    "YWT": "Years with team",
    "Ovr": "Current overall rating",
    "Pot": "Potential rating ceiling",
}


def th(label: str, cls: str = "") -> str:
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    title = GLOSSARY.get(label)
    title_attr = f' title="{esc(title)}"' if title else ""
    return f"<th{cls_attr}{title_attr}>{esc(label)}</th>"


def table_html(headers: list, rows: list[str], table_id: str | None = None, empty_message: str = "No players found.", wrap_cls: str = "") -> str:
    table_id_attr = f' id="{esc(table_id)}"' if table_id else ""
    if not rows:
        return f'<p class="empty-state">{esc(empty_message)}</p>'
    header_html = "".join(th(label) if isinstance(label, str) else th(label[0], label[1]) for label in headers)
    body_html = "\n".join(row if row.lstrip().startswith("<tr") else f"<tr>{row}</tr>" for row in rows)
    wrap_cls_attr = f" {wrap_cls}" if wrap_cls else ""
    return f"""
    <div class="table-wrap{wrap_cls_attr}">
      <table{table_id_attr} data-sortable>
        <thead><tr>{header_html}</tr></thead>
        <tbody>
          {body_html}
        </tbody>
      </table>
    </div>
    """


def team_slug(team: dict[str, Any]) -> str:
    return f"{slugify(team.get('region', 'team'))}-{slugify(team.get('name', str(team.get('tid', ''))))}-{team.get('tid')}"


def player_slug(player: dict[str, Any]) -> str:
    return f"{slugify(player_name(player), 'player')}-{player.get('pid')}"


def team_url(team: dict[str, Any], root: str = "") -> str:
    return f"{root}teams/{team_slug(team)}.html"


def player_url(player: dict[str, Any], root: str = "") -> str:
    return f"{root}players/{player_slug(player)}.html"


def team_label(tid: Any, teams_by_tid: dict[int, dict[str, Any]], root: str = "", as_link: bool = True) -> str:
    if tid == FREE_AGENT_TID:
        return f'<a href="{root}free-agency.html">FA</a>' if as_link else "FA"
    if tid == DRAFT_PROSPECT_TID:
        return "Draft"
    if tid == RETIRED_TID:
        return "Retired"
    if tid == TOTALS_TID:
        return "TOT"
    team = teams_by_tid.get(tid)
    if not team:
        return esc(tid)
    label = esc(team.get("abbrev") or team.get("name") or tid)
    if not as_link:
        return label
    return f'<a href="{team_url(team, root)}">{label}</a>'


def player_link(player: dict[str, Any], root: str = "", show_number: bool = True) -> str:
    number = player.get("jerseyNumber")
    number_html = f'<span class="muted number">{esc(number)}</span> ' if show_number and number not in (None, "") else ""
    skills = latest_rating(player).get("skills") or []
    skill_html = "".join(f'<span class="mini-skill">{esc(skill)}</span>' for skill in skills)
    return f'{number_html}<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a> {skill_html}'


MOOD_LABELS = {"F": "Fame", "L": "Loyalty", "W": "Winning", "$": "Money"}


def mood_html(player: dict[str, Any]) -> str:
    mood = player.get("moodTraits") or []
    if not mood:
        return "—"
    return " ".join(
        f'<span class="mood-chip" title="Values {esc(MOOD_LABELS.get(m, m))}">{esc(m)}</span>'
        for m in mood
    )


def injury_html(player: dict[str, Any]) -> str:
    injury = player.get("injury") or {}
    injury_type = injury.get("type") or "Healthy"
    games = injury.get("gamesRemaining")
    if injury_type == "Healthy" or not injury_type:
        return '<span class="healthy">Healthy</span>'
    games_text = f" ({games} games)" if games else ""
    return f'<span class="injured">{esc(injury_type)}{esc(games_text)}</span>'


def nav_html(teams: list[dict[str, Any]], root: str, active: str = "") -> str:
    def link(label: str, href: str, key: str) -> str:
        klass = "active" if key == active else ""
        return f'<a class="{klass}" href="{href}">{esc(label)}</a>'

    main_links = [
        link("Home", f"{root}index.html", "home"),
        link("Schedule", f"{root}schedule.html", "schedule"),
        link("Players", f"{root}players/index.html", "players"),
        link("Free Agency", f"{root}free-agency.html", "free-agency"),
        link("Draft", f"{root}draft.html", "draft"),
        link("Trade", f"{root}trade.html", "trade"),
        link("History", f"{root}history.html", "history"),
        link("Records", f"{root}records.html", "records"),
    ]
    team_links = []
    for team in sorted(teams, key=team_sort_key):
        key = f"team-{team.get('tid')}"
        klass = "active" if key == active else ""
        team_links.append(
            f'<a class="{klass}" data-tid="{esc(team.get("tid"))}" data-abbrev="{esc(team.get("abbrev", ""))}" '
            f'href="{team_url(team, root)}">{esc(team_full_name(team))}</a>'
        )

    dropdown_class = "team-dropdown active" if active.startswith("team-") else "team-dropdown"
    return f"""
    <header class="site-header">
      <div class="brand"><a href="{root}index.html">SMP Basketball League</a></div>
      <div class="nav-search">
        <input type="search" placeholder="Search players &amp; teams…" data-global-search autocomplete="off" aria-label="Search players and teams">
        <div class="search-results" data-search-results hidden></div>
      </div>
      <nav class="primary-nav">
        {''.join(main_links)}
        <details class="{dropdown_class}">
          <summary>Teams</summary>
          <div class="team-menu" aria-label="Teams">{''.join(team_links)}</div>
        </details>
      </nav>
    </header>
    """


def page_html(title: str, body: str, teams: list[dict[str, Any]], root: str = "", active: str = "") -> str:
    season = SITE_META.get("season")
    day = SITE_META.get("day")
    if season and day:
        freshness = f"Season {season} · updated through Day {day}"
    elif season:
        freshness = f"Season {season}"
    else:
        freshness = ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} — SMP Basketball League</title>
  <link rel="icon" href="{FAVICON}">
  <link rel="stylesheet" href="{root}assets/styles.css">
  <script defer src="{root}assets/site.js"></script>
</head>
<body data-root="{esc(root)}">
  {nav_html(teams, root, active)}
  <main class="page-shell">
    {body}
  </main>
  <footer class="site-footer">SMP Basketball League · {esc(freshness)}</footer>
</body>
</html>
"""


def acquisition_html(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    transactions = [t for t in (player.get("transactions") or []) if isinstance(t, dict)]
    relevant = [t for t in transactions if t.get("type") in ("draft", "trade", "freeAgent")]
    if not relevant:
        return '<span class="muted">—</span>'
    tx = relevant[-1]
    tx_type = tx.get("type")
    season_short = f"'{str(tx.get('season'))[-2:]}" if tx.get("season") else ""
    if tx_type == "draft":
        pick = tx.get("pickNum")
        pick_text = f" #{pick}" if pick else ""
        return f"Draft {esc(season_short)}{esc(pick_text)}"
    if tx_type == "trade":
        from_team = teams_by_tid.get(safe_int(tx.get("fromTid"), -10))
        from_text = f" from {team_abbrev(from_team)}" if from_team else ""
        return f"Trade {esc(season_short)}{esc(from_text)}"
    return f"FA {esc(season_short)}"


def roster_row(player: dict[str, Any], season: int, start_season: int, root: str, teams_by_tid: dict[int, dict[str, Any]] | None = None) -> str:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    return "".join([
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - (player.get("born") or {}).get("year", season) if isinstance((player.get("born") or {}).get("year"), int) else None)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
        td(fmt_contract(player), sort=(player.get("contract") or {}).get("amount")),
        td(injury_html(player), sort=(player.get("injury") or {}).get("gamesRemaining") or 0),
        td(fmt_number(gp, 0), sort=gp),
        td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
        td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts")),
        td(fmt_number((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0, 1), sort=((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0)),
        td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast")),
        td(fmt_number(stat.get("per"), 1), sort=stat.get("per")),
        td(fmt_number(player.get("value"), 1), sort=player.get("value")),
        td(acquisition_html(player, teams_by_tid or {}), sort=((player.get("transactions") or [{}])[-1] or {}).get("season")),
        td(mood_html(player), sort=" ".join(player.get("moodTraits") or [])),
    ])


def roster_table(title: str, players: list[dict[str, Any]], season: int, start_season: int, root: str, table_id: str, teams_by_tid: dict[int, dict[str, Any]] | None = None) -> str:
    headers = ["Name", "Pos", "Age", "Ovr", "Pot", "Contract", "Health", "G", "MP", "PTS", "TRB", "AST", "PER", "Value", "Acquired", "Mood"]
    rows = [roster_row(p, season, start_season, root, teams_by_tid) for p in players]
    return f"""
    <section class="card roster-section">
      <div class="section-title-row">
        <h2>{esc(title)}</h2>
        <span class="count-pill">{len(players)}</span>
      </div>
      {table_html(headers, rows, table_id=table_id, empty_message="No players in this group.")}
    </section>
    """


def team_finances_table(roster: list[dict[str, Any]], season: int, cap: float, data: dict[str, Any] | None = None, tid: int | None = None) -> str:
    seasons = list(range(season, season + 5))
    players = sorted(
        roster,
        key=lambda p: (-safe_float((p.get("contract") or {}).get("amount"), 0.0), player_name(p)),
    )
    headers = ["Pos", "Name", "Cap%"] + [(str(s), "cur-season" if s == season else "") for s in seasons]
    rows = []
    totals = {s: 0.0 for s in seasons}
    for player in players:
        contract = player.get("contract") or {}
        amount = safe_float(contract.get("amount"), 0.0)
        exp = safe_int(contract.get("exp"), season)
        rating = latest_rating(player, season)
        cap_pct = 100.0 * amount / cap if cap > 0 else None
        cap_bar = ""
        if cap_pct is not None:
            bar_w = max(0.0, min(100.0, cap_pct * 4))  # 25% of cap fills the mini bar
            cap_bar = f'<span class="capbar" aria-hidden="true"><i style="width:{bar_w:.0f}%"></i></span>'
        cells = [
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(player_link(player, "../"), sort=player_name(player), cls="name-cell"),
            td(f"{cap_bar}{fmt_number(cap_pct, 1)}", sort=cap_pct, cls="capcell"),
        ]
        for s in seasons:
            if s <= exp and amount > 0:
                totals[s] += amount
                cells.append(td(fmt_money(amount), sort=amount, cls="cur-season" if s == season else ""))
            else:
                cells.append(td("", sort=-1, cls="cur-season" if s == season else ""))
        rows.append("".join(cells))

    # Dead money: released players whose contracts still count against the cap.
    if data is not None and tid is not None:
        for released in data.get("releasedPlayers", []):
            if safe_int(released.get("tid"), -10) != tid:
                continue
            contract = released.get("contract") or {}
            amount = safe_float(contract.get("amount"), 0.0)
            exp = safe_int(contract.get("exp"), season)
            ghost = ALL_PLAYERS_BY_PID.get(safe_int(released.get("pid"), -10))
            name = player_name(ghost) if ghost else f"Released player {released.get('pid')}"
            cap_pct = 100.0 * amount / cap if cap > 0 else None
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Waived; contract still counts against the cap">{esc(name)} <span class="muted small-copy">(dead money)</span></span>', sort=name, cls="name-cell"),
                td(fmt_number(cap_pct, 1), sort=cap_pct, cls="capcell"),
            ]
            for s in seasons:
                if s <= exp and amount > 0:
                    totals[s] += amount
                    cells.append(td(fmt_money(amount), sort=amount, cls=("cur-season dead-cell" if s == season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    totals_cells = [td(""), td("Totals", cls="name-cell total-label"), td("")]
    space_cells = [td(""), td("Free Cap Space", cls="name-cell total-label"), td("")]
    for s in seasons:
        cur = " cur-season" if s == season else ""
        totals_cells.append(td(fmt_money(totals[s]), sort=totals[s], cls=cur.strip()))
        space = cap - totals[s]
        space_cls = ("delta-up" if space > 0 else "delta-down" if space < 0 else "") + cur
        space_cells.append(td(fmt_money(space), sort=space, cls=space_cls.strip()))
    rows.append(f'<tr class="total-row">{"".join(totals_cells)}</tr>')
    rows.append(f'<tr class="total-row">{"".join(space_cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Salaries</h2>
        <span class="muted small-copy">Salary cap {fmt_money(cap)}</span>
      </div>
      {table_html(headers, rows, table_id="team-finances", empty_message="No contracts found.", wrap_cls="fit-table")}
    </section>
    """


def team_vitals_html(team: dict[str, Any], season: int) -> str:
    team_season = latest_team_season(team, season)
    hype = safe_float(team_season.get("hype"), float("nan"))
    att = safe_float(team_season.get("att"))
    gp_home = safe_float(team_season.get("gpHome"))
    cash = safe_float(team_season.get("cash"), float("nan"))
    pop = safe_float(team_season.get("pop"), float("nan"))
    owner = team_season.get("ownerMood") or {}
    owner_total = sum(safe_float(owner.get(k)) for k in ("wins", "playoffs", "money"))
    tiles = []
    if math.isfinite(hype):
        tiles.append(("Hype", f"{hype * 100:.0f}%"))
    if att and gp_home:
        tiles.append(("Avg attendance", f"{att / gp_home:,.0f}"))
    if math.isfinite(cash):
        tiles.append(("Cash", fmt_money(cash)))
    if math.isfinite(pop):
        tiles.append(("Market", f"{pop:.1f}M"))
    tiles.append(("Owner mood", fmt_signed(owner_total, 1)))
    tile_html = "".join(
        f'<div class="vital-tile"><span>{esc(label)}</span><strong>{value}</strong></div>'
        for label, value in tiles
    )
    return f'<div class="vitals-row">{tile_html}</div>'


def team_games_strip(team: dict[str, Any], game_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    involved = [
        item for item in game_items
        if safe_int(item.get("home_tid")) == tid or safe_int(item.get("away_tid")) == tid
    ]
    involved.sort(key=lambda item: (safe_int(item.get("day")), str(item.get("gid"))))
    played = [item for item in involved if is_completed_game_item(item)]
    upcoming = [item for item in involved if not is_completed_game_item(item)]
    chips = []
    for item in played[-5:]:
        result = team_schedule_result(item, tid)
        ot = game_ot_label(item)
        if ot:
            result += f" {ot}"
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        loc = "vs." if safe_int(item.get("home_tid")) == tid else "@"
        cls = "chip-win" if result.startswith("W") else "chip-loss"
        chips.append(
            f'<a class="game-chip {cls}" href="{esc(game_url(item, "../"))}">'
            f'<span>Day {safe_int(item.get("day"))} {loc} {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}</span>'
            f'<strong>{esc(result)}</strong></a>'
        )
    for item in upcoming[:5]:
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        loc = "vs." if safe_int(item.get("home_tid")) == tid else "@"
        chips.append(
            f'<a class="game-chip chip-next" href="{esc(game_url(item, "../"))}">'
            f'<span>Day {safe_int(item.get("day"))}</span>'
            f'<strong>{loc} {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}</strong></a>'
        )
    if not chips:
        return ""
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Form &amp; Upcoming</h2><span class="muted small-copy">last 5 · next 5</span></div>
      <div class="game-strip">{''.join(chips)}</div>
    </section>
    """


def depth_chart_card(roster: list[dict[str, Any]], season: int) -> str:
    buckets = {
        "PG": {"PG", "G"},
        "SG": {"SG", "G", "GF"},
        "SF": {"SF", "F", "GF"},
        "PF": {"PF", "F", "FC"},
        "C": {"C", "FC"},
    }
    columns = []
    for slot, accepted in buckets.items():
        fits = [p for p in roster if (latest_rating(p, season).get("pos") or "") in accepted]
        fits.sort(key=lambda p: -safe_int(latest_rating(p, season).get("ovr")))
        rows = []
        for p in fits[:4]:
            rating = latest_rating(p, season)
            injury = p.get("injury") or {}
            hurt = ' <span class="injured" title="' + esc(injury.get("type", "")) + '">✚</span>' if injury.get("type") and injury.get("type") != "Healthy" else ""
            rows.append(
                f'<li><a class="player-link" href="{player_url(p, "../")}">{esc(player_name(p))}</a>{hurt}'
                f'<span class="leader-value">{esc(rating.get("ovr", "—"))}</span></li>'
            )
        body_rows = "".join(rows) or '<li class="muted">—</li>'
        columns.append(f'<div class="depth-col"><h3>{slot}</h3><ol class="leader-list">{body_rows}</ol></div>')
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Depth Chart</h2><span class="muted small-copy">by position fit, best overall first · ✚ currently injured</span></div>
      <div class="depth-grid">{''.join(columns)}</div>
    </section>
    """


def team_quarter_profile(team: dict[str, Any], data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    own_q = [0.0, 0.0, 0.0, 0.0]
    opp_q = [0.0, 0.0, 0.0, 0.0]
    games = 0
    close_w = close_l = ot_w = ot_l = 0
    biggest_win = None
    biggest_loss = None
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            own, opp = item.get("home_box") or {}, item.get("away_box") or {}
        elif safe_int(item.get("away_tid")) == tid:
            own, opp = item.get("away_box") or {}, item.get("home_box") or {}
        else:
            continue
        games += 1
        own_qtrs = own.get("ptsQtrs") or []
        opp_qtrs = opp.get("ptsQtrs") or []
        for i in range(4):
            own_q[i] += safe_float(own_qtrs[i]) if i < len(own_qtrs) else 0.0
            opp_q[i] += safe_float(opp_qtrs[i]) if i < len(opp_qtrs) else 0.0
        margin = safe_float(own.get("pts")) - safe_float(opp.get("pts"))
        won = margin > 0
        overtimes = safe_int((item.get("game") or {}).get("overtimes"))
        if overtimes:
            ot_w += 1 if won else 0
            ot_l += 0 if won else 1
        if abs(margin) <= 5:
            close_w += 1 if won else 0
            close_l += 0 if won else 1
        if won and (biggest_win is None or margin > biggest_win[0]):
            biggest_win = (margin, item)
        if not won and (biggest_loss is None or margin < biggest_loss[0]):
            biggest_loss = (margin, item)
    if not games:
        return ""

    def qtr_row(label, values, other):
        cells = [td(esc(label), cls="name-cell")]
        for i in range(4):
            diff = values[i] / games - other[i] / games
            cells.append(td(fmt_number(values[i] / games, 1), sort=values[i], style=heat_style(diff, -4, 4, 1)))
        return "<tr>" + "".join(cells) + "</tr>"

    def game_chip(entry, label):
        if not entry:
            return ""
        margin, item = entry
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        own_pts = item_team_points(item, tid)
        opp_pts = item_team_points(item, safe_int(opp_tid))
        return (
            f'<div class="vital-tile"><span>{esc(label)}</span>'
            f'<strong><a href="{esc(game_url(item, "../"))}">{fmt_signed(margin, 0)} vs {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}'
            f' ({fmt_number(own_pts, 0)}-{fmt_number(opp_pts, 0)})</a></strong></div>'
        )

    table = f"""
    <div class="table-wrap fit-table">
      <table class="qtr-table">
        <thead><tr><th></th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th></tr></thead>
        <tbody>
          {qtr_row("Scored", own_q, opp_q)}
          {qtr_row("Allowed", opp_q, own_q)}
        </tbody>
      </table>
    </div>
    """
    tiles = "".join([
        f'<div class="vital-tile"><span>Close games (≤5)</span><strong>{close_w}-{close_l}</strong></div>',
        f'<div class="vital-tile"><span>Overtime</span><strong>{ot_w}-{ot_l}</strong></div>',
        game_chip(biggest_win, "Biggest win"),
        game_chip(biggest_loss, "Worst loss"),
    ])
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Game Profile</h2><span class="muted small-copy">average points by quarter · green = outscoring opponents</span></div>
      <div class="profile-row">
        {table}
        <div class="vitals-row">{tiles}</div>
      </div>
    </section>
    """


def draft_picks_card(data: dict[str, Any], team: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    picks = [
        dp for dp in data.get("draftPicks", [])
        if isinstance(dp, dict) and safe_int(dp.get("tid"), -10) == tid and isinstance(dp.get("season"), int)
    ]
    if not picks:
        return ""
    picks.sort(key=lambda dp: (dp.get("season"), safe_int(dp.get("round"))))
    chips = []
    for dp in picks:
        rnd = "1st" if safe_int(dp.get("round")) == 1 else "2nd"
        own = safe_int(dp.get("originalTid"), -10) == tid
        via = "" if own else f' <span class="muted">via {esc(team_abbrev(teams_by_tid.get(safe_int(dp.get("originalTid"), -10))))}</span>'
        chips.append(f'<span class="pick-chip{" pick-own" if own else " pick-acquired"}">{esc(dp.get("season"))} {rnd}{via}</span>')
    traded_away = [
        dp for dp in data.get("draftPicks", [])
        if isinstance(dp, dict) and safe_int(dp.get("originalTid"), -10) == tid and safe_int(dp.get("tid"), -10) != tid
    ]
    away_note = ""
    if traded_away:
        away_bits = []
        for dp in sorted(traded_away, key=lambda dp: (dp.get("season"), safe_int(dp.get("round")))):
            rnd = "1st" if safe_int(dp.get("round")) == 1 else "2nd"
            holder = team_abbrev(teams_by_tid.get(safe_int(dp.get("tid"), -10)))
            away_bits.append(f"{dp.get('season')} {rnd} → {holder}")
        away_note = f'<p class="muted small-copy">Traded away: {esc(" · ".join(away_bits))}</p>'
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Draft Picks</h2><span class="count-pill">{len(picks)} owned</span></div>
      <div class="pick-row">{''.join(chips)}</div>
      {away_note}
    </section>
    """


def render_team_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, cap: float, data: dict[str, Any] | None = None, game_items: list[dict[str, Any]] | None = None) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = sorted(roster, key=lambda p: (p.get("rosterOrder", 10**9), -latest_rating(p, season).get("ovr", 0), player_name(p)))
    starters = sorted_roster[:5]
    bench = sorted_roster[5:10]
    reserves = sorted_roster[10:]
    team_full = team_full_name(team)
    palette = team_palette_by_tid(teams)
    primary = palette.get(safe_int(team.get("tid"), -1), "#5b9dff")
    secondary = primary
    payroll = team_payroll(sorted_roster, season)
    team_season = latest_team_season(team, season)
    record = fmt_record(team_season.get("won"), team_season.get("lost"))
    streak = streak_text(team_season.get("streak"))
    record_bits = [esc(team.get("abbrev", ""))]
    if record != "—":
        record_bits.append(f"{record}")
    if streak != "—":
        record_bits.append(streak)
    record_bits.append(f"{len(sorted_roster)} players")
    strip = team_games_strip(team, game_items or [], teams_by_tid) if game_items else ""
    picks = draft_picks_card(data, team, teams_by_tid) if data else ""
    profile = team_quarter_profile(team, data, season, teams_by_tid) if data else ""
    body = f"""
    <section class="page-hero team-hero" style="--team-primary:{esc(primary)};--team-secondary:{esc(secondary)}">
      <div>
        <p class="eyebrow">Team</p>
        <h1><button class="fav-star" data-fav-team="{esc(team.get('tid'))}" title="Set as favorite team">★</button>{esc(team_full)}</h1>
        <p class="muted">{' · '.join(record_bits)}</p>
        {team_vitals_html(team, season)}
      </div>
      {salary_cap_html(payroll, cap)}
    </section>
    {strip}
    {profile}
    <h2 class="block-title">Roster</h2>
    {roster_table("Starters", starters, season, start_season, "../", f"team-{team.get('tid')}-starters", teams_by_tid)}
    {roster_table("Bench", bench, season, start_season, "../", f"team-{team.get('tid')}-bench", teams_by_tid)}
    {roster_table("Reserve", reserves, season, start_season, "../", f"team-{team.get('tid')}-reserve", teams_by_tid)}
    {depth_chart_card(sorted_roster, season)}
    <h2 class="block-title">Finances</h2>
    {team_finances_table(sorted_roster, season, cap, data=data, tid=safe_int(team.get("tid")))}
    {picks}
    """
    return page_html(team_full, body, teams, root="../", active=f"team-{team.get('tid')}")


RATING_GROUP_STARTS = {"hgt", "ins", "oiq"}


def free_agent_row(player: dict[str, Any], season: int, root: str, rating_ranges: dict[str, tuple[float, float]]) -> str:
    rating = latest_rating(player, season)
    contract = player.get("contract") or {}
    cells = [
        td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - (player.get("born") or {}).get("year", season) if isinstance((player.get("born") or {}).get("year"), int) else None)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
        td(fmt_money(contract.get("amount")), sort=contract.get("amount")),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
    cells.append(td(mood_html(player), sort=" ".join(player.get("moodTraits") or []), cls="group-start"))
    return "".join(cells)


def render_free_agency_page(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int) -> str:
    sorted_players = sorted(players, key=lambda p: (-latest_rating(p, season).get("ovr", 0), -latest_rating(p, season).get("pot", 0), player_name(p)))

    rating_ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        values = []
        for p in sorted_players:
            value = latest_rating(p, season).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers: list = ["Name", "Pos", "Age", "Ovr", "Pot", "Asking For"]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    headers.append(("Mood", "group-start"))
    rows = [free_agent_row(p, season, "", rating_ranges) for p in sorted_players]
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Free Agency</h1>
        <p class="muted">{len(sorted_players)} available players · Physical / Shooting / Skill ratings · color scaled against this class</p>
      </div>
    </section>
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="free-agents" placeholder="Filter free agents…" aria-label="Filter free agents">
      </div>
      {table_html(headers, rows, table_id="free-agents", empty_message="No free agents found.")}
    </section>
    """
    return page_html("Free Agency", body, teams, root="", active="free-agency")


def render_players_index(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    rostered = [p for p in players if isinstance(p.get("tid"), int) and p.get("tid") >= 0]
    sorted_players = sorted(rostered, key=lambda p: (p.get("tid", 999), p.get("rosterOrder", 9999), player_name(p)))
    headers = [
        "Name", "Team", "Pos", "Age", "Ovr", "Pot", "G", "MP",
        ("Contract", "col-basic"), ("PTS", "col-basic"), ("TRB", "col-basic"), ("AST", "col-basic"), ("PER", "col-basic"),
        ("TS%", "col-adv"), ("USG%", "col-adv"), ("ORtg", "col-adv"), ("DRtg", "col-adv"),
        ("OBPM", "col-adv"), ("DBPM", "col-adv"), ("BPM", "col-adv"), ("VORP", "col-adv"), ("WS", "col-adv"),
        ("Value", "col-adv"),
        ("PTS/36", "col-p36"), ("TRB/36", "col-p36"), ("AST/36", "col-p36"),
        ("STL/36", "col-p36"), ("BLK/36", "col-p36"), ("TOV/36", "col-p36"),
    ]
    rows = []
    for p in sorted_players:
        rating = latest_rating(p, season)
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
        obpm = safe_float(stat.get("obpm"), 0.0)
        dbpm = safe_float(stat.get("dbpm"), 0.0)
        ws = safe_float(stat.get("ows"), 0.0) + safe_float(stat.get("dws"), 0.0)
        rows.append("".join([
            td(player_link(p, "../"), sort=player_name(p), cls="name-cell"),
            td(team_label(p.get("tid"), teams_by_tid, "../"), sort=team_label(p.get("tid"), teams_by_tid, as_link=False)),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(age(p, season), sort=(season - (p.get("born") or {}).get("year", season) if isinstance((p.get("born") or {}).get("year"), int) else None)),
            td(rating_delta_html(p, "ovr", rating), sort=rating.get("ovr")),
            td(rating_delta_html(p, "pot", rating), sort=rating.get("pot")),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_contract(p), sort=(p.get("contract") or {}).get("amount"), cls="col-basic"),
            td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts"), cls="col-basic"),
            td(fmt_number(trb_pg, 1), sort=trb_pg, cls="col-basic"),
            td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast"), cls="col-basic"),
            td(fmt_number(stat.get("per"), 1), sort=stat.get("per"), cls="col-basic"),
            td(fmt_pct(ts_pct(stat)), sort=ts_pct(stat), cls="col-adv"),
            td(fmt_number(stat.get("usgp"), 1), sort=stat.get("usgp"), cls="col-adv"),
            td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg"), cls="col-adv"),
            td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg"), cls="col-adv"),
            td(fmt_number(obpm, 1), sort=obpm, cls="col-adv"),
            td(fmt_number(dbpm, 1), sort=dbpm, cls="col-adv"),
            td(fmt_number(obpm + dbpm, 1), sort=obpm + dbpm, cls="col-adv"),
            td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp"), cls="col-adv"),
            td(fmt_number(ws, 1), sort=ws, cls="col-adv"),
            td(fmt_number(p.get("value"), 1), sort=p.get("value"), cls="col-adv"),
            td(fmt_number(per36(stat, "pts"), 1), sort=per36(stat, "pts"), cls="col-p36"),
            td(fmt_number(per36_trb(stat), 1), sort=per36_trb(stat), cls="col-p36"),
            td(fmt_number(per36(stat, "ast"), 1), sort=per36(stat, "ast"), cls="col-p36"),
            td(fmt_number(per36(stat, "stl"), 1), sort=per36(stat, "stl"), cls="col-p36"),
            td(fmt_number(per36(stat, "blk"), 1), sort=per36(stat, "blk"), cls="col-p36"),
            td(fmt_number(per36(stat, "tov"), 1), sort=per36(stat, "tov"), cls="col-p36"),
        ]))

    palette_teams = sorted((t for t in teams if t.get("tid") is not None and not t.get("disabled")), key=lambda t: team_abbrev(t))
    team_colors = {team_abbrev(t): TEAM_PALETTE[i % len(TEAM_PALETTE)] for i, t in enumerate(palette_teams)}
    chart_players = []
    for p in sorted_players:
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        if gp <= 0:
            continue
        rating = latest_rating(p, season)
        born_year = (p.get("born") or {}).get("year")
        values = {
            "pts": per_game(stat, "pts"), "trb": (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp,
            "ast": per_game(stat, "ast"), "stl": per_game(stat, "stl"), "blk": per_game(stat, "blk"),
            "tov": per_game(stat, "tov"), "min": per_game(stat, "min"),
            "fgp": made_pct(stat.get("fg"), stat.get("fga")), "tpp": made_pct(stat.get("tp"), stat.get("tpa")),
            "ftp": made_pct(stat.get("ft"), stat.get("fta")), "ts": ts_pct(stat), "efg": efg_pct(stat),
            "usg": stat.get("usgp"), "per": stat.get("per"), "ortg": stat.get("ortg"), "drtg": stat.get("drtg"),
            "obpm": stat.get("obpm"), "dbpm": stat.get("dbpm"),
            "bpm": safe_float(stat.get("obpm"), 0.0) + safe_float(stat.get("dbpm"), 0.0),
            "vorp": stat.get("vorp"), "ws": safe_float(stat.get("ows"), 0.0) + safe_float(stat.get("dws"), 0.0),
            "age": (season - born_year) if isinstance(born_year, int) else None,
            "ovr": rating.get("ovr"), "pot": rating.get("pot"),
        }
        clean = {}
        for key, value in values.items():
            number = safe_float(value, float("nan"))
            clean[key] = round(number, 2) if math.isfinite(number) and value is not None else None
        chart_players.append({
            "name": player_name(p),
            "team": team_abbrev_for_tid(p.get("tid"), teams_by_tid),
            "pos": rating.get("pos", ""),
            "url": player_url(p, "../"),
            "v": clean,
        })
    payload = {
        "metrics": [{"key": key, "label": label} for key, label in SCATTER_METRICS],
        "defaultX": "obpm",
        "defaultY": "dbpm",
        "teams": [{"abbrev": abbrev, "color": color} for abbrev, color in team_colors.items()],
        "players": chart_players,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\/")

    def metric_options(selected: str) -> str:
        return "".join(
            f'<option value="{esc(key)}"{" selected" if key == selected else ""}>{esc(label)}</option>'
            for key, label in SCATTER_METRICS
        )

    chart_card = f"""
    <section class="card">
      <div class="toolbar">
        <h2>Scatter</h2>
        <div class="chart-controls">
          <label class="select-label">X
            <select data-chart-axis="x">{metric_options("obpm")}</select>
          </label>
          <label class="select-label">Y
            <select data-chart-axis="y">{metric_options("dbpm")}</select>
          </label>
          <label class="select-label">Pos
            <select data-chart-pos>
              <option value="all">All</option>
              <option value="G">Guards</option>
              <option value="F">Forwards</option>
              <option value="C">Centers</option>
            </select>
          </label>
          <label class="select-label">Min MP/G
            <input type="number" data-chart-minmin value="0" min="0" max="48" step="2">
          </label>
          <label class="select-label check-label">Labels
            <input type="checkbox" data-chart-labels>
          </label>
        </div>
      </div>
      <div class="chart-legend" data-chart-legend></div>
      <div class="chart-wrap">
        <canvas id="player-chart" data-player-chart height="460"></canvas>
        <div class="chart-tooltip" data-chart-tooltip hidden></div>
      </div>
      <p class="muted small-copy">Players with at least one game played. Click a team in the legend to hide or show it; click a dot to open the player.</p>
    </section>
    <script type="application/json" id="player-chart-data">{payload_json}</script>
    """

    body = f"""
    <section class="page-hero">
      <div>
        <h1>Players</h1>
        <p class="muted">{len(sorted_players)} rostered players · free agents are in the <a href="../free-agency.html">Free Agency</a> tab · <a href="../compare.html">compare players →</a></p>
      </div>
    </section>
    {chart_card}
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="players-index" placeholder="Filter players…" aria-label="Filter players">
        <div class="view-toggle" data-view-toggle="players-index">
          <button type="button" class="active" data-view="basic">Per Game</button>
          <button type="button" data-view="p36">Per 36</button>
          <button type="button" data-view="adv">Advanced</button>
        </div>
      </div>
      {table_html(headers, rows, table_id="players-index", empty_message="No players found.")}
    </section>
    """
    return page_html("Players", body, teams, root="../", active="players")


def detail_item(label: str, value: str) -> str:
    return f'<div class="detail-item"><span>{esc(label)}</span><strong>{value}</strong></div>'


def player_summary_rows(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int, start_season: int) -> str:
    regular = regular_stats_since(player, start_season)
    current = [s for s in regular if s.get("season") == season]
    current_stat = current[-1] if current else (regular[-1] if regular else {})
    career = combine_stat_rows(regular) if regular else {}

    def row(label: str, stat: dict[str, Any]) -> str:
        if not stat:
            values = [label] + ["—"] * 8
            sorts = [label] + [None] * 8
        else:
            gp = stat_gp(stat)
            trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
            values = [
                label,
                fmt_number(gp, 0),
                fmt_number(per_game(stat, "min"), 1),
                fmt_number(per_game(stat, "pts"), 1),
                fmt_number(trb_pg, 1),
                fmt_number(per_game(stat, "ast"), 1),
                fmt_pct(made_pct(stat.get("fg"), stat.get("fga"))),
                fmt_pct(made_pct(stat.get("tp"), stat.get("tpa"))),
                fmt_pct(made_pct(stat.get("ft"), stat.get("fta"))),
                fmt_pct(ts_pct(stat)),
                fmt_number(stat.get("per"), 1),
                fmt_number((float(stat.get("ows") or 0) + float(stat.get("dws") or 0)), 1),
            ]
            sorts = [label, gp, per_game(stat, "min"), per_game(stat, "pts"), trb_pg, per_game(stat, "ast"), made_pct(stat.get("fg"), stat.get("fga")), made_pct(stat.get("tp"), stat.get("tpa")), made_pct(stat.get("ft"), stat.get("fta")), ts_pct(stat), stat.get("per"), (float(stat.get("ows") or 0) + float(stat.get("dws") or 0))]
        return "<tr>" + "".join(td(v, sort=s) for v, s in zip(values, sorts)) + "</tr>"

    headers = ["Summary", "G", "MP", "PTS", "TRB", "AST", "FG%", "3P%", "FT%", "TS%", "PER", "WS"]
    return f"""
    <section class="card compact-card">
      <div class="table-wrap summary-wrap">
        <table>
          <thead><tr>{''.join(th(h) for h in headers)}</tr></thead>
          <tbody>
            {row(str(season), current_stat)}
            {row('Career', career)}
          </tbody>
        </table>
      </div>
    </section>
    """


def portrait_html(player: dict[str, Any]) -> str:
    img = player.get("imgURL") or ""
    if img:
        return f'<img class="portrait" alt="{esc(player_name(player))}" src="{esc(img)}">'
    return f'<div class="portrait placeholder" aria-hidden="true">{initials(player)}</div>'


def render_player_hero(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int, start_season: int) -> str:
    rating = latest_rating(player, season)
    team_html = team_label(player.get("tid"), teams_by_tid, "../")
    born = player.get("born") or {}
    born_bits = []
    if born.get("year"):
        born_bits.append(str(born.get("year")))
    if born.get("loc"):
        born_bits.append(esc(born.get("loc")))
    born_html = " · ".join(born_bits) if born_bits else "—"
    draft = player.get("draft") or {}
    if draft and draft.get("year"):
        if draft.get("round") and draft.get("pick"):
            draft_html = f"{draft.get('year')} · Round {draft.get('round')}, Pick {draft.get('pick')}"
        else:
            draft_html = f"{draft.get('year')} · Undrafted"
    else:
        draft_html = "—"
    awards = player.get("awards") or []
    awards_html = "".join(f'<span class="award-chip">{esc(a.get("season", ""))} {esc(a.get("type", ""))}</span>' for a in awards[-8:]) or '<span class="muted">No awards listed</span>'

    relatives = player.get("relatives") or []
    family_bits = []
    for relative in relatives:
        rel_player = ALL_PLAYERS_BY_PID.get(safe_int(relative.get("pid"), -10))
        name = relative.get("name") or (player_name(rel_player) if rel_player else "?")
        rel_type = str(relative.get("type", "relative")).capitalize()
        if rel_player is not None and rel_player.get("retiredYear") is None and safe_int(rel_player.get("tid"), RETIRED_TID) >= FREE_AGENT_TID:
            family_bits.append(f'{esc(rel_type)}: <a href="{player_url(rel_player, "../")}">{esc(name)}</a>')
        else:
            family_bits.append(f"{esc(rel_type)}: {esc(name)}")
    family_html = detail_item("Family", " · ".join(family_bits)) if family_bits else ""
    details = "".join([
        detail_item("Team", team_html),
        detail_item("Position", esc(rating.get("pos", "—"))),
        detail_item("Age", age(player, season)),
        detail_item("Height", fmt_height(player.get("hgt"))),
        detail_item("Weight", f'{esc(player.get("weight", "—"))} lbs' if player.get("weight") else "—"),
        detail_item("Born", born_html),
        detail_item("College", esc(player.get("college") or "—")),
        detail_item("Draft", esc(draft_html)),
        detail_item("Contract", fmt_contract(player)),
        detail_item("Injury", injury_html(player)),
        detail_item("Mood", mood_html(player)),
        family_html,
    ])

    rating_groups_html = []
    for title, keys in RATING_GROUPS:
        rows = []
        for key in keys:
            rows.append(f"""
            <div class="rating-row">
              <span>{esc(RATING_LABELS[key])}</span>
              <strong>{rating_delta_html(player, key, rating)}</strong>
            </div>
            """)
        rating_groups_html.append(f"""
        <div class="rating-group">
          <h3>{esc(title)}</h3>
          {''.join(rows)}
        </div>
        """)

    body = f"""
    <section class="player-hero card">
      <div class="portrait-wrap">{portrait_html(player)}</div>
      <div class="player-intro">
        <p class="eyebrow">Player profile</p>
        <h1>{esc(player_name(player))}</h1>
        <p class="muted">#{esc(player.get('jerseyNumber', '—'))} · {team_html}</p>
        <div class="details-grid">{details}</div>
      </div>
      <div class="rating-panel full-rating-panel">
        <div class="rating-topline">
          <div class="big-rating"><span>Overall</span><strong>{rating_delta_html(player, 'ovr', rating)}</strong></div>
          <div class="big-rating"><span>Potential</span><strong>{rating_delta_html(player, 'pot', rating)}</strong></div>
        </div>
        <div class="rating-groups">{''.join(rating_groups_html)}</div>
        <div class="awards-strip">{awards_html}</div>
      </div>
    </section>
    """
    return body


def per_game_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str) -> str:
    source_rows = rows[:]
    display_rows = rows[:]
    if len(rows) > 1:
        display_rows.append(combine_stat_rows(rows))

    headers = ["Year", "Team", "Age", "G", "GS", "MP", "FG", "FGA", "FG%", "3P", "3PA", "3P%", "2P", "2PA", "2P%", "eFG%", "FT", "FTA", "FT%", "ORB", "DRB", "TRB", "AST", "TOV", "STL", "BLK", "BA", "PF", "PTS"]
    html_rows = []
    for stat in display_rows:
        gp = stat_gp(stat)
        season = stat.get("season")
        year_cell = esc(season)
        age_sort = None
        if isinstance(season, int):
            year_cell = f'<a href="#ratings">{season}</a>'
            born_year = (player.get("born") or {}).get("year")
            if isinstance(born_year, int):
                age_sort = season - born_year
        trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
        fg_pct = made_pct(stat.get("fg"), stat.get("fga"))
        tp_pct = made_pct(stat.get("tp"), stat.get("tpa"))
        two_pct = made_pct(total_2p(stat), total_2pa(stat))
        ft_pct = made_pct(stat.get("ft"), stat.get("fta"))
        html_rows.append("".join([
            td(year_cell, sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_number(per_game(stat, "fg"), 1), sort=per_game(stat, "fg")),
            td(fmt_number(per_game(stat, "fga"), 1), sort=per_game(stat, "fga")),
            td(fmt_pct(fg_pct), sort=fg_pct),
            td(fmt_number(per_game(stat, "tp"), 1), sort=per_game(stat, "tp")),
            td(fmt_number(per_game(stat, "tpa"), 1), sort=per_game(stat, "tpa")),
            td(fmt_pct(tp_pct), sort=tp_pct),
            td(fmt_number(total_2p(stat) / gp if gp else 0, 1), sort=(total_2p(stat) / gp if gp else 0)),
            td(fmt_number(total_2pa(stat) / gp if gp else 0, 1), sort=(total_2pa(stat) / gp if gp else 0)),
            td(fmt_pct(two_pct), sort=two_pct),
            td(fmt_pct(efg_pct(stat)), sort=efg_pct(stat)),
            td(fmt_number(per_game(stat, "ft"), 1), sort=per_game(stat, "ft")),
            td(fmt_number(per_game(stat, "fta"), 1), sort=per_game(stat, "fta")),
            td(fmt_pct(ft_pct), sort=ft_pct),
            td(fmt_number(per_game(stat, "orb"), 1), sort=per_game(stat, "orb")),
            td(fmt_number(per_game(stat, "drb"), 1), sort=per_game(stat, "drb")),
            td(fmt_number(trb_pg, 1), sort=trb_pg),
            td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast")),
            td(fmt_number(per_game(stat, "tov"), 1), sort=per_game(stat, "tov")),
            td(fmt_number(per_game(stat, "stl"), 1), sort=per_game(stat, "stl")),
            td(fmt_number(per_game(stat, "blk"), 1), sort=per_game(stat, "blk")),
            td(fmt_number(per_game(stat, "ba"), 1), sort=per_game(stat, "ba")),
            td(fmt_number(per_game(stat, "pf"), 1), sort=per_game(stat, "pf")),
            td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts")),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2><span class="count-pill">{len(source_rows)}</span></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No stats from the selected seasons.")}
    </section>
    """


def shot_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str) -> str:
    display_rows = rows[:]
    if len(rows) > 1:
        display_rows.append(combine_stat_rows(rows))

    headers = ["Year", "Team", "Age", "G", "GS", "MP", "Rim M", "Rim A", "Rim %", "Post M", "Post A", "Post %", "Mid M", "Mid A", "Mid %", "3P", "3PA", "3P%", "DD", "TD", "QD", "5x5"]
    html_rows = []
    for stat in display_rows:
        gp = stat_gp(stat)
        season = stat.get("season")
        age_sort = None
        if isinstance(season, int):
            born_year = (player.get("born") or {}).get("year")
            if isinstance(born_year, int):
                age_sort = season - born_year
        rim_pct = made_pct(stat.get("fgAtRim"), stat.get("fgaAtRim"))
        post_pct = made_pct(stat.get("fgLowPost"), stat.get("fgaLowPost"))
        mid_pct = made_pct(stat.get("fgMidRange"), stat.get("fgaMidRange"))
        tp_pct = made_pct(stat.get("tp"), stat.get("tpa"))
        html_rows.append("".join([
            td(esc(season), sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_number(per_game(stat, "fgAtRim"), 1), sort=per_game(stat, "fgAtRim")),
            td(fmt_number(per_game(stat, "fgaAtRim"), 1), sort=per_game(stat, "fgaAtRim")),
            td(fmt_pct(rim_pct), sort=rim_pct),
            td(fmt_number(per_game(stat, "fgLowPost"), 1), sort=per_game(stat, "fgLowPost")),
            td(fmt_number(per_game(stat, "fgaLowPost"), 1), sort=per_game(stat, "fgaLowPost")),
            td(fmt_pct(post_pct), sort=post_pct),
            td(fmt_number(per_game(stat, "fgMidRange"), 1), sort=per_game(stat, "fgMidRange")),
            td(fmt_number(per_game(stat, "fgaMidRange"), 1), sort=per_game(stat, "fgaMidRange")),
            td(fmt_pct(mid_pct), sort=mid_pct),
            td(fmt_number(per_game(stat, "tp"), 1), sort=per_game(stat, "tp")),
            td(fmt_number(per_game(stat, "tpa"), 1), sort=per_game(stat, "tpa")),
            td(fmt_pct(tp_pct), sort=tp_pct),
            td(fmt_number(stat.get("dd"), 0), sort=stat.get("dd")),
            td(fmt_number(stat.get("td"), 0), sort=stat.get("td")),
            td(fmt_number(stat.get("qd"), 0), sort=stat.get("qd")),
            td(fmt_number(stat.get("fxf"), 0), sort=stat.get("fxf")),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No shot-location stats from the selected seasons.")}
    </section>
    """


def advanced_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str) -> str:
    display_rows = rows[:]
    if len(rows) > 1:
        display_rows.append(combine_stat_rows(rows))

    headers = ["Year", "Team", "Age", "G", "GS", "MP", "PER", "EWA", "TS%", "3PAr", "FTr", "ORB%", "DRB%", "TRB%", "AST%", "STL%", "BLK%", "TOV%", "USG%", "+/-", "On-Off", "ORtg", "DRtg", "OWS", "DWS", "WS", "WS/48", "OBPM", "DBPM", "BPM", "VORP"]
    html_rows = []
    for stat in display_rows:
        gp = stat_gp(stat)
        season = stat.get("season")
        age_sort = None
        if isinstance(season, int):
            born_year = (player.get("born") or {}).get("year")
            if isinstance(born_year, int):
                age_sort = season - born_year
        ows = float(stat.get("ows") or 0)
        dws = float(stat.get("dws") or 0)
        ws = ows + dws
        minutes = float(stat.get("min") or 0)
        ws48 = ws / (minutes / 48) if minutes > 0 else None
        obpm = float(stat.get("obpm") or 0)
        dbpm = float(stat.get("dbpm") or 0)
        bpm = obpm + dbpm
        pmar = ratio(stat.get("tpa"), stat.get("fga"))
        ftr = ratio(stat.get("fta"), stat.get("fga"))
        html_rows.append("".join([
            td(esc(season), sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_number(stat.get("per"), 1), sort=stat.get("per")),
            td(fmt_number(stat.get("ewa"), 1), sort=stat.get("ewa")),
            td(fmt_pct(ts_pct(stat)), sort=ts_pct(stat)),
            td(fmt_ratio(pmar), sort=pmar),
            td(fmt_ratio(ftr), sort=ftr),
            td(fmt_number(stat.get("orbp"), 1), sort=stat.get("orbp")),
            td(fmt_number(stat.get("drbp"), 1), sort=stat.get("drbp")),
            td(fmt_number(stat.get("trbp"), 1), sort=stat.get("trbp")),
            td(fmt_number(stat.get("astp"), 1), sort=stat.get("astp")),
            td(fmt_number(stat.get("stlp"), 1), sort=stat.get("stlp")),
            td(fmt_number(stat.get("blkp"), 1), sort=stat.get("blkp")),
            td(fmt_number(turnover_pct(stat), 1), sort=turnover_pct(stat)),
            td(fmt_number(stat.get("usgp"), 1), sort=stat.get("usgp")),
            td(fmt_number(stat.get("pm100"), 1), sort=stat.get("pm100"), cls=("delta-up" if float(stat.get("pm100") or 0) > 0 else "delta-down" if float(stat.get("pm100") or 0) < 0 else "")),
            td(fmt_number(stat.get("onOff100"), 1), sort=stat.get("onOff100"), cls=("delta-up" if float(stat.get("onOff100") or 0) > 0 else "delta-down" if float(stat.get("onOff100") or 0) < 0 else "")),
            td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg")),
            td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg")),
            td(fmt_number(ows, 1), sort=ows),
            td(fmt_number(dws, 1), sort=dws),
            td(fmt_number(ws, 1), sort=ws),
            td(fmt_ratio(ws48), sort=ws48),
            td(fmt_number(obpm, 1), sort=obpm),
            td(fmt_number(dbpm, 1), sort=dbpm),
            td(fmt_number(bpm, 1), sort=bpm),
            td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp")),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No advanced stats from the selected seasons.")}
    </section>
    """


def ratings_table(player: dict[str, Any], start_season: int) -> str:
    ratings = sorted([r for r in player.get("ratings", []) if r.get("season", -10**9) >= start_season], key=lambda r: r.get("season", 0))
    headers = ["Year", "Pos", "Ovr", "Pot"] + list(RATING_LABELS.values()) + ["Skills"]
    rows = []
    for rating in ratings:
        cells = [
            td(esc(rating.get("season", "—")), sort=rating.get("season")),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
            td(esc(rating.get("pot", "—")), sort=rating.get("pot")),
        ]
        for key in RATING_LABELS:
            cells.append(td(esc(rating.get(key, "—")), sort=rating.get(key)))
        skills = " ".join(f'<span class="mini-skill">{esc(skill)}</span>' for skill in rating.get("skills") or []) or "—"
        cells.append(td(skills, sort=" ".join(rating.get("skills") or [])))
        rows.append("".join(cells))
    return f"""
    <section class="card stats-section" id="ratings">
      <div class="section-title-row"><h2>Ratings</h2></div>
      {table_html(headers, rows, table_id=f"ratings-{player.get('pid')}", empty_message="No ratings from the selected seasons.")}
    </section>
    """


def build_game_logs(data: dict[str, Any], season: int) -> dict[int, list[dict[str, Any]]]:
    """pid -> chronological list of single-game entries for the season."""
    logs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for game in data.get("games", []):
        if game.get("season") != season:
            continue
        item = normalize_game_item(game)
        if item is None:
            continue
        for own_key, opp_key in (("home_box", "away_box"), ("away_box", "home_box")):
            own = item.get(own_key) or {}
            opp = item.get(opp_key) or {}
            for box in own.get("players") or []:
                pid = safe_int(box.get("pid"), -1)
                if pid < 0:
                    continue
                logs[pid].append({
                    "day": safe_int(item.get("day")),
                    "gid": item.get("gid"),
                    "opp_tid": opp.get("tid"),
                    "home": own_key == "home_box",
                    "team_pts": own.get("pts"),
                    "opp_pts": opp.get("pts"),
                    "box": box,
                    "overtimes": safe_int(game.get("overtimes")),
                    "playoffs": bool(game.get("playoffs")),
                })
    for entries in logs.values():
        entries.sort(key=lambda e: (e["day"], str(e["gid"])))
    return logs


def game_log_table(player: dict[str, Any], entries: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int, root: str) -> str:
    played = [e for e in entries if safe_float((e.get("box") or {}).get("min")) > 0]
    if not played:
        return ""
    headers = ["Day", "Opp", "Result", "MP", "FG", "3P", "FT", "ORB", "TRB", "AST", "TOV", "STL", "BLK", "PF", "PTS", "+/-", "GmSc"]
    rows = []
    for entry in played:
        box = entry["box"]
        opp = team_label(entry.get("opp_tid"), teams_by_tid, root)
        loc = "vs." if entry.get("home") else "@"
        team_pts = safe_float(entry.get("team_pts"))
        opp_pts = safe_float(entry.get("opp_pts"))
        res = "W" if team_pts > opp_pts else "L"
        ot = ""
        overtimes = safe_int(entry.get("overtimes"))
        if overtimes == 1:
            ot = " OT"
        elif overtimes > 1:
            ot = f" {overtimes}OT"
        result_html = (
            f'<a href="{root}games/{esc(game_slug_from_gid(entry.get("gid")))}.html">'
            f'<span class="{"delta-up" if res == "W" else "delta-down"}">{res}</span> '
            f'{fmt_number(team_pts, 0)}-{fmt_number(opp_pts, 0)}{esc(ot)}</a>'
        )
        trb = safe_float(box.get("orb")) + safe_float(box.get("drb"))
        gmsc = game_score_value(box)
        rows.append("".join([
            td(fmt_number(entry.get("day"), 0), sort=entry.get("day")),
            td(f'<span class="muted">{loc}</span> {opp}', sort=team_abbrev_for_tid(entry.get("opp_tid"), teams_by_tid)),
            td(result_html, sort=team_pts - opp_pts),
            td(fmt_minutes(box.get("min")), sort=box.get("min")),
            td(made_attempted(box.get("fg"), box.get("fga")), sort=box.get("fg")),
            td(made_attempted(box.get("tp"), box.get("tpa")), sort=box.get("tp")),
            td(made_attempted(box.get("ft"), box.get("fta")), sort=box.get("ft")),
            td(fmt_number(box.get("orb") or 0, 0), sort=box.get("orb")),
            td(fmt_number(trb, 0), sort=trb),
            td(fmt_number(box.get("ast") or 0, 0), sort=box.get("ast")),
            td(fmt_number(box.get("tov") or 0, 0), sort=box.get("tov")),
            td(fmt_number(box.get("stl") or 0, 0), sort=box.get("stl")),
            td(fmt_number(box.get("blk") or 0, 0), sort=box.get("blk")),
            td(fmt_number(box.get("pf") or 0, 0), sort=box.get("pf")),
            td(fmt_number(box.get("pts") or 0, 0), sort=box.get("pts")),
            td(fmt_signed(box.get("pm") or 0, 0), sort=box.get("pm"), cls=plus_minus_class(box.get("pm"))),
            td(fmt_number(gmsc, 1), sort=gmsc),
        ]))
    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>Game Log · Season {season}</h2><span class="count-pill">{len(played)} games</span></div>
      {table_html(headers, rows, table_id=f"gamelog-{player.get('pid')}", empty_message="No games played yet.")}
    </section>
    """


def ratings_progress_svg(player: dict[str, Any]) -> str:
    ratings = sorted(
        [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)],
        key=lambda r: r["season"],
    )
    if len(ratings) < 2:
        return ""
    seasons = [r["season"] for r in ratings]
    ovr = [safe_float(r.get("ovr")) for r in ratings]
    pot = [safe_float(r.get("pot")) for r in ratings]
    lo = max(0.0, min(min(ovr), min(pot)) - 4)
    hi = min(100.0, max(max(ovr), max(pot)) + 4)
    width, height = 640, 170
    ml, mr, mt, mb = 34, 12, 10, 24
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def x(i: int) -> float:
        return ml + (i / max(1, len(seasons) - 1)) * plot_w

    def y(v: float) -> float:
        return mt + plot_h - ((v - lo) / max(1e-9, hi - lo)) * plot_h

    grid = []
    step = 10 if hi - lo > 25 else 5
    tick = math.ceil(lo / step) * step
    while tick <= hi:
        gy = y(tick)
        grid.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w}" y2="{gy:.1f}" class="chart-grid"/>')
        grid.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{int(tick)}</text>')
        tick += step
    for i, season in enumerate(seasons):
        grid.append(f'<text x="{x(i):.1f}" y="{height - 8}" class="chart-tick" text-anchor="middle">{season}</text>')

    def line(values: list[float], cls: str) -> str:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
        dots = "".join(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" class="{cls}-dot"><title>{seasons[i]}: {int(v)}</title></circle>'
            for i, v in enumerate(values)
        )
        return f'<polyline points="{points}" class="{cls}"/>{dots}'

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Development</h2>
        <span class="muted small-copy"><span class="chart-key chart-key-ovr"></span> Overall · <span class="chart-key chart-key-pot"></span> Potential</span>
      </div>
      <svg viewBox="0 0 {width} {height}" class="dev-chart" role="img" aria-label="Overall and potential by season">
        {''.join(grid)}
        {line(pot, "line-pot")}
        {line(ovr, "line-ovr")}
      </svg>
    </section>
    """


def season_highs_html(player: dict[str, Any], log_entries: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int, root: str) -> str:
    chips = []
    played = [e for e in (log_entries or []) if safe_float((e.get("box") or {}).get("min")) > 0]
    cats = [("pts", "PTS"), ("trb", "TRB"), ("ast", "AST"), ("stl", "STL"), ("blk", "BLK"), ("tp", "3P")]
    for key, label in cats:
        best = None
        for entry in played:
            box = entry["box"]
            value = safe_float(box.get("orb")) + safe_float(box.get("drb")) if key == "trb" else safe_float(box.get(key))
            if best is None or value > best[0]:
                best = (value, entry)
        if best and best[0] > 0:
            value, entry = best
            opp = team_abbrev_for_tid(entry.get("opp_tid"), teams_by_tid)
            chips.append(
                f'<a class="high-chip" href="{root}games/{esc(game_slug_from_gid(entry.get("gid")))}.html" '
                f'title="Day {safe_int(entry.get("day"))} vs {esc(opp)}">'
                f'<span>{esc(label)}</span><strong>{fmt_number(value, 0)}</strong></a>'
            )
    # Career highs: BBGM stores per-season maxes as [value] or [value, gid].
    def max_value(raw: Any) -> float:
        if isinstance(raw, list) and raw:
            return safe_float(raw[0])
        return safe_float(raw)

    career = []
    for key, label in [("ptsMax", "PTS"), ("trbMax", "TRB"), ("astMax", "AST"), ("blkMax", "BLK"), ("stlMax", "STL")]:
        values = [max_value(s.get(key)) for s in player.get("stats", []) if not s.get("playoffs") and s.get(key) is not None]
        if values and max(values) > 0:
            career.append(f"{fmt_number(max(values), 0)} {label}")
    career_html = f'<p class="muted small-copy">Career highs: {esc(" · ".join(career))}</p>' if career else ""
    if not chips and not career_html:
        return ""
    chips_html = f'<div class="high-row">{"".join(chips)}</div>' if chips else ""
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Season Highs · {season}</h2></div>
      {chips_html}
      {career_html}
    </section>
    """


def salary_history_html(player: dict[str, Any]) -> str:
    salaries = [s for s in player.get("salaries", []) if isinstance(s, dict) and isinstance(s.get("season"), int)]
    if not salaries:
        return ""
    by_season: dict[int, float] = {}
    for s in salaries:
        by_season[s["season"]] = safe_float(s.get("amount"))
    seasons = sorted(by_season)
    rows = ["".join([td(esc(s), sort=s), td(fmt_money(by_season[s]), sort=by_season[s])]) for s in seasons]
    total = sum(by_season.values())
    rows.append(f'<tr class="total-row">{td("Total", cls="total-label")}{td(fmt_money(total), sort=total)}</tr>')
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Salary History</h2></div>
      {table_html(["Season", "Salary"], rows, table_id=f"salary-{player.get('pid')}", empty_message="No salary data.", wrap_cls="fit-table")}
    </section>
    """


def injury_history_html(player: dict[str, Any]) -> str:
    injuries = [i for i in player.get("injuries", []) if isinstance(i, dict)]
    if not injuries:
        return ""
    rows = []
    for injury in sorted(injuries, key=lambda i: (-safe_int(i.get("season")), str(i.get("type")))):
        rows.append("".join([
            td(esc(injury.get("season", "—")), sort=injury.get("season")),
            td(esc(injury.get("type", "—")), sort=injury.get("type", "")),
            td(fmt_number(injury.get("games"), 0), sort=injury.get("games")),
        ]))
    total_games = sum(safe_int(i.get("games")) for i in injuries)
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Injury History</h2><span class="count-pill">{total_games} games missed</span></div>
      {table_html(["Season", "Injury", "Games"], rows, table_id=f"injuries-{player.get('pid')}", empty_message="No injuries.", wrap_cls="fit-table")}
    </section>
    """


def render_player_page(player: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int, log_entries: list[dict[str, Any]] | None = None) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    regular = regular_stats_since(player, start_season)
    playoffs = playoff_stats_since(player, start_season)
    body = "".join([
        render_player_hero(player, teams_by_tid, season, start_season),
        player_summary_rows(player, teams_by_tid, season, start_season),
        season_highs_html(player, log_entries or [], teams_by_tid, season, "../"),
        ratings_progress_svg(player),
        game_log_table(player, log_entries or [], teams_by_tid, season, "../"),
        per_game_table(player, regular, teams_by_tid, "../", "Per Game · Regular Season", f"regular-{player.get('pid')}"),
        shot_table(player, regular, teams_by_tid, "../", "Shot Locations and Feats · Regular Season", f"shots-{player.get('pid')}"),
        advanced_table(player, regular, teams_by_tid, "../", "Advanced · Regular Season", f"advanced-{player.get('pid')}"),
        ratings_table(player, start_season),
        '<div class="history-row">' + salary_history_html(player) + injury_history_html(player) + "</div>",
    ])
    if playoffs:
        body += per_game_table(player, playoffs, teams_by_tid, "../", "Per Game · Playoffs", f"playoffs-{player.get('pid')}")
        body += advanced_table(player, playoffs, teams_by_tid, "../", "Advanced · Playoffs", f"playoff-advanced-{player.get('pid')}")
    return page_html(player_name(player), body, teams, root="../", active="players")


def team_stat_per_game(stat: dict[str, Any], key: str) -> float | None:
    gp = safe_float(stat.get("gp"), 0.0)
    if gp <= 0:
        return None
    return safe_float(stat.get(key), 0.0) / gp


def team_mov(stat: dict[str, Any]) -> float | None:
    gp = safe_float(stat.get("gp"), 0.0)
    if gp <= 0:
        return None
    return (safe_float(stat.get("pts"), 0.0) - safe_float(stat.get("oppPts"), 0.0)) / gp


def last_ten_text(last_ten: Any) -> str:
    if not isinstance(last_ten, list) or not last_ten:
        return "—"
    wins = sum(1 for result in last_ten if result)
    return f"{wins}-{len(last_ten) - wins}"


def last_ten_dots(last_ten: Any) -> str:
    if not isinstance(last_ten, list) or not last_ten:
        return "—"
    # BBGM stores most-recent first; show oldest -> newest left to right.
    ordered = list(reversed(last_ten))
    dots = "".join(f'<i class="l10-dot {"l10-w" if result else "l10-l"}"></i>' for result in ordered)
    title = f"Last {len(ordered)}: {last_ten_text(last_ten)}"
    return f'<span class="l10-dots" title="{title}">{dots}</span>'



def streak_text(streak: Any) -> str:
    try:
        streak = int(streak)
    except (TypeError, ValueError):
        return "—"
    if streak > 0:
        return f"Won {streak}"
    if streak < 0:
        return f"Lost {abs(streak)}"
    return "—"


def clinch_html(team_season: dict[str, Any]) -> str:
    marker = team_season.get("clinchedPlayoffs")
    if not marker:
        return ""
    return f' <span class="clinch">{esc(marker)}</span>'


def team_anchor(team: dict[str, Any], root: str = "") -> str:
    return f'<a href="{team_url(team, root)}">{esc(team_full_name(team))}</a>'


def standings_order(teams: list[dict[str, Any]], season: int) -> list[int]:
    rows = []
    for team in teams:
        team_season = latest_team_season(team, season)
        won = safe_float(team_season.get("won"))
        lost = safe_float(team_season.get("lost"))
        pct = win_pct(won, lost)
        rows.append((-(pct if pct is not None else -1), -won, lost, team_full_name(team), safe_int(team.get("tid"))))
    rows.sort()
    return [row[4] for row in rows]


def simulate_playoff_odds(data: dict[str, Any], teams: list[dict[str, Any]], season: int, sims: int = 5000) -> dict[int, dict[str, float]]:
    """Monte Carlo the remaining schedule from regressed scoring margins."""
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    wins0: dict[int, float] = {}
    strength: dict[int, float] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins0[tid] = safe_float(team_season.get("won"))
        gp = safe_float(stat.get("gp"))
        mov = team_mov(stat) or 0.0
        strength[tid] = mov * gp / (gp + 10.0)  # regress early-season margins toward 0

    remaining: list[tuple[int, int]] = []
    items, _ = score_items_for_page(data, teams)
    for item in items:
        if is_completed_game_item(item) or safe_int(item.get("season")) != season:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        if home in wins0 and away in wins0:
            remaining.append((home, away))

    games_left = defaultdict(int)
    for home, away in remaining:
        games_left[home] += 1
        games_left[away] += 1

    rng = random.Random(20290101)
    playoff_count = defaultdict(int)
    seed1_count = defaultdict(int)
    win_total = defaultdict(float)
    probs = {
        (home, away): 1.0 / (1.0 + math.exp(-((strength[home] - strength[away] + 1.5) * 0.16)))
        for home, away in set(remaining)
    }
    for _ in range(sims):
        wins = dict(wins0)
        for matchup in remaining:
            home, away = matchup
            if rng.random() < probs[matchup]:
                wins[home] += 1
            else:
                wins[away] += 1
        order = sorted(tids, key=lambda tid: (-wins[tid], rng.random()))
        for seed, tid in enumerate(order, 1):
            if seed <= 4:
                playoff_count[tid] += 1
            if seed == 1:
                seed1_count[tid] += 1
        for tid in tids:
            win_total[tid] += wins[tid]

    results: dict[int, dict[str, float]] = {}
    for tid in tids:
        results[tid] = {
            "po": playoff_count[tid] / sims,
            "seed1": seed1_count[tid] / sims,
            "proj_w": win_total[tid] / sims,
            "games_left": games_left[tid],
            "wins": wins0[tid],
        }
    return results


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


def playoff_odds_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    odds = simulate_playoff_odds(data, teams, season)
    if not odds or all(o["games_left"] == 0 for o in odds.values()):
        return ""
    season_len = regular_season_length(data, season) or 45
    magic = magic_elimination(teams, season, season_len)
    infos = sorted(odds.items(), key=lambda kv: -kv[1]["po"])
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    rows = []
    for tid, o in infos:
        team = teams_by_tid.get(tid, {})
        proj_w = o["proj_w"]
        proj_l = season_len - proj_w
        po_pct = 100 * o["po"]
        seed1_pct = 100 * o["seed1"]
        note = magic.get(tid, "—")
        note_cls = "delta-up" if note == "Clinched" else "delta-down" if note == "Eliminated" else ""
        rows.append(f'<tr data-tid="{tid}">' + "".join([
            td(f'{team_dot(tid, palette)}{team_anchor(team)}', sort=team_full_name(team), cls="name-cell"),
            td(f"{fmt_number(proj_w, 1)}-{fmt_number(proj_l, 1)}", sort=proj_w),
            td(fmt_number(po_pct, 0) + "%", sort=po_pct, style=heat_style(po_pct, 0, 100, 1)),
            td(fmt_number(seed1_pct, 0) + "%", sort=seed1_pct),
            td(note, sort=note, cls=note_cls),
        ]) + "</tr>")
    headers = ["Team", "Proj W-L", "PO%", "Seed 1%", "Clinch"]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Playoff Odds</h2><span class="muted small-copy">5,000 season simulations of the remaining schedule</span></div>
      {table_html(headers, rows, table_id="playoff-odds", empty_message="Season complete.")}
    </section>
    """


def remaining_sos_by_tid(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[int, float | None]:
    """Average current win% of each team's remaining (unplayed) opponents."""
    pct_by_tid: dict[int, float | None] = {}
    for team in teams:
        team_season = latest_team_season(team, season)
        pct_by_tid[safe_int(team.get("tid"))] = win_pct(team_season.get("won"), team_season.get("lost"))
    items, _ = score_items_for_page(data, teams)
    opps: dict[int, list[float]] = defaultdict(list)
    for item in items:
        if is_completed_game_item(item) or safe_int(item.get("season")) != season:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        if home in pct_by_tid and away in pct_by_tid:
            opps[home].append(pct_by_tid.get(away) or 0.0)
            opps[away].append(pct_by_tid.get(home) or 0.0)
    return {tid: (sum(values) / len(values) if values else None) for tid, values in opps.items()}


def standings_table(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    sos_by_tid = remaining_sos_by_tid(data, teams, season)
    ga = data.get("gameAttributes") or {}
    confs_by_cid = {conf.get("cid"): conf.get("name", f"Conference {conf.get('cid')}") for conf in ga.get("confs", []) if isinstance(conf, dict)}
    season_rows = []
    for team in teams:
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        row = {
            "team": team,
            "season": team_season,
            "stat": stat,
            "won": safe_float(team_season.get("won"), 0.0),
            "lost": safe_float(team_season.get("lost"), 0.0),
            "cid": team_season.get("cid", team.get("cid")),
        }
        row["pct"] = win_pct(row["won"], row["lost"])
        row["mov"] = team_mov(stat)
        season_rows.append(row)

    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in season_rows:
        grouped[row["cid"]].append(row)

    sections = []
    headers = ["Team", "W", "L", "%", "GB", "Home", "Road", "PS", "PA", "MOV", "Streak", "L10", "SOS"]
    for cid in sorted(grouped, key=lambda value: confs_by_cid.get(value, str(value))):
        rows = grouped[cid]
        rows.sort(key=lambda r: (-(r["pct"] if r["pct"] is not None else -1), -r["won"], r["lost"], team_full_name(r["team"])))
        played_rows = [r for r in rows if (r["won"] + r["lost"]) > 0]
        leader = played_rows[0] if played_rows else None
        html_rows = []
        for rank, row in enumerate(rows, 1):
            team = row["team"]
            team_season = row["season"]
            stat = row["stat"]
            if leader and (row["won"] + row["lost"]) > 0:
                gb = ((leader["won"] - row["won"]) + (row["lost"] - leader["lost"])) / 2
                gb_text = "0" if abs(gb) < 1e-12 else fmt_number(gb, 1).rstrip(".0")
            else:
                gb_text = "—"
            mov = row["mov"]
            prev_ranks = SITE_META.get("prev_ranks") or {}
            prev_rank = prev_ranks.get(safe_int(team.get("tid")))
            move_html = ""
            if prev_rank is not None:
                delta = prev_rank - rank
                if delta > 0:
                    move_html = f'<span class="rank-move delta-up" title="Up {delta} since last update">▲{delta}</span>'
                elif delta < 0:
                    move_html = f'<span class="rank-move delta-down" title="Down {-delta} since last update">▼{-delta}</span>'
                else:
                    move_html = '<span class="rank-move rank-flat">·</span>'
            cells = "".join([
                td(f'<span class="row-rank">{rank}</span>{move_html}{team_dot(team.get("tid"), palette)}{team_anchor(team)}{clinch_html(team_season)}', sort=rank, cls="name-cell"),
                td(fmt_number(row["won"], 0), sort=row["won"]),
                td(fmt_number(row["lost"], 0), sort=row["lost"]),
                td(fmt_win_pct(row["pct"]), sort=row["pct"]),
                td(gb_text, sort=gb if leader else None),
                td(fmt_record(team_season.get("wonHome"), team_season.get("lostHome")), sort=team_season.get("wonHome")),
                td(fmt_record(team_season.get("wonAway"), team_season.get("lostAway")), sort=team_season.get("wonAway")),
                td(fmt_number(team_stat_per_game(stat, "pts"), 1), sort=team_stat_per_game(stat, "pts")),
                td(fmt_number(team_stat_per_game(stat, "oppPts"), 1), sort=team_stat_per_game(stat, "oppPts")),
                td(fmt_signed(mov, 1), sort=mov, cls=plus_minus_class(mov)),
                td(streak_text(team_season.get("streak")), sort=team_season.get("streak")),
                td(last_ten_dots(team_season.get("lastTen")), sort=last_ten_text(team_season.get("lastTen"))),
                td(fmt_win_pct(sos_by_tid.get(safe_int(team.get("tid")))), sort=sos_by_tid.get(safe_int(team.get("tid")))),
            ])
            # Top 4 teams make the playoffs: draw the cutoff line above the 5th row.
            row_cls = ' class="playoff-cut"' if rank == 5 else ""
            html_rows.append(f'<tr{row_cls} data-tid="{esc(team.get("tid"))}">{cells}</tr>')
        if len(grouped) == 1:
            title = "Standings"
        else:
            conf_name = confs_by_cid.get(cid, f"Conference {cid}" if cid is not None else "Independent")
            title = f"Standings · {conf_name}"
        sections.append(f'''
        <section class="card home-section standings-section">
          <div class="section-title-row"><h2>{esc(title)}</h2><span class="muted small-copy">Top 4 make the playoffs · SOS = remaining opponents' win%</span></div>
          {table_html(headers, html_rows, table_id=f"standings-{esc(cid)}", empty_message="No standings data found.")}
        </section>
        ''')
    return "".join(sections)


def heat_style(value: Any, lo: float, hi: float, direction: int) -> str:
    """Background tint from red (worst) to green (best) across a column's range."""
    if direction == 0 or value is None:
        return ""
    value = safe_float(value, float("nan"))
    if not math.isfinite(value) or hi - lo <= 1e-12:
        return ""
    frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    if direction < 0:
        frac = 1.0 - frac
    hue = 4 + frac * 126
    return f"background-color: hsla({hue:.0f}, 55%, 41%, .45)"


def team_stats_table(teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    infos = []
    for team in teams:
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        pct = win_pct(team_season.get("won"), team_season.get("lost"))
        infos.append({"team": team, "season": team_season, "stat": stat, "pct": pct, "mov": team_mov(stat)})
    infos.sort(key=lambda info: (-(info["pct"] if info["pct"] is not None else -1), -safe_float((info["season"] or {}).get("won")), team_full_name(info["team"])))

    def stat_pg(key):
        return lambda info: team_stat_per_game(info["stat"], key)

    def shot_pct(made_key, att_key):
        return lambda info: made_pct(info["stat"].get(made_key), info["stat"].get(att_key))

    def two_made_pg(info):
        gp = safe_float(info["stat"].get("gp"), 0.0)
        return (safe_float(info["stat"].get("fg"), 0.0) - safe_float(info["stat"].get("tp"), 0.0)) / gp if gp else None

    def two_att_pg(info):
        gp = safe_float(info["stat"].get("gp"), 0.0)
        return (safe_float(info["stat"].get("fga"), 0.0) - safe_float(info["stat"].get("tpa"), 0.0)) / gp if gp else None

    def two_pct(info):
        s = info["stat"]
        return made_pct(safe_float(s.get("fg"), 0.0) - safe_float(s.get("tp"), 0.0), safe_float(s.get("fga"), 0.0) - safe_float(s.get("tpa"), 0.0))

    def trb_pg(info):
        gp = safe_float(info["stat"].get("gp"), 0.0)
        return (safe_float(info["stat"].get("orb"), 0.0) + safe_float(info["stat"].get("drb"), 0.0)) / gp if gp else None

    # (label, value getter, format, direction) — direction 1: high is good, -1: low is good, 0: no tint.
    columns = [
        ("FG", stat_pg("fg"), "num", 1),
        ("FGA", stat_pg("fga"), "num", 0),
        ("FG%", shot_pct("fg", "fga"), "pct", 1),
        ("3P", stat_pg("tp"), "num", 1),
        ("3PA", stat_pg("tpa"), "num", 0),
        ("3P%", shot_pct("tp", "tpa"), "pct", 1),
        ("2P", two_made_pg, "num", 1),
        ("2PA", two_att_pg, "num", 0),
        ("2P%", two_pct, "pct", 1),
        ("FT", stat_pg("ft"), "num", 1),
        ("FTA", stat_pg("fta"), "num", 0),
        ("FT%", shot_pct("ft", "fta"), "pct", 1),
        ("ORB", stat_pg("orb"), "num", 1),
        ("DRB", stat_pg("drb"), "num", 1),
        ("TRB", trb_pg, "num", 1),
        ("AST", stat_pg("ast"), "num", 1),
        ("TOV", stat_pg("tov"), "num", -1),
        ("STL", stat_pg("stl"), "num", 1),
        ("BLK", stat_pg("blk"), "num", 1),
        ("PF", stat_pg("pf"), "num", -1),
        ("PTS", stat_pg("pts"), "num", 1),
        ("PA", stat_pg("oppPts"), "num", -1),
        ("MOV", lambda info: info["mov"], "signed", 1),
    ]

    values_by_col: list[list[float]] = []
    for _, getter, _, _ in columns:
        col_values = []
        for info in infos:
            value = getter(info)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                col_values.append(float(value))
        values_by_col.append(col_values)

    def fmt_cell(value, fmt):
        if fmt == "pct":
            return fmt_pct(value)
        if fmt == "signed":
            return fmt_signed(value, 1)
        return fmt_number(value, 1)

    headers = ["#", "Team", "G", "W", "L", "%"] + [label for label, _, _, _ in columns]
    rows = []
    for rank, info in enumerate(infos, 1):
        team = info["team"]
        team_season = info["season"]
        stat = info["stat"]
        gp = safe_float(stat.get("gp"), 0.0)
        cells = [
            td(rank, sort=rank),
            td(f'{team_dot(team.get("tid"), palette)}{team_anchor(team)}', sort=team_full_name(team), cls="name-cell"),
            td(fmt_number(gp if gp else None, 0), sort=gp),
            td(fmt_number(team_season.get("won"), 0), sort=team_season.get("won")),
            td(fmt_number(team_season.get("lost"), 0), sort=team_season.get("lost")),
            td(fmt_win_pct(info["pct"]), sort=info["pct"]),
        ]
        for (label, getter, fmt, direction), col_values in zip(columns, values_by_col):
            value = getter(info)
            lo = min(col_values) if col_values else 0.0
            hi = max(col_values) if col_values else 0.0
            cells.append(td(fmt_cell(value, fmt), sort=value, style=heat_style(value, lo, hi, direction)))
        rows.append(f'<tr data-tid="{esc(team.get("tid"))}">{"".join(cells)}</tr>')

    if any(values for values in values_by_col):
        cells = [
            td("—", sort=999),
            td("League average", sort="zzzz", cls="name-cell"),
            td("—"), td("—"), td("—"), td("—"),
        ]
        for (label, getter, fmt, direction), col_values in zip(columns, values_by_col):
            avg = sum(col_values) / len(col_values) if col_values else None
            cells.append(td(fmt_cell(avg, fmt), sort=avg))
        rows.append(f'<tr class="avg-row">{"".join(cells)}</tr>')

    return f'''
    <section class="card home-section">
      <div class="section-title-row"><h2>Team Stats</h2><span class="muted small-copy">Per game · green is good, red is bad</span></div>
      {table_html(headers, rows, table_id="team-stats", empty_message="No team stats available.")}
    </section>
    '''


def season_regular_stat(player: dict[str, Any], season: int) -> dict[str, Any]:
    rows = [s for s in player.get("stats", []) if isinstance(s, dict) and not s.get("playoffs") and s.get("season") == season]
    if not rows:
        return {}
    if len(rows) == 1:
        return dict(rows[0])
    combined = combine_stat_rows(rows)
    combined["season"] = season
    combined["tid"] = rows[-1].get("tid", player.get("tid"))
    return combined


def previous_regular_stat(player: dict[str, Any], season: int) -> dict[str, Any]:
    rows = [s for s in player.get("stats", []) if isinstance(s, dict) and not s.get("playoffs") and isinstance(s.get("season"), int) and s.get("season") < season]
    if not rows:
        return {}
    latest = max(s.get("season", -10**9) for s in rows)
    latest_rows = [s for s in rows if s.get("season") == latest]
    if len(latest_rows) == 1:
        return dict(latest_rows[0])
    combined = combine_stat_rows(latest_rows)
    combined["season"] = latest
    combined["tid"] = latest_rows[-1].get("tid", player.get("tid"))
    return combined


def award_scoreboard(data: dict[str, Any], players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int) -> dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]]:
    team_seasons_by_tid = {team.get("tid"): latest_team_season(team, season) for team in teams}
    team_stats_by_tid = {team.get("tid"): latest_team_stat(team, season) for team in teams}
    current_awards = next((award for award in data.get("awards", []) if award.get("season") == season), {})
    league_games = max([safe_float(row.get("gp"), 0.0) for row in team_stats_by_tid.values()] or [0.0])
    min_gp = max(1.0, league_games * 0.20)

    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], float]] = []
    for player in players:
        stat = season_regular_stat(player, season)
        gp = stat_gp(stat)
        if gp <= 0:
            continue
        rating = latest_rating(player, season)
        candidates.append((player, stat, rating, min(1.0, gp / max(min_gp, 1.0))))

    def team_winp(stat: dict[str, Any]) -> float:
        team_season = team_seasons_by_tid.get(stat.get("tid")) or {}
        return win_pct(team_season.get("won"), team_season.get("lost")) or 0.0

    def box_basics(stat: dict[str, Any]) -> tuple[float, float, float]:
        gp = max(stat_gp(stat), 1.0)
        pts = per_game(stat, "pts") or 0.0
        trb = total_rebounds(stat) / gp
        ast = per_game(stat, "ast") or 0.0
        return pts, trb, ast

    score_lists: dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for player, stat, rating, gp_factor in candidates:
        gp = max(stat_gp(stat), 1.0)
        pts, trb, ast = box_basics(stat)
        ws = safe_float(stat.get("ows"), 0.0) + safe_float(stat.get("dws"), 0.0)
        bpm = safe_float(stat.get("obpm"), 0.0) + safe_float(stat.get("dbpm"), 0.0)
        per = safe_float(stat.get("per"), 0.0)
        ewa = safe_float(stat.get("ewa"), 0.0)
        winp = team_winp(stat)
        mvp = gp_factor * (ewa * 4.0 + per * 1.15 + ws * 2.2 + (pts + trb + ast) * 0.55 + winp * 9.0 + bpm * 0.55)
        dpoy = gp_factor * (
            safe_float(stat.get("dws"), 0.0) * 8.0
            + (per_game(stat, "blk") or 0.0) * 5.0
            + (per_game(stat, "stl") or 0.0) * 3.25
            + trb * 0.35
            + max(0.0, 116.0 - safe_float(stat.get("drtg"), 116.0)) * 0.28
            + safe_float(rating.get("diq"), 0.0) * 0.07
            + safe_float(rating.get("reb"), 0.0) * 0.035
        )
        start_share = safe_float(stat.get("gs"), 0.0) / gp if gp else 1.0
        sixth_penalty = 1.0 if start_share <= 0.5 else max(0.12, 1.05 - start_share)
        smoy = mvp * sixth_penalty + max(0.0, 0.5 - start_share) * 8.0
        rookie = (player.get("draft") or {}).get("year") in {season - 1, season}
        roy = (mvp * 0.85 + safe_float(rating.get("ovr"), 0.0) * 0.18 + safe_float(rating.get("pot"), 0.0) * 0.08) if rookie else -10**9
        prev = previous_regular_stat(player, season)
        prev_gp = max(stat_gp(prev), 1.0)
        prev_pts = per_game(prev, "pts") or 0.0
        prev_trb = total_rebounds(prev) / prev_gp if prev else 0.0
        prev_ast = per_game(prev, "ast") or 0.0
        prev_per = safe_float(prev.get("per"), 0.0)
        prev_ewa = safe_float(prev.get("ewa"), 0.0)
        prev_rating = previous_rating(player, rating)
        ovr_delta = safe_float(rating.get("ovr"), 0.0) - safe_float(prev_rating.get("ovr"), safe_float(rating.get("ovr"), 0.0))
        mip = (
            max(0.0, pts - prev_pts) * 1.6
            + max(0.0, trb - prev_trb) * 0.85
            + max(0.0, ast - prev_ast) * 1.0
            + max(0.0, per - prev_per) * 0.75
            + max(0.0, ewa - prev_ewa) * 2.2
            + max(0.0, ovr_delta) * 0.9
        ) * gp_factor
        raw_scores = {"mvp": mvp, "dpoy": dpoy, "smoy": smoy, "roy": roy, "mip": mip}
        for key, score in raw_scores.items():
            winner = current_awards.get(key) or {}
            if winner.get("pid") == player.get("pid"):
                score += 10000.0
            if score > -10**8:
                score_lists[key].append((score, player, stat))

    for key in score_lists:
        score_lists[key].sort(key=lambda item: (-item[0], player_name(item[1])))
        score_lists[key] = score_lists[key][:5]
    return score_lists


def award_candidate_image(player: dict[str, Any]) -> str:
    img = player.get("imgURL") or ""
    if img:
        return f'<img class="candidate-img" alt="{esc(player_name(player))}" src="{esc(img)}">'
    return f'<div class="candidate-img placeholder" aria-hidden="true">{initials(player)}</div>'


def award_candidate_cell(player: dict[str, Any], stat: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], award_key: str) -> str:
    gp = max(stat_gp(stat), 1.0)
    pts = per_game(stat, "pts") or 0.0
    trb = total_rebounds(stat) / gp
    ast = per_game(stat, "ast") or 0.0
    if award_key == "dpoy":
        line = f"{fmt_number(trb, 1)} TRB · {fmt_number(per_game(stat, 'blk'), 1)} BLK · {fmt_number(per_game(stat, 'stl'), 1)} STL"
    elif award_key == "mip":
        prev = previous_regular_stat(player, int(stat.get("season", 0)))
        delta = pts - (per_game(prev, "pts") or 0.0)
        line = f"{fmt_number(pts, 1)} PTS <span class=\"{plus_minus_class(delta)}\">({fmt_signed(delta, 1)})</span>"
    else:
        line = f"{fmt_number(pts, 1)} PTS · {fmt_number(trb, 1)} TRB · {fmt_number(ast, 1)} AST"
    team = team_label(stat.get("tid", player.get("tid")), teams_by_tid, "")
    return f'''
    <div class="candidate-card">
      {award_candidate_image(player)}
      <div>
        <a class="player-link" href="{player_url(player, '')}">{esc(player_name(player))}</a>
        <span>{team} · {line}</span>
      </div>
    </div>
    '''


def awards_voting_table(data: dict[str, Any], players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int) -> str:
    teams_by_tid = {team["tid"]: team for team in teams}
    scoreboard = award_scoreboard(data, players, teams, season)
    headers = ["Award", "1st", "2nd", "3rd", "4th", "5th"]
    rows = []
    for key, short_label, long_label in AWARD_ROWS:
        cells = [td(f'<strong>{esc(short_label)}</strong><span>{esc(long_label)}</span>', sort=short_label, cls="award-name")]
        for score, player, stat in scoreboard.get(key, [])[:5]:
            cells.append(td(award_candidate_cell(player, stat, teams_by_tid, key), sort=score, cls="candidate-cell"))
        while len(cells) < 6:
            cells.append(td("—"))
        rows.append("".join(cells))
    return f'''
    <section class="card home-section">
      <div class="section-title-row"><h2>Award Voting Sentiment</h2><span class="muted">Top five candidates by current-season production and award signals</span></div>
      {table_html(headers, rows, table_id="award-sentiment", empty_message="No award candidates available.")}
    </section>
    '''


def team_abbrev(team: dict[str, Any] | None, fallback_tid: Any = None) -> str:
    if team:
        return str(team.get("abbrev") or team.get("region") or team.get("name") or fallback_tid or "—")
    return f"T{fallback_tid}" if fallback_tid is not None else "—"


def team_abbrev_for_tid(tid: Any, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    try:
        tid_int = int(tid)
    except (TypeError, ValueError):
        return "—"
    return team_abbrev(teams_by_tid.get(tid_int), tid_int)


def team_full_for_tid(tid: Any, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    try:
        tid_int = int(tid)
    except (TypeError, ValueError):
        return "Unknown Team"
    return team_full_name(teams_by_tid.get(tid_int, {"region": f"Team {tid_int}", "name": ""})).strip()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def active_team_ids(teams: list[dict[str, Any]]) -> list[int]:
    return [int(team.get("tid")) for team in sorted(teams, key=team_sort_key) if team.get("tid") is not None and not team.get("disabled")]


def phase_value(data: dict[str, Any]) -> int:
    return safe_int((data.get("gameAttributes") or {}).get("phase"), 0)


def regular_season_length(data: dict[str, Any], season: int) -> int:
    value = get_attr_value((data.get("gameAttributes") or {}).get("numGames"), season)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def latest_game_season(data: dict[str, Any]) -> int | None:
    seasons = [g.get("season") for g in data.get("games", []) if isinstance(g.get("season"), int)]
    return max(seasons) if seasons else None


def scheduled_season_from_raw(data: dict[str, Any]) -> int | None:
    raw = data.get("schedule") or data.get("scheduledGames") or []
    seasons = [g.get("season") for g in raw if isinstance(g, dict) and isinstance(g.get("season"), int)]
    return max(seasons) if seasons else None


def inferred_upcoming_schedule_season(data: dict[str, Any]) -> int:
    raw_season = scheduled_season_from_raw(data)
    if raw_season is not None:
        return raw_season
    season = current_season(data)
    # Basketball GM phase 8 is after re-signing/free agency. At that point the next useful
    # regular-season hub is usually the upcoming season rather than the completed season.
    if phase_value(data) >= 8:
        return season + 1
    return season


def game_slug_from_gid(gid: Any) -> str:
    return slugify(str(gid), "game")


def game_url(item: dict[str, Any], root: str = "") -> str:
    return f"{root}games/{game_slug_from_gid(item.get('gid'))}.html"


def is_completed_game_item(item: dict[str, Any]) -> bool:
    return bool(item.get("game")) and item.get("home_pts") is not None and item.get("away_pts") is not None


def normalize_game_item(game: dict[str, Any]) -> dict[str, Any] | None:
    teams_box = game.get("teams") or []
    if len(teams_box) < 2:
        return None
    # Basketball GM stores the home team first in game box-score objects.
    home_box = teams_box[0]
    away_box = teams_box[1]
    home_tid = home_box.get("tid")
    away_tid = away_box.get("tid")
    if home_tid is None or away_tid is None:
        return None
    return {
        "gid": game.get("gid"),
        "day": safe_int(game.get("day"), 0),
        "season": safe_int(game.get("season"), current_season({})),
        "home_tid": safe_int(home_tid),
        "away_tid": safe_int(away_tid),
        "home_pts": home_box.get("pts"),
        "away_pts": away_box.get("pts"),
        "home_box": home_box,
        "away_box": away_box,
        "game": game,
        "source": "game",
        "playoffs": bool(game.get("playoffs")),
    }


def completed_game_items(data: dict[str, Any], season: int | None = None, playoffs: bool | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for game in data.get("games", []):
        if season is not None and game.get("season") != season:
            continue
        item = normalize_game_item(game)
        if item is None:
            continue
        if playoffs is not None and bool(item.get("playoffs")) is not playoffs:
            continue
        items.append(item)
    items.sort(key=lambda item: (safe_int(item.get("day")), 1 if item.get("playoffs") else 0, str(item.get("gid"))))
    return items


def extract_tid_from_team_obj(obj: Any) -> int | None:
    if isinstance(obj, dict):
        for key in ["tid", "id", "teamId"]:
            if obj.get(key) is not None:
                return safe_int(obj.get(key))
    elif obj is not None:
        return safe_int(obj)
    return None


def normalize_schedule_entry(entry: dict[str, Any], index: int, default_season: int) -> dict[str, Any] | None:
    home_tid = None
    away_tid = None
    for home_key in ["homeTid", "home", "homeTeam", "homeTeamId"]:
        if entry.get(home_key) is not None:
            home_tid = extract_tid_from_team_obj(entry.get(home_key))
            break
    for away_key in ["awayTid", "away", "awayTeam", "awayTeamId"]:
        if entry.get(away_key) is not None:
            away_tid = extract_tid_from_team_obj(entry.get(away_key))
            break

    teams_list = entry.get("teams") or []
    if (home_tid is None or away_tid is None) and isinstance(teams_list, list) and len(teams_list) >= 2:
        home_candidates = [t for t in teams_list if isinstance(t, dict) and t.get("home") is True]
        away_candidates = [t for t in teams_list if isinstance(t, dict) and t.get("home") is False]
        if home_candidates and away_candidates:
            home_tid = extract_tid_from_team_obj(home_candidates[0])
            away_tid = extract_tid_from_team_obj(away_candidates[0])
        else:
            # Match Basketball GM box-score ordering: first team is home, second team is away.
            home_tid = extract_tid_from_team_obj(teams_list[0])
            away_tid = extract_tid_from_team_obj(teams_list[1])

    if home_tid is None or away_tid is None:
        return None

    home_pts = entry.get("homePts")
    away_pts = entry.get("awayPts")
    if home_pts is None or away_pts is None:
        # Some exports store scheduled games in the same shape as completed games.
        try:
            if isinstance(teams_list, list) and len(teams_list) >= 2:
                home_pts = teams_list[0].get("pts") if isinstance(teams_list[0], dict) else home_pts
                away_pts = teams_list[1].get("pts") if isinstance(teams_list[1], dict) else away_pts
        except Exception:
            pass

    return {
        "gid": entry.get("gid") or f"schedule-{default_season}-{index}",
        "day": safe_int(entry.get("day"), index + 1),
        "season": safe_int(entry.get("season"), default_season),
        "home_tid": home_tid,
        "away_tid": away_tid,
        "home_pts": home_pts,
        "away_pts": away_pts,
        "home_box": None,
        "away_box": None,
        "game": None,
        "source": "schedule",
        "playoffs": bool(entry.get("playoffs")),
    }


def raw_schedule_items(data: dict[str, Any], teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = data.get("schedule") or data.get("scheduledGames") or []
    if not isinstance(raw, list) or not raw:
        return []
    default_season = scheduled_season_from_raw(data) or inferred_upcoming_schedule_season(data)
    items: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        item = normalize_schedule_entry(entry, i, default_season)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: (safe_int(item.get("day")), str(item.get("gid"))))
    return items


def round_robin_rounds(team_ids: list[int]) -> list[list[tuple[int, int]]]:
    if not team_ids:
        return []
    ids: list[int | None] = list(team_ids)
    if len(ids) % 2:
        ids.append(None)
    n = len(ids)
    arr = ids[:]
    rounds: list[list[tuple[int, int]]] = []
    for _ in range(n - 1):
        pairs: list[tuple[int, int]] = []
        for i in range(n // 2):
            a = arr[i]
            b = arr[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((int(a), int(b)))
        rounds.append(pairs)
        arr = [arr[0], arr[-1], *arr[1:-1]]
    return rounds


def generated_schedule_items(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> list[dict[str, Any]]:
    team_ids = active_team_ids(teams)
    if len(team_ids) < 2:
        return []
    season = schedule_season if schedule_season is not None else inferred_upcoming_schedule_season(data)
    games_per_team = regular_season_length(data, season)
    if games_per_team <= 0:
        games_per_team = regular_season_length(data, current_season(data))
    if games_per_team <= 0:
        games_per_team = max(1, len(team_ids) - 1)
    series_count = max(1, round(games_per_team / max(1, len(team_ids) - 1)))
    rounds = round_robin_rounds(team_ids)
    if not rounds:
        return []

    items: list[dict[str, Any]] = []
    raw_day = 1
    total_game_days = len(rounds) * series_count
    if schedule_days is None and games_per_team == 45 and len(team_ids) == 10:
        schedule_days = 46
    off_days = max(0, safe_int(schedule_days, total_game_days) - total_game_days) if schedule_days else 0
    off_after = [math.ceil(total_game_days * (i + 1) / (off_days + 1)) for i in range(off_days)]

    gid_counter = 1
    for series_index in range(series_count):
        for round_index, pairs in enumerate(rounds):
            day = raw_day + sum(1 for cutoff in off_after if raw_day > cutoff)
            for pair_index, (a, b) in enumerate(pairs):
                if (round_index + series_index + pair_index) % 2 == 0:
                    home_tid, away_tid = b, a
                else:
                    home_tid, away_tid = a, b
                items.append({
                    "gid": f"generated-{season}-{gid_counter}",
                    "day": day,
                    "season": season,
                    "home_tid": home_tid,
                    "away_tid": away_tid,
                    "home_pts": None,
                    "away_pts": None,
                    "home_box": None,
                    "away_box": None,
                    "game": None,
                    "source": "generated",
                    "playoffs": False,
                })
                gid_counter += 1
            raw_day += 1
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    items.sort(key=lambda item: (safe_int(item.get("day")), team_abbrev_for_tid(item.get("home_tid"), teams_by_tid), team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)))
    return items


def schedule_items_for_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> tuple[list[dict[str, Any]], str]:
    raw_items = raw_schedule_items(data, teams)
    if schedule_season is not None and raw_items:
        raw_items = [item for item in raw_items if safe_int(item.get("season")) == schedule_season]
    if raw_items:
        season = max(safe_int(item.get("season")) for item in raw_items)
        return raw_items, f"Season {season} schedule"

    # When the caller explicitly asks for a past season, prefer the completed
    # regular-season game log over a synthetic schedule.
    if schedule_season is not None:
        completed_regular = completed_game_items(data, schedule_season, playoffs=False)
        if completed_regular:
            return completed_regular, f"Season {schedule_season} completed schedule"

    generated = generated_schedule_items(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    if generated:
        season = max(safe_int(item.get("season")) for item in generated)
        return generated, f"Generated Season {season} schedule"

    latest = latest_game_season(data)
    if latest is not None:
        return completed_game_items(data, latest, playoffs=False), f"Season {latest} completed schedule"
    return [], "Schedule"


def merge_schedule_and_completed(schedule_items: list[dict[str, Any]], completed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_by_gid = {str(item.get("gid")): item for item in completed_items if item.get("gid") is not None}
    completed_by_matchup = {
        (item.get("day"), item.get("home_tid"), item.get("away_tid")): item
        for item in completed_items
    }
    merged: list[dict[str, Any]] = []
    seen_completed_gids: set[str] = set()
    seen_matchups: set[tuple[Any, Any, Any]] = set()
    for item in schedule_items:
        replacement = None
        if item.get("gid") is not None:
            replacement = completed_by_gid.get(str(item.get("gid")))
        if replacement is None:
            replacement = completed_by_matchup.get((item.get("day"), item.get("home_tid"), item.get("away_tid")))
        chosen = replacement or item
        merged.append(chosen)
        seen_matchups.add((chosen.get("day"), chosen.get("home_tid"), chosen.get("away_tid")))
        if replacement is not None and replacement.get("gid") is not None:
            seen_completed_gids.add(str(replacement.get("gid")))
    for item in completed_items:
        gid = str(item.get("gid")) if item.get("gid") is not None else ""
        matchup = (item.get("day"), item.get("home_tid"), item.get("away_tid"))
        if gid and gid in seen_completed_gids:
            continue
        if matchup in seen_matchups:
            continue
        merged.append(item)
    merged.sort(key=lambda item: (safe_int(item.get("day")), 1 if item.get("playoffs") else 0, str(item.get("gid"))))
    return merged


def score_items_for_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> tuple[list[dict[str, Any]], str]:
    schedule_items, schedule_label = schedule_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    if schedule_items:
        season = max(safe_int(item.get("season")) for item in schedule_items)
        completed = completed_game_items(data, season, playoffs=False)
        return merge_schedule_and_completed(schedule_items, completed), schedule_label.replace("schedule", "scores")
    latest = latest_game_season(data)
    if latest is not None:
        return completed_game_items(data, latest, playoffs=False), f"Season {latest} scores"
    return [], "Scores"


def item_team_box(item: dict[str, Any], tid: int) -> dict[str, Any] | None:
    if item.get("home_tid") == tid:
        return item.get("home_box")
    if item.get("away_tid") == tid:
        return item.get("away_box")
    return None


def item_team_points(item: dict[str, Any], tid: int) -> Any:
    if item.get("home_tid") == tid:
        return item.get("home_pts")
    if item.get("away_tid") == tid:
        return item.get("away_pts")
    return None


def game_winner_tid(item: dict[str, Any]) -> int | None:
    try:
        home_pts = float(item.get("home_pts"))
        away_pts = float(item.get("away_pts"))
    except (TypeError, ValueError):
        return None
    if home_pts > away_pts:
        return int(item.get("home_tid"))
    if away_pts > home_pts:
        return int(item.get("away_tid"))
    return None


def game_ot_label(item: dict[str, Any]) -> str:
    game = item.get("game") or {}
    boxes = game.get("teams") or []
    periods = max((len(box.get("ptsQtrs") or []) for box in boxes), default=0)
    if periods <= 4:
        return ""
    extra = periods - 4
    return "OT" if extra == 1 else f"{extra}OT"


def team_schedule_result(item: dict[str, Any], tid: int) -> str:
    if not is_completed_game_item(item):
        return "Scheduled"
    team_pts = item_team_points(item, tid)
    opp_tid = item.get("away_tid") if item.get("home_tid") == tid else item.get("home_tid")
    opp_pts = item_team_points(item, opp_tid)
    if team_pts is None or opp_pts is None:
        return "Scheduled"
    result = "W" if safe_float(team_pts) > safe_float(opp_pts) else "L"
    return f"{result} {fmt_number(team_pts, 0)}-{fmt_number(opp_pts, 0)}"


def schedule_matchup_label(item: dict[str, Any], tid: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    home_tid = item.get("home_tid")
    away_tid = item.get("away_tid")
    if tid == home_tid:
        return f"vs. {esc(team_abbrev_for_tid(away_tid, teams_by_tid))}"
    if tid == away_tid:
        return f"@ {esc(team_abbrev_for_tid(home_tid, teams_by_tid))}"
    return "—"


def full_matchup_label(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str = "") -> str:
    away = team_label(item.get("away_tid"), teams_by_tid, root=root, as_link=True)
    home = team_label(item.get("home_tid"), teams_by_tid, root=root, as_link=True)
    return f"{away} <span class=\"muted\">@</span> {home}"


def compact_score_label(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    if not is_completed_game_item(item):
        return '<span class="muted">Scheduled</span>'
    away = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    away_pts = fmt_number(item.get("away_pts"), 0)
    home_pts = fmt_number(item.get("home_pts"), 0)
    winner = game_winner_tid(item)
    away_html = f'<strong>{esc(away)} {away_pts}</strong>' if winner == item.get("away_tid") else f'{esc(away)} {away_pts}'
    home_html = f'<strong>{esc(home)} {home_pts}</strong>' if winner == item.get("home_tid") else f'{esc(home)} {home_pts}'
    return f"{away_html} <span class=\"muted\">@</span> {home_html}"


def head_to_head_matrix(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    grid_teams = sorted(
        [team for team in teams if team.get("tid") is not None and not team.get("disabled")],
        key=lambda team: team_abbrev(team),
    )
    records: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for item in completed_game_items(data, season, playoffs=False):
        winner = game_winner_tid(item)
        if winner is None:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        loser = away if winner == home else home
        records[(winner, loser)][0] += 1
        records[(loser, winner)][1] += 1
    if not records:
        return ""

    header = "".join(
        f'<th data-tid="{esc(t.get("tid"))}">{team_dot(t.get("tid"), palette)}{esc(team_abbrev(t))}</th>'
        for t in grid_teams
    )
    rows = []
    for row_team in grid_teams:
        row_tid = safe_int(row_team.get("tid"))
        cells = [td(f'{team_dot(row_tid, palette)}{team_anchor(row_team)}', cls="name-cell")]
        for col_team in grid_teams:
            col_tid = safe_int(col_team.get("tid"))
            if row_tid == col_tid:
                cells.append(td("", cls="h2h-self"))
                continue
            won, lost = records.get((row_tid, col_tid), [0, 0])
            if won == 0 and lost == 0:
                cells.append(td('<span class="muted">—</span>'))
                continue
            frac = won / (won + lost)
            style = heat_style(frac, 0.0, 1.0, 1)
            cells.append(td(f"{won}-{lost}", sort=frac, style=style))
        rows.append(f'<tr data-tid="{row_tid}">{"".join(cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Head-to-Head</h2><span class="muted small-copy">Season {season} · read across: row team's record vs column team</span></div>
      <div class="table-wrap fit-table">
        <table id="h2h-grid" class="h2h-grid">
          <thead><tr><th>Team</th>{header}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """


def render_schedule_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    # Merge completed games into the schedule so the grid covers the whole season with results.
    items, label = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    label = label.replace("scores", "schedule")
    grid_teams = sorted(
        [team for team in teams if team.get("tid") is not None and not team.get("disabled")],
        key=lambda team: team_abbrev(team),
    )
    days = sorted({safe_int(item.get("day"), 0) for item in items})
    by_day_tid: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for tid in (item.get("home_tid"), item.get("away_tid")):
            if tid is not None:
                by_day_tid[(safe_int(item.get("day")), safe_int(tid))].append(item)

    palette = team_palette_by_tid(teams)
    next_day = min(
        (safe_int(item.get("day")) for item in items if not is_completed_game_item(item)),
        default=None,
    )
    header_cells = [th("Day")] + [
        f'<th data-tid="{esc(team.get("tid"))}">{team_dot(team.get("tid"), palette)}{esc(team_abbrev(team))}</th>'
        for team in grid_teams
    ]
    rows: list[str] = []
    for day in days:
        cells = [td(fmt_number(day, 0), cls="day-label")]
        for team in grid_teams:
            tid = int(team.get("tid"))
            cell_items = by_day_tid.get((day, tid), [])
            if not cell_items:
                cells.append(td("", cls="off-day"))
                continue
            parts = []
            for item in cell_items:
                matchup = schedule_matchup_label(item, tid, teams_by_tid)
                cls = "sched-cell"
                result_html = ""
                if is_completed_game_item(item):
                    result = team_schedule_result(item, tid)
                    cls += " sched-win" if result.startswith("W") else " sched-loss"
                    ot = game_ot_label(item)
                    if ot:
                        result = f"{result} {ot}"
                    result_html = f'<span class="sched-result">{esc(result)}</span>'
                parts.append(f'<a class="{cls}" href="{esc(game_url(item))}">{matchup}{result_html}</a>')
            cells.append(td("".join(parts)))
        row_cls = ' class="next-day"' if next_day is not None and day == next_day else ""
        rows.append(f"<tr{row_cls}>" + "".join(cells) + "</tr>")

    if rows:
        table = f"""
        <div class="table-wrap schedule-grid-wrap">
          <table id="schedule-grid" class="schedule-grid">
            <thead><tr>{''.join(header_cells)}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
    else:
        table = '<p class="empty-state">No schedule data was found in this export.</p>'

    season_for_h2h = max((safe_int(item.get("season")) for item in items), default=current_season(data))
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Schedule</h1>
        <p class="muted">{esc(label)} · <strong>vs.</strong> home · <strong>@</strong> road · the highlighted row is the next game day</p>
      </div>
    </section>
    <section class="card">
      {table}
    </section>
    {head_to_head_matrix(data, teams, season_for_h2h)}
    """
    return page_html("Schedule", body, teams, root="", active="schedule")


def fmt_minutes(value: Any) -> str:
    try:
        minutes_float = float(value or 0)
    except (TypeError, ValueError):
        return "0:00"
    if minutes_float <= 0:
        return "0:00"
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60))
    if seconds >= 60:
        minutes += 1
        seconds -= 60
    return f"{minutes}:{seconds:02d}"


def made_attempted(made: Any, attempted: Any) -> str:
    return f"{fmt_number(made or 0, 0)}-{fmt_number(attempted or 0, 0)}"


def game_score_value(player_box: dict[str, Any]) -> float:
    fg = safe_float(player_box.get("fg"))
    fga = safe_float(player_box.get("fga"))
    ft = safe_float(player_box.get("ft"))
    fta = safe_float(player_box.get("fta"))
    orb = safe_float(player_box.get("orb"))
    drb = safe_float(player_box.get("drb"))
    stl = safe_float(player_box.get("stl"))
    ast = safe_float(player_box.get("ast"))
    blk = safe_float(player_box.get("blk"))
    pf = safe_float(player_box.get("pf"))
    tov = safe_float(player_box.get("tov"))
    pts = safe_float(player_box.get("pts"))
    return pts + 0.4 * fg - 0.7 * fga - 0.4 * (fta - ft) + 0.7 * orb + 0.3 * drb + stl + 0.7 * ast + 0.7 * blk - 0.4 * pf - tov


def box_player_link(player_box: dict[str, Any], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    pid = player_box.get("pid")
    full = players_by_pid.get(int(pid)) if pid is not None and str(pid).lstrip("-").isdigit() else None
    number = player_box.get("jerseyNumber")
    number_html = f'<span class="muted number">{esc(number)}</span> ' if number not in (None, "") else ""
    skills = player_box.get("skills") or (latest_rating(full).get("skills") if full else []) or []
    skill_html = "".join(f'<span class="mini-skill">{esc(skill)}</span>' for skill in skills)
    name = player_box.get("name") or (player_name(full) if full else "Unknown")
    if full:
        return f'{number_html}<a class="player-link" href="{player_url(full, root)}">{esc(name)}</a> {skill_html}'
    return f'{number_html}<span class="player-link">{esc(name)}</span> {skill_html}'


def selected_box_players(team_box: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    players = team_box.get("players") or []
    starters = [p for p in players if safe_int(p.get("gs")) > 0]
    active_bench = [p for p in players if p not in starters and (safe_float(p.get("min")) > 0 or safe_int(p.get("gp")) > 0)]
    selected = starters[:5] + active_bench[:5]
    if len(selected) < 10:
        for p in players:
            if p not in selected:
                selected.append(p)
            if len(selected) >= 10:
                break
    bench_start_index = min(5, len(starters[:5]))
    return selected[:10], bench_start_index


def box_score_player_row(player_box: dict[str, Any], players_by_pid: dict[int, dict[str, Any]], root: str, cls: str = "") -> str:
    if player_box.get("_projected"):
        row = "".join([
            td(box_player_link(player_box, players_by_pid, root), sort=player_box.get("name"), cls="name-cell"),
            td(esc(player_box.get("pos", "—")), sort=player_box.get("pos", "")),
            *[td("—") for _ in range(15)],
        ])
        cls_attr = f' class="{cls}"' if cls else ""
        return f"<tr{cls_attr}>{row}</tr>"

    trb = safe_float(player_box.get("orb")) + safe_float(player_box.get("drb"))
    gmsc = game_score_value(player_box)
    row = "".join([
        td(box_player_link(player_box, players_by_pid, root), sort=player_box.get("name"), cls="name-cell"),
        td(esc(player_box.get("pos", "—")), sort=player_box.get("pos", "")),
        td(fmt_minutes(player_box.get("min")), sort=player_box.get("min")),
        td(made_attempted(player_box.get("fg"), player_box.get("fga")), sort=player_box.get("fg")),
        td(made_attempted(player_box.get("tp"), player_box.get("tpa")), sort=player_box.get("tp")),
        td(made_attempted(player_box.get("ft"), player_box.get("fta")), sort=player_box.get("ft")),
        td(fmt_number(player_box.get("orb") or 0, 0), sort=player_box.get("orb")),
        td(fmt_number(trb, 0), sort=trb),
        td(fmt_number(player_box.get("ast") or 0, 0), sort=player_box.get("ast")),
        td(fmt_number(player_box.get("tov") or 0, 0), sort=player_box.get("tov")),
        td(fmt_number(player_box.get("stl") or 0, 0), sort=player_box.get("stl")),
        td(fmt_number(player_box.get("blk") or 0, 0), sort=player_box.get("blk")),
        td(fmt_number(player_box.get("ba") or 0, 0), sort=player_box.get("ba")),
        td(fmt_number(player_box.get("pf") or 0, 0), sort=player_box.get("pf")),
        td(fmt_number(player_box.get("pts") or 0, 0), sort=player_box.get("pts")),
        td(fmt_signed(player_box.get("pm") or 0, 0), sort=player_box.get("pm"), cls=plus_minus_class(player_box.get("pm"))),
        td(fmt_number(gmsc, 1), sort=gmsc),
    ])
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<tr{cls_attr}>{row}</tr>"


def box_team_totals_row(team_box: dict[str, Any]) -> str:
    trb = safe_float(team_box.get("orb")) + safe_float(team_box.get("drb"))
    cells = [
        td("Total", sort="zzzz", cls="name-cell total-label"),
        td(""),
        td(fmt_number(team_box.get("min") or 240, 0), sort=team_box.get("min") or 240),
        td(made_attempted(team_box.get("fg"), team_box.get("fga")), sort=team_box.get("fg")),
        td(made_attempted(team_box.get("tp"), team_box.get("tpa")), sort=team_box.get("tp")),
        td(made_attempted(team_box.get("ft"), team_box.get("fta")), sort=team_box.get("ft")),
        td(fmt_number(team_box.get("orb") or 0, 0), sort=team_box.get("orb")),
        td(fmt_number(trb, 0), sort=trb),
        td(fmt_number(team_box.get("ast") or 0, 0), sort=team_box.get("ast")),
        td(fmt_number(team_box.get("tov") or 0, 0), sort=team_box.get("tov")),
        td(fmt_number(team_box.get("stl") or 0, 0), sort=team_box.get("stl")),
        td(fmt_number(team_box.get("blk") or 0, 0), sort=team_box.get("blk")),
        td(fmt_number(team_box.get("ba") or 0, 0), sort=team_box.get("ba")),
        td(fmt_number(team_box.get("pf") or 0, 0), sort=team_box.get("pf")),
        td(fmt_number(team_box.get("pts") or 0, 0), sort=team_box.get("pts")),
        td(""),
        td(""),
    ]
    return f"<tr class=\"total-row\">{''.join(cells)}</tr>"


def box_team_percentages_row(team_box: dict[str, Any]) -> str:
    cells = [td("Percentages", cls="name-cell total-label"), td(""), td("")]
    cells.append(td(fmt_pct(made_pct(team_box.get("fg"), team_box.get("fga")), 1), sort=made_pct(team_box.get("fg"), team_box.get("fga"))))
    cells.append(td(fmt_pct(made_pct(team_box.get("tp"), team_box.get("tpa")), 1), sort=made_pct(team_box.get("tp"), team_box.get("tpa"))))
    cells.append(td(fmt_pct(made_pct(team_box.get("ft"), team_box.get("fta")), 1), sort=made_pct(team_box.get("ft"), team_box.get("fta"))))
    cells.extend(td("") for _ in range(11))
    return f"<tr class=\"pct-row\">{''.join(cells)}</tr>"


def projected_team_box(tid: Any, players: list[dict[str, Any]], season: int) -> dict[str, Any]:
    tid_int = safe_int(tid)
    roster = [p for p in players if p.get("tid") == tid_int and p.get("retiredYear") is None]
    roster.sort(key=lambda p: (p.get("rosterOrder", 10**9), -safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
    selected = roster[:10]
    projected_players: list[dict[str, Any]] = []
    for i, player in enumerate(selected):
        rating = latest_rating(player, season)
        projected_players.append({
            "pid": player.get("pid"),
            "name": player_name(player),
            "pos": rating.get("pos", "—"),
            "jerseyNumber": player.get("jerseyNumber"),
            "skills": rating.get("skills") or [],
            "gs": 1 if i < 5 else 0,
            "_projected": True,
        })
    return {"tid": tid_int, "players": projected_players, "_projected": True}


def box_score_team_table(team_box: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    tid = safe_int(team_box.get("tid"))
    selected, bench_index = selected_box_players(team_box)
    rows: list[str] = []
    for i, player_box in enumerate(selected):
        cls = "bench-start" if i == bench_index and i > 0 else ""
        rows.append(box_score_player_row(player_box, players_by_pid, root, cls=cls))
    if not team_box.get("_projected"):
        rows.append(box_team_totals_row(team_box))
        rows.append(box_team_percentages_row(team_box))
    note = '<p class="muted small-copy">Projected active rotation. Stats will populate after the game is played.</p>' if team_box.get("_projected") else ""
    header_html = "".join(th(label) for label in ["Name", "Pos", "MP", "FG", "3P", "FT", "ORB", "TRB", "AST", "TOV", "STL", "BLK", "BA", "PF", "PTS", "+/-", "GmSc"])
    return f"""
    <section class="box-team-section">
      <h2>{team_label(tid, teams_by_tid, root=root)}</h2>
      {note}
      <div class="table-wrap box-table-wrap">
        <table data-sortable class="box-score-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """


def qtr_cells(points: list[Any], max_len: int) -> str:
    cells = []
    for i in range(max_len):
        value = points[i] if i < len(points) else ""
        cells.append(td(fmt_number(value, 0) if value != "" else "", sort=value if value != "" else None))
    return "".join(cells)


def team_factor_values(team_box: dict[str, Any], opp_box: dict[str, Any]) -> dict[str, float | None]:
    fga = safe_float(team_box.get("fga"))
    fta = safe_float(team_box.get("fta"))
    tov = safe_float(team_box.get("tov"))
    efg = (safe_float(team_box.get("fg")) + 0.5 * safe_float(team_box.get("tp"))) / fga if fga else None
    tov_pct = tov / (fga + 0.44 * fta + tov) if (fga + 0.44 * fta + tov) else None
    orb_pct = safe_float(team_box.get("orb")) / (safe_float(team_box.get("orb")) + safe_float(opp_box.get("drb"))) if (safe_float(team_box.get("orb")) + safe_float(opp_box.get("drb"))) else None
    ftr = fta / fga if fga else None
    return {"eFG%": efg, "TOV%": tov_pct, "ORB%": orb_pct, "FT/FGA": ftr}


def game_series_note(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    game = item.get("game") or {}
    if not game.get("playoffs"):
        return ""
    target = safe_int(game.get("numGamesToWinSeries"), 0)
    notes = []
    for box in game.get("teams") or []:
        playoffs = box.get("playoffs") or {}
        won = safe_int(playoffs.get("won"), 0)
        lost = safe_int(playoffs.get("lost"), 0)
        if target and won >= target:
            notes.append(f"{team_abbrev_for_tid(box.get('tid'), teams_by_tid)} won series {won}-{lost}")
    if notes:
        return f'<p class="series-note">{esc(" · ".join(notes))}</p>'
    return ""


def scheduled_game_header(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], prev_item: dict[str, Any] | None, next_item: dict[str, Any] | None) -> str:
    home_tid = item.get("home_tid")
    away_tid = item.get("away_tid")
    prev_link = f'<a class="button-link" href="{esc(game_url(prev_item, root="../"))}">Prev</a>' if prev_item else '<span class="button-link disabled">Prev</span>'
    next_link = f'<a class="button-link" href="{esc(game_url(next_item, root="../"))}">Next</a>' if next_item else '<span class="button-link disabled">Next</span>'
    return f"""
    <section class="box-score-hero card">
      <div class="game-pager">{prev_link}</div>
      <div class="scoreboard-core">
        <p class="eyebrow">Day {fmt_number(item.get('day'), 0)} · Season {fmt_number(item.get('season'), 0)}</p>
        <h1>{team_label(away_tid, teams_by_tid, root='../')} <em>@</em> {team_label(home_tid, teams_by_tid, root='../')}</h1>
        <p class="scheduled-note">Scheduled game · box score will populate when the JSON includes this game result.</p>
      </div>
      <div class="game-pager">{next_link}</div>
    </section>
    """


def player_of_the_game_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    best = None
    for box_key in ("home_box", "away_box"):
        box = item.get(box_key) or {}
        for player_box in box.get("players") or []:
            if safe_float(player_box.get("min")) <= 0:
                continue
            gmsc = game_score_value(player_box)
            if best is None or gmsc > best[0]:
                best = (gmsc, player_box, box.get("tid"))
    if best is None:
        return ""
    gmsc, player_box, tid = best
    full = ALL_PLAYERS_BY_PID.get(safe_int(player_box.get("pid"), -10))
    name = player_box.get("name") or (player_name(full) if full else "—")
    if full is not None and full.get("retiredYear") is None and safe_int(full.get("tid"), RETIRED_TID) >= FREE_AGENT_TID:
        name_html = f'<a href="{player_url(full, root)}">{esc(name)}</a>'
    else:
        name_html = esc(name)
    trb = safe_float(player_box.get("orb")) + safe_float(player_box.get("drb"))
    line = f"{fmt_number(player_box.get('pts'), 0)} PTS · {fmt_number(trb, 0)} TRB · {fmt_number(player_box.get('ast'), 0)} AST"
    return (
        f'<p class="potg"><span class="badge badge-accent">POTG</span>{name_html} '
        f'<span class="muted">({esc(team_abbrev_for_tid(tid, teams_by_tid))}) · {line} · GmSc {fmt_number(gmsc, 1)}</span></p>'
    )


def clutch_plays_html(item: dict[str, Any], root: str) -> str:
    plays = (item.get("game") or {}).get("clutchPlays") or []
    if not plays:
        return ""
    rendered = []
    for play in plays:
        def repl(match):
            pid = match.group(1)
            label = re.sub(r"<[^>]+>", "", match.group(2))
            return event_player_link(pid, ALL_PLAYERS_BY_PID, root, label=label)
        text = re.sub(r'<a href="[^"]*?/player/(\d+)[^"]*">(.*?)</a>', repl, play)
        text = re.sub(r'<a href="[^"]*">(.*?)</a>', lambda m: esc(re.sub(r"<[^>]+>", "", m.group(1))), text)
        rendered.append(f'<li><span class="badge badge-accent">CLUTCH</span><span>{text}</span></li>')
    return f"""
    <section class="card compact-card">
      <ul class="news-list">{''.join(rendered)}</ul>
    </section>
    """


def box_score_header(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], prev_item: dict[str, Any] | None, next_item: dict[str, Any] | None) -> str:
    if not is_completed_game_item(item):
        return scheduled_game_header(item, teams_by_tid, prev_item, next_item)

    home_box = item.get("home_box") or {}
    away_box = item.get("away_box") or {}
    home_tid = item.get("home_tid")
    away_tid = item.get("away_tid")
    home_abbrev = team_abbrev_for_tid(home_tid, teams_by_tid)
    away_abbrev = team_abbrev_for_tid(away_tid, teams_by_tid)
    max_len = max(len(home_box.get("ptsQtrs") or []), len(away_box.get("ptsQtrs") or []), 4)
    period_labels = [str(i + 1) for i in range(min(4, max_len))]
    if max_len > 4:
        period_labels.extend("OT" if i == 4 else f"{i - 3}OT" for i in range(4, max_len))
    period_labels = period_labels[:max_len]
    score_headers = "".join(th(label) for label in ["", *period_labels, "F"])
    away_row = f"<tr>{td(away_abbrev, cls='score-team')}{qtr_cells(away_box.get('ptsQtrs') or [], max_len)}{td(fmt_number(item.get('away_pts'), 0), sort=item.get('away_pts'), cls='final-score')}</tr>"
    home_row = f"<tr>{td(home_abbrev, cls='score-team')}{qtr_cells(home_box.get('ptsQtrs') or [], max_len)}{td(fmt_number(item.get('home_pts'), 0), sort=item.get('home_pts'), cls='final-score')}</tr>"

    home_factors = team_factor_values(home_box, away_box)
    away_factors = team_factor_values(away_box, home_box)
    factor_headers = "".join(th(label) for label in ["", "eFG%", "TOV%", "ORB%", "FT/FGA"])
    away_factor_row = f"<tr>{td(away_abbrev, cls='score-team')}{td(fmt_pct((away_factors['eFG%'] or 0) * 100 if away_factors['eFG%'] is not None else None, 1))}{td(fmt_pct((away_factors['TOV%'] or 0) * 100 if away_factors['TOV%'] is not None else None, 1))}{td(fmt_pct((away_factors['ORB%'] or 0) * 100 if away_factors['ORB%'] is not None else None, 1))}{td(fmt_ratio(away_factors['FT/FGA'], 3))}</tr>"
    home_factor_row = f"<tr>{td(home_abbrev, cls='score-team')}{td(fmt_pct((home_factors['eFG%'] or 0) * 100 if home_factors['eFG%'] is not None else None, 1))}{td(fmt_pct((home_factors['TOV%'] or 0) * 100 if home_factors['TOV%'] is not None else None, 1))}{td(fmt_pct((home_factors['ORB%'] or 0) * 100 if home_factors['ORB%'] is not None else None, 1))}{td(fmt_ratio(home_factors['FT/FGA'], 3))}</tr>"
    prev_link = f'<a class="button-link" href="{esc(game_url(prev_item, root="../"))}">Prev</a>' if prev_item else '<span class="button-link disabled">Prev</span>'
    next_link = f'<a class="button-link" href="{esc(game_url(next_item, root="../"))}">Next</a>' if next_item else '<span class="button-link disabled">Next</span>'
    return f"""
    <section class="box-score-hero card">
      <div class="game-pager">{prev_link}</div>
      <div class="scoreboard-core">
        <p class="eyebrow">Day {fmt_number(item.get('day'), 0)} · Season {fmt_number(item.get('season'), 0)}</p>
        <h1>{team_label(home_tid, teams_by_tid, root='../')} <span>{fmt_number(item.get('home_pts'), 0)}</span> <em>vs.</em> {team_label(away_tid, teams_by_tid, root='../')} <span>{fmt_number(item.get('away_pts'), 0)}</span></h1>
        <div class="scoreboard-grid">
          <div class="mini-score-table table-wrap"><table><thead><tr>{score_headers}</tr></thead><tbody>{away_row}{home_row}</tbody></table></div>
          <div class="mini-score-table table-wrap"><table><thead><tr>{factor_headers}</tr></thead><tbody>{away_factor_row}{home_factor_row}</tbody></table></div>
        </div>
        {player_of_the_game_html(item, teams_by_tid, '../')}
        {game_series_note(item, teams_by_tid)}
      </div>
      <div class="game-pager">{next_link}</div>
    </section>
    """


def season_series_html(item: dict[str, Any], all_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    pair = {safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))}
    meetings = [
        other for other in all_items
        if {safe_int(other.get("home_tid")), safe_int(other.get("away_tid"))} == pair
    ]
    meetings.sort(key=lambda other: (safe_int(other.get("day")), str(other.get("gid"))))
    completed = [m for m in meetings if is_completed_game_item(m)]
    if len(meetings) < 2:
        return ""
    tid_a, tid_b = sorted(pair)
    wins = {tid_a: 0, tid_b: 0}
    for m in completed:
        winner = game_winner_tid(m)
        if winner in wins:
            wins[winner] += 1
    if wins[tid_a] == wins[tid_b]:
        series_text = f"Series tied {wins[tid_a]}-{wins[tid_b]}" if completed else "First meeting of the season"
    else:
        lead_tid = tid_a if wins[tid_a] > wins[tid_b] else tid_b
        trail = min(wins.values())
        series_text = f"{team_abbrev_for_tid(lead_tid, teams_by_tid)} lead{'s' if True else ''} the series {max(wins.values())}-{trail}"
    chips = []
    for m in meetings:
        current = str(m.get("gid")) == str(item.get("gid"))
        if is_completed_game_item(m):
            winner = game_winner_tid(m)
            away = team_abbrev_for_tid(m.get("away_tid"), teams_by_tid)
            home = team_abbrev_for_tid(m.get("home_tid"), teams_by_tid)
            away_html = f"{esc(away)} {fmt_number(m.get('away_pts'), 0)}"
            home_html = f"{esc(home)} {fmt_number(m.get('home_pts'), 0)}"
            if winner == m.get("away_tid"):
                away_html = f"<strong>{away_html}</strong>"
            elif winner == m.get("home_tid"):
                home_html = f"<strong>{home_html}</strong>"
            label = f"Day {safe_int(m.get('day'))}: {away_html} @ {home_html}"
        else:
            label = (
                f"Day {safe_int(m.get('day'))}: "
                f"{esc(team_abbrev_for_tid(m.get('away_tid'), teams_by_tid))} @ "
                f"{esc(team_abbrev_for_tid(m.get('home_tid'), teams_by_tid))}"
            )
        cls = "series-chip current" if current else "series-chip"
        chips.append(f'<a class="{cls}" href="{esc(game_url(m, root))}">{label}</a>')
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Season Series</h2><span class="muted small-copy">{esc(series_text)}</span></div>
      <div class="series-row">{''.join(chips)}</div>
    </section>
    """


def preview_team_metrics(team: dict[str, Any], season: int) -> dict[str, Any]:
    team_season = latest_team_season(team, season)
    stat = latest_team_stat(team, season)
    fga = safe_float(stat.get("fga"))
    fta = safe_float(stat.get("fta"))
    tov = safe_float(stat.get("tov"))
    efg = 100 * (safe_float(stat.get("fg")) + 0.5 * safe_float(stat.get("tp"))) / fga if fga else None
    tovp = 100 * tov / (fga + 0.44 * fta + tov) if (fga + 0.44 * fta + tov) else None
    ftr = safe_float(stat.get("ft")) / fga if fga else None
    return {
        "record": fmt_record(team_season.get("won"), team_season.get("lost")),
        "streak": streak_text(team_season.get("streak")),
        "l10": last_ten_text(team_season.get("lastTen")),
        "ppg": team_stat_per_game(stat, "pts"),
        "papg": team_stat_per_game(stat, "oppPts"),
        "mov": team_mov(stat),
        "efg": efg,
        "tovp": tovp,
        "ftr": ftr,
    }


def game_preview_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], players: list[dict[str, Any]], season: int, root: str) -> str:
    away_team = teams_by_tid.get(safe_int(item.get("away_tid")))
    home_team = teams_by_tid.get(safe_int(item.get("home_tid")))
    if not away_team or not home_team:
        return ""
    away = preview_team_metrics(away_team, season)
    home = preview_team_metrics(home_team, season)
    rows_spec = [
        ("Record", "record", None),
        ("Streak", "streak", None),
        ("Last 10", "l10", None),
        ("Points/G", "ppg", 1),
        ("Allowed/G", "papg", 1),
        ("MOV", "mov", "signed"),
        ("eFG%", "efg", 1),
        ("TOV%", "tovp", 1),
        ("FT/FGA", "ftr", "ratio"),
    ]
    rows = []
    for label, key, fmt in rows_spec:
        def render(value):
            if fmt is None:
                return esc(value)
            if fmt == "signed":
                return fmt_signed(value, 1)
            if fmt == "ratio":
                return fmt_ratio(value, 3)
            return fmt_number(value, fmt)
        rows.append(
            f"<tr><td>{render(away.get(key))}</td>"
            f'<td class="cmp-label">{esc(label)}</td>'
            f"<td>{render(home.get(key))}</td></tr>"
        )
    injuries = []
    for team, side in ((away_team, "away"), (home_team, "home")):
        tid = safe_int(team.get("tid"))
        hurt = [
            p for p in players
            if safe_int(p.get("tid"), -9) == tid and (p.get("injury") or {}).get("type") not in (None, "", "Healthy")
        ]
        if hurt:
            bits = []
            for p in sorted(hurt, key=lambda p: -safe_int((p.get("injury") or {}).get("gamesRemaining"))):
                injury = p.get("injury") or {}
                bits.append(
                    f'<a class="player-link" href="{player_url(p, root)}">{esc(player_name(p))}</a> '
                    f'<span class="injured">({esc(injury.get("type"))}, {safe_int(injury.get("gamesRemaining"))} games)</span>'
                )
            injuries.append(f'<p class="small-copy"><strong>{esc(team_abbrev(team))}:</strong> {" · ".join(bits)}</p>')
        else:
            injuries.append(f'<p class="small-copy"><strong>{esc(team_abbrev(team))}:</strong> <span class="healthy">no injuries</span></p>')
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Matchup</h2><span class="muted small-copy">season-to-date</span></div>
      <div class="table-wrap fit-table">
        <table class="cmp-table">
          <thead><tr><th>{team_label(item.get("away_tid"), teams_by_tid, root)}</th><th></th><th>{team_label(item.get("home_tid"), teams_by_tid, root)}</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <div class="preview-injuries">
        <h3 class="small-copy muted">INJURY REPORT</h3>
        {''.join(injuries)}
      </div>
    </section>
    """


def render_game_page(item: dict[str, Any], all_items: list[dict[str, Any]], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    players_by_pid = {int(player.get("pid")): player for player in players if player.get("pid") is not None}
    ordered_items = sorted(all_items, key=lambda it: (safe_int(it.get("day")), str(it.get("gid"))))
    index = ordered_items.index(item) if item in ordered_items else -1
    prev_item = ordered_items[index - 1] if index > 0 else None
    next_item = ordered_items[index + 1] if 0 <= index < len(ordered_items) - 1 else None
    home_box = item.get("home_box") or projected_team_box(item.get("home_tid"), players, season)
    away_box = item.get("away_box") or projected_team_box(item.get("away_tid"), players, season)
    preview = "" if is_completed_game_item(item) else game_preview_html(item, teams_by_tid, players, season, "../")
    series = season_series_html(item, all_items, teams_by_tid, "../")
    clutch = clutch_plays_html(item, "../")
    body = f"""
    {box_score_header(item, teams_by_tid, prev_item, next_item)}
    {clutch}
    {preview}
    {box_score_team_table(away_box, teams_by_tid, players_by_pid, root='../')}
    {box_score_team_table(home_box, teams_by_tid, players_by_pid, root='../')}
    {series}
    """
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    title = f"{away_abbrev} at {home_abbrev} Box Score"
    return page_html(title, body, teams, root="../", active="schedule")



def latest_results_strip(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    completed = completed_game_items(data, season, playoffs=None)
    if not completed:
        return ""
    last_day = max(safe_int(item.get("day")) for item in completed)
    day_items = [item for item in completed if safe_int(item.get("day")) == last_day]
    lines = []
    for item in day_items:
        winner = game_winner_tid(item)
        away = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
        home = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
        away_html = f"{esc(away)} {fmt_number(item.get('away_pts'), 0)}"
        home_html = f"{esc(home)} {fmt_number(item.get('home_pts'), 0)}"
        if winner == item.get("away_tid"):
            away_html = f"<strong>{away_html}</strong>"
        elif winner == item.get("home_tid"):
            home_html = f"<strong>{home_html}</strong>"
        ot = game_ot_label(item)
        ot_html = f' <span class="score-status">{esc(ot)}</span>' if ot else ""
        lines.append(
            f'<a class="score-line" href="{esc(game_url(item))}">'
            f'<span class="score-match">{away_html} <em>@</em> {home_html}{ot_html}</span>'
            f'<span class="score-status final">Final</span></a>'
        )
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Latest Results · Day {last_day}</h2><a class="muted small-copy" href="schedule.html">Full schedule →</a></div>
      <div class="score-list">{''.join(lines)}</div>
    </section>
    """


EVENT_BADGES = {
    "injured": ("INJ", "badge-bad"),
    "healed": ("FIT", "badge-good"),
    "playerFeat": ("FEAT", "badge-accent"),
    "award": ("AWARD", "badge-accent"),
    "freeAgent": ("SIGN", "badge-good"),
    "reSigned": ("RE-SIGN", "badge-good"),
    "release": ("WAIVE", "badge-bad"),
    "trade": ("TRADE", "badge-accent"),
    "hallOfFame": ("HOF", "badge-accent"),
    "retired": ("RETIRE", "badge-muted"),
    "playoffs": ("RACE", "badge-muted"),
    "madePlayoffs": ("CLINCH", "badge-good"),
}


def event_player_link(pid: Any, all_players_by_pid: dict[int, dict[str, Any]], root: str, label: str | None = None) -> str:
    player = all_players_by_pid.get(safe_int(pid, -10))
    if not player:
        return esc(label or f"Player {pid}")
    text = esc(label or player_name(player))
    # Pages exist only for active (non-retired, rostered or FA) players.
    if player.get("retiredYear") is None and safe_int(player.get("tid"), RETIRED_TID) >= FREE_AGENT_TID:
        return f'<a href="{player_url(player, root)}">{text}</a>'
    return text


def rewrite_event_text(text: str, all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int, current_gids: set[str], root: str) -> str:
    def repl(match: re.Match) -> str:
        href, label = match.group(1), match.group(2)
        player_match = re.search(r"/player/(\d+)", href)
        if player_match:
            return event_player_link(player_match.group(1), all_players_by_pid, root, label=re.sub(r"<[^>]+>", "", label))
        roster_match = re.search(r"/roster/[A-Za-z]+_(\d+)", href)
        if roster_match:
            team = teams_by_tid.get(safe_int(roster_match.group(1)))
            if team:
                return f'<a href="{team_url(team, root)}">{esc(re.sub(r"<[^>]+>", "", label))}</a>'
        game_match = re.search(r"/game_log/[^/]+/(\d+)/(\d+)", href)
        if game_match and safe_int(game_match.group(1)) == season and game_match.group(2) in current_gids:
            return f'<a href="{root}games/{game_match.group(2)}.html">{esc(re.sub(r"<[^>]+>", "", label))}</a>'
        return esc(re.sub(r"<[^>]+>", "", label))
    return re.sub(r'<a href="([^"]*)">(.*?)</a>', repl, text)


def compose_event_html(event: dict[str, Any], all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int, current_gids: set[str], root: str) -> str:
    etype = event.get("type")
    pids = event.get("pids") or []
    tids = event.get("tids") or []

    def team_link(tid: Any) -> str:
        team = teams_by_tid.get(safe_int(tid, -10))
        if not team:
            return "FA"
        return f'<a href="{team_url(team, root)}">{esc(team_abbrev(team))}</a>'

    if etype == "trade":
        sides = event.get("teams") or []
        if len(sides) >= 2 and len(tids) >= 2:
            parts = []
            for tid, side in zip(tids[:2], sides[:2]):
                got = []
                for asset in side.get("assets") or []:
                    if asset.get("pid") is not None:
                        got.append(event_player_link(asset.get("pid"), all_players_by_pid, root, label=asset.get("name")))
                    elif asset.get("round") is not None:
                        origin = team_abbrev(teams_by_tid.get(safe_int(asset.get("originalTid"), -10)))
                        rnd = "1st" if safe_int(asset.get("round")) == 1 else "2nd"
                        got.append(f"{esc(asset.get('season'))} {rnd} ({esc(origin)})")
                parts.append(f"{team_link(tid)} receive {', '.join(got) or 'nothing'}")
            return "; ".join(parts) + "."
        if len(tids) >= 2:
            return f"{team_link(tids[0])} and {team_link(tids[1])} completed a trade."
        return "Trade completed."
    if etype in ("freeAgent", "reSigned") and pids:
        contract = event.get("contract") or {}
        deal = fmt_money(contract.get("amount"))
        if contract.get("exp") is not None:
            deal += f"/{esc(contract.get('exp'))}"
        verb = "re-signed with" if etype == "reSigned" else "signed with"
        return f"{event_player_link(pids[0], all_players_by_pid, root)} {verb} {team_link(tids[0]) if tids else 'a team'} for {deal}."
    text = event.get("text") or ""
    if text:
        return rewrite_event_text(text, all_players_by_pid, teams_by_tid, season, current_gids, root)
    return ""


def news_feed_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "", limit: int = 25) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    current_gids = {str(g.get("gid")) for g in data.get("games", []) if g.get("season") == season}
    wanted = set(EVENT_BADGES)
    events = [e for e in data.get("events", []) if e.get("season") == season and e.get("type") in wanted]
    events.sort(key=lambda e: -safe_int(e.get("eid")))
    items = []
    for event in events:
        if len(items) >= limit:
            break
        html_text = compose_event_html(event, all_players_by_pid, teams_by_tid, season, current_gids, root)
        if not html_text:
            continue
        label, badge_cls = EVENT_BADGES.get(event.get("type"), ("NEWS", "badge-muted"))
        items.append(f'<li><span class="badge {badge_cls}">{esc(label)}</span><span>{html_text}</span></li>')
    if not items:
        return ""
    return f"""
    <section class="card home-section news-card">
      <div class="section-title-row"><h2>League News</h2><span class="count-pill">latest {len(items)}</span></div>
      <ul class="news-list">{''.join(items)}</ul>
    </section>
    """


def injury_report_card(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    injured = []
    for player in players:
        injury = player.get("injury") or {}
        if injury.get("type") and injury.get("type") != "Healthy" and safe_int(player.get("tid"), -9) >= 0:
            injured.append((player, injury))
    injured.sort(key=lambda pair: (-safe_int(pair[1].get("gamesRemaining")), player_name(pair[0])))
    rows = []
    for player, injury in injured:
        rating = latest_rating(player, season)
        rows.append("".join([
            td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
            td(team_label(player.get("tid"), teams_by_tid, root), sort=team_label(player.get("tid"), teams_by_tid, as_link=False)),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
            td(esc(injury.get("type", "—")), sort=injury.get("type", "")),
            td(fmt_number(injury.get("gamesRemaining"), 0), sort=injury.get("gamesRemaining")),
        ]))
    if not rows:
        return ""
    headers = ["Player", "Team", "Pos", "Ovr", "Injury", "Games left"]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Injury Report</h2><span class="count-pill">{len(rows)} out</span></div>
      {table_html(headers, rows, table_id="injury-report", empty_message="Everyone is healthy.")}
    </section>
    """


def league_leaders_card(data: dict[str, Any], players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    max_team_gp = max((safe_float(latest_team_stat(t, season).get("gp")) for t in teams), default=0.0)
    min_gp = max(1.0, 0.7 * max_team_gp)
    qualified = []
    for player in players:
        if safe_int(player.get("tid"), -9) < 0:
            continue
        stat = season_regular_stat(player, season)
        if stat_gp(stat) >= min_gp:
            qualified.append((player, stat))
    if not qualified:
        return ""

    def leaders(value_fn, fmt_digits=1):
        scored = []
        for player, stat in qualified:
            value = value_fn(stat)
            if value is None:
                continue
            scored.append((float(value), player, stat))
        scored.sort(key=lambda x: (-x[0], player_name(x[1])))
        rows = []
        for rank, (value, player, stat) in enumerate(scored[:5], 1):
            rows.append(
                f'<li><span class="leader-rank">{rank}</span>'
                f'{team_dot(player.get("tid"), palette)}'
                f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
                f'<span class="leader-team">{esc(team_abbrev_for_tid(player.get("tid"), teams_by_tid))}</span>'
                f'<span class="leader-value">{fmt_number(value, fmt_digits)}</span></li>'
            )
        return "".join(rows)

    categories = [
        ("Points", lambda s: per_game(s, "pts")),
        ("Rebounds", lambda s: total_rebounds(s) / stat_gp(s) if stat_gp(s) else None),
        ("Assists", lambda s: per_game(s, "ast")),
        ("Steals", lambda s: per_game(s, "stl")),
        ("Blocks", lambda s: per_game(s, "blk")),
        ("PER", lambda s: s.get("per")),
        ("BPM", lambda s: safe_float(s.get("obpm")) + safe_float(s.get("dbpm"))),
        ("Win Shares", lambda s: safe_float(s.get("ows")) + safe_float(s.get("dws"))),
    ]
    boxes = []
    for title, fn in categories:
        body = leaders(fn)
        if body:
            boxes.append(f'<div class="leader-box"><h3>{esc(title)}</h3><ol class="leader-list">{body}</ol></div>')
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>League Leaders</h2><span class="muted small-copy">min {fmt_number(min_gp, 0)} games played</span></div>
      <div class="leader-grid">{''.join(boxes)}</div>
    </section>
    """


def rookie_watch_card(data: dict[str, Any], players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    rookies = []
    for player in players:
        if safe_int(player.get("tid"), -9) < 0:
            continue
        if (player.get("draft") or {}).get("year") not in (season - 1, season):
            continue
        stat = season_regular_stat(player, season)
        gp = stat_gp(stat)
        if gp <= 0:
            continue
        pts = per_game(stat, "pts") or 0.0
        trb = total_rebounds(stat) / gp
        ast = per_game(stat, "ast") or 0.0
        score = pts + 1.2 * trb + 1.5 * ast
        rookies.append((score, player, stat, pts, trb, ast))
    if not rookies:
        return ""
    rookies.sort(key=lambda x: (-x[0], player_name(x[1])))
    rows = []
    for rank, (score, player, stat, pts, trb, ast) in enumerate(rookies[:5], 1):
        rows.append(
            f'<li><span class="leader-rank">{rank}</span>'
            f'{team_dot(player.get("tid"), palette)}'
            f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
            f'<span class="leader-team">{esc(team_abbrev_for_tid(player.get("tid"), teams_by_tid))}</span>'
            f'<span class="leader-value">{fmt_number(pts, 1)} / {fmt_number(trb, 1)} / {fmt_number(ast, 1)}</span></li>'
        )
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Rookie Watch</h2><span class="muted small-copy">PTS / TRB / AST</span></div>
      <ol class="leader-list rookie-list">{''.join(rows)}</ol>
    </section>
    """


def four_factors_table(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    acc: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games_count: dict[int, int] = defaultdict(int)
    keys = ["fg", "fga", "tp", "ft", "fta", "tov", "orb", "drb", "pts"]
    for item in completed_game_items(data, season, playoffs=False):
        for own_key, opp_key in (("home_box", "away_box"), ("away_box", "home_box")):
            own = item.get(own_key) or {}
            opp = item.get(opp_key) or {}
            tid = safe_int(own.get("tid"), -1)
            if tid not in teams_by_tid:
                continue
            games_count[tid] += 1
            for key in keys:
                acc[tid][key] += safe_float(own.get(key))
                acc[tid]["opp_" + key] += safe_float(opp.get(key))
    if not acc:
        return ""

    def factors(t: dict[str, float], prefix: str = "") -> dict[str, float | None]:
        fg, fga = t[prefix + "fg"], t[prefix + "fga"]
        tp, ft, fta = t[prefix + "tp"], t[prefix + "ft"], t[prefix + "fta"]
        tov, orb = t[prefix + "tov"], t[prefix + "orb"]
        opp_drb = t[("" if prefix else "opp_") + "drb"]
        efg = 100 * (fg + 0.5 * tp) / fga if fga else None
        tovp = 100 * tov / (fga + 0.44 * fta + tov) if (fga + 0.44 * fta + tov) else None
        orbp = 100 * orb / (orb + opp_drb) if (orb + opp_drb) else None
        ftr = ft / fga if fga else None
        return {"efg": efg, "tov": tovp, "orb": orbp, "ftr": ftr}

    infos = []
    for tid, totals in acc.items():
        gp = games_count[tid]
        poss = totals["fga"] + 0.44 * totals["fta"] - totals["orb"] + totals["tov"]
        opp_poss = totals["opp_fga"] + 0.44 * totals["opp_fta"] - totals["opp_orb"] + totals["opp_tov"]
        avg_poss = (poss + opp_poss) / 2
        pace = avg_poss / gp if gp else None
        ortg = 100 * totals["pts"] / avg_poss if avg_poss else None
        drtg = 100 * totals["opp_pts"] / avg_poss if avg_poss else None
        off = factors(totals)
        defense = factors(totals, "opp_")
        infos.append({
            "tid": tid, "pace": pace, "ortg": ortg, "drtg": drtg,
            "net": (ortg - drtg) if ortg is not None and drtg is not None else None,
            "off": off, "def": defense,
        })
    infos.sort(key=lambda info: -(info["net"] if info["net"] is not None else -999))

    columns = [
        ("Pace", lambda i: i["pace"], "num", 0),
        ("ORtg", lambda i: i["ortg"], "num", 1),
        ("DRtg", lambda i: i["drtg"], "num", -1),
        ("Net", lambda i: i["net"], "signed", 1),
        ("eFG%", lambda i: i["off"]["efg"], "num", 1),
        ("TOV%", lambda i: i["off"]["tov"], "num", -1),
        ("ORB%", lambda i: i["off"]["orb"], "num", 1),
        ("FT/FGA", lambda i: i["off"]["ftr"], "ratio", 1),
        ("eFG%", lambda i: i["def"]["efg"], "num", -1),
        ("TOV%", lambda i: i["def"]["tov"], "num", 1),
        ("ORB%", lambda i: i["def"]["orb"], "num", -1),
        ("FT/FGA", lambda i: i["def"]["ftr"], "ratio", -1),
    ]
    col_values = []
    for _, getter, _, _ in columns:
        values = [float(getter(i)) for i in infos if getter(i) is not None and math.isfinite(safe_float(getter(i), float("nan")))]
        col_values.append(values)

    def fmt_cell(value, fmt):
        if value is None:
            return "—"
        if fmt == "ratio":
            return fmt_ratio(value, 3)
        if fmt == "signed":
            return fmt_signed(value, 1)
        return fmt_number(value, 1)

    rows = []
    for rank, info in enumerate(infos, 1):
        team = teams_by_tid.get(info["tid"], {})
        cells = [
            td(rank, sort=rank),
            td(f'{team_dot(info["tid"], palette)}{team_anchor(team)}', sort=team_full_name(team), cls="name-cell"),
        ]
        for (label, getter, fmt, direction), values in zip(columns, col_values):
            value = getter(info)
            lo = min(values) if values else 0.0
            hi = max(values) if values else 0.0
            cells.append(td(fmt_cell(value, fmt), sort=value, style=heat_style(value, lo, hi, direction)))
        rows.append(f'<tr data-tid="{esc(info["tid"])}">{"".join(cells)}</tr>')

    header_html = (
        '<tr><th rowspan="2">#</th><th rowspan="2">Team</th>'
        '<th rowspan="2">Pace</th><th rowspan="2">ORtg</th><th rowspan="2">DRtg</th><th rowspan="2">Net</th>'
        '<th colspan="4" class="group-head">Offense</th><th colspan="4" class="group-head">Defense</th></tr>'
        "<tr>" + "".join(th(label) for label in ["eFG%", "TOV%", "ORB%", "FT/FGA", "eFG%", "TOV%", "ORB%", "FT/FGA"]) + "</tr>"
    )
    body_html = "".join(rows)
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Four Factors</h2><span class="muted small-copy">Per-possession profile · defense = what opponents do against you</span></div>
      <div class="table-wrap">
        <table id="four-factors">
          <thead>{header_html}</thead>
          <tbody>{body_html}</tbody>
        </table>
      </div>
    </section>
    """


def render_home_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    chart_teams = active_teams_for_season(teams, season)
    latest_day = max((safe_int(item.get("day")) for item in completed_game_items(data, season)), default=0)
    season_note = f"{season}, Day {latest_day}" if latest_day else f"Season {season}"
    body = f"""
    <section class="page-hero home-hero">
      <div>
        <h1>SMP Basketball League</h1>
        <p class="muted">{season_note}</p>
      </div>
    </section>
    {latest_results_strip(data, chart_teams, season)}
    <div class="home-columns">
      <div class="home-main">
        {standings_table(data, chart_teams, season)}
        {playoff_odds_card(data, chart_teams, season)}
        {league_leaders_card(data, players, teams, season)}
      </div>
      <div class="home-side">
        {news_feed_card(data, teams, season)}
        {injury_report_card(players, teams, season)}
        {rookie_watch_card(data, players, teams, season)}
      </div>
    </div>
    {team_stats_table(chart_teams, season)}
    {four_factors_table(data, chart_teams, season)}
    {awards_voting_table(data, players, teams, season)}
    """
    return page_html("Home", body, teams, root="", active="home")


AWARD_DISPLAY = [
    ("mvp", "MVP"),
    ("dpoy", "Defensive POY"),
    ("smoy", "Sixth Man"),
    ("roy", "Rookie of the Year"),
    ("mip", "Most Improved"),
    ("finalsMvp", "Finals MVP"),
]


def award_winner_html(winner: dict[str, Any] | None, all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    if not isinstance(winner, dict) or winner.get("pid") is None:
        return '<span class="muted">—</span>'
    name = event_player_link(winner.get("pid"), all_players_by_pid, root, label=winner.get("name"))
    team = team_abbrev(teams_by_tid.get(safe_int(winner.get("tid"), -10)))
    stats_bits = []
    for key, label in (("pts", "PTS"), ("trb", "TRB"), ("ast", "AST")):
        if winner.get(key) is not None:
            stats_bits.append(f"{fmt_number(winner.get(key), 1)} {label}")
    stat_text = f' <span class="muted small-copy">{esc(team)} · {esc(", ".join(stats_bits))}</span>' if stats_bits else f' <span class="muted small-copy">{esc(team)}</span>'
    return f"{name}{stat_text}"


def honors_html(award: dict[str, Any], all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    sections = []
    for key, title in (("allLeague", "All-League"), ("allDefensive", "All-Defensive"), ("allRookie", "All-Rookie")):
        groups = award.get(key)
        if not isinstance(groups, list) or not groups:
            continue
        if key == "allRookie" and groups and isinstance(groups[0], dict) and "players" not in groups[0]:
            groups = [{"title": "", "players": groups}]
        rows = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            names = [
                event_player_link(member.get("pid"), all_players_by_pid, root, label=member.get("name"))
                + f' <span class="muted small-copy">{esc(team_abbrev(teams_by_tid.get(safe_int(member.get("tid"), -10))))}</span>'
                for member in group.get("players") or []
                if isinstance(member, dict)
            ]
            if not names:
                continue
            group_title = group.get("title") or ""
            label = f"{title} {group_title}".strip()
            rows.append(f'<div class="honor-row"><span class="honor-label">{esc(label)}</span><span>{" · ".join(names)}</span></div>')
        sections.extend(rows)
    if not sections:
        return ""
    return f'<div class="honors">{"".join(sections)}</div>'


def playoff_bracket_html(ps: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    rounds = ps.get("series") or []
    if not rounds:
        return ""
    round_names = {1: ["Finals"], 2: ["Semifinals", "Finals"], 3: ["Quarterfinals", "Semifinals", "Finals"]}.get(len(rounds), [f"Round {i + 1}" for i in range(len(rounds))])
    cols = []
    for round_index, matchups in enumerate(rounds):
        cards = []
        for series in matchups:
            home, away = series.get("home") or {}, series.get("away") or {}
            home_won = safe_int(home.get("won"))
            away_won = safe_int(away.get("won"))
            winner_is_home = home_won > away_won
            def side(s, is_winner):
                team = teams_by_tid.get(safe_int(s.get("tid"), -10))
                label = f'({safe_int(s.get("seed"))}) {esc(team_abbrev(team))}'
                link = f'<a href="{team_url(team, root)}">{label}</a>' if team else label
                cls = "bracket-win" if is_winner else "bracket-loss"
                return f'<div class="{cls}"><span>{link}</span><strong>{safe_int(s.get("won"))}</strong></div>'
            cards.append(f'<div class="bracket-series">{side(home, winner_is_home)}{side(away, not winner_is_home)}</div>')
        cards_html = "".join(cards)
        cols.append(f'<div class="bracket-round"><h4>{esc(round_names[round_index])}</h4>{cards_html}</div>')
    return f'<div class="bracket">{"".join(cols)}</div>'


def past_season_leaders_html(data: dict[str, Any], season: int, all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    rows = []
    for player in data.get("players", []):
        stat = season_regular_stat(player, season)
        if stat_gp(stat) >= 20:
            rows.append((player, stat))
    if not rows:
        return ""
    categories = [
        ("PTS", lambda s: per_game(s, "pts")),
        ("TRB", lambda s: total_rebounds(s) / stat_gp(s) if stat_gp(s) else None),
        ("AST", lambda s: per_game(s, "ast")),
        ("PER", lambda s: s.get("per")),
    ]
    bits = []
    for label, fn in categories:
        scored = sorted(
            ((float(fn(s)), p) for p, s in rows if fn(s) is not None),
            key=lambda x: -x[0],
        )
        if not scored:
            continue
        value, player = scored[0]
        bits.append(
            f'<span class="leader-inline"><strong>{esc(label)}</strong> '
            f'{event_player_link(player.get("pid"), all_players_by_pid, root)} {fmt_number(value, 1)}</span>'
        )
    return f'<div class="leaders-inline">{"".join(bits)}</div>'


def draft_prospects(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        p for p in data.get("players", [])
        if p.get("tid") == DRAFT_PROSPECT_TID and p.get("retiredYear") is None
    ]


def prospect_row(player: dict[str, Any], season: int, rating_ranges: dict[str, tuple[float, float]], root: str = "") -> str:
    rating = latest_rating(player, season + 1) or latest_rating(player)
    cells = [
        td(f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>', sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - (player.get("born") or {}).get("year", season) if isinstance((player.get("born") or {}).get("year"), int) else None)),
        td(fmt_height(player.get("hgt")), sort=player.get("hgt")),
        td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
        td(esc(rating.get("pot", "—")), sort=rating.get("pot"), style=heat_style(rating.get("pot"), *rating_ranges.get("pot", (0, 0)), 1)),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, style=heat_style(value, lo, hi, 1), cls=cls))
    return "".join(cells)


def projected_lottery_html(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int) -> str:
    palette = team_palette_by_tid(teams)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    order = standings_order(active_teams_for_season(teams, season), season)
    reverse_order = list(reversed(order))
    picks = [dp for dp in data.get("draftPicks", []) if isinstance(dp, dict) and dp.get("season") == draft_year]
    owner_by_slot: dict[tuple[int, int], int] = {}
    for dp in picks:
        owner_by_slot[(safe_int(dp.get("round")), safe_int(dp.get("originalTid"), -10))] = safe_int(dp.get("tid"), -10)
    rounds = sorted({safe_int(dp.get("round")) for dp in picks}) or [1, 2]
    rows = []
    pick_no = 0
    for rnd in rounds:
        for slot_tid in reverse_order:
            pick_no += 1
            slot_team = teams_by_tid.get(slot_tid, {})
            owner_tid = owner_by_slot.get((rnd, slot_tid), slot_tid)
            owner_team = teams_by_tid.get(owner_tid, {})
            team_season = latest_team_season(slot_team, season)
            record = fmt_record(team_season.get("won"), team_season.get("lost"))
            if owner_tid == slot_tid:
                owner_html = f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)}'
            else:
                owner_html = (
                    f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)} '
                    f'<span class="badge badge-good" title="Acquired via trade">via {esc(team_abbrev(slot_team))}</span>'
                )
            rows.append(f'<tr data-tid="{owner_tid}">' + "".join([
                td(pick_no, sort=pick_no),
                td(f"R{rnd}", sort=rnd),
                td(f'{team_dot(slot_tid, palette)}{team_anchor(slot_team)} <span class="muted small-copy">({esc(record)})</span>', sort=team_full_name(slot_team), cls="name-cell"),
                td(owner_html, sort=team_full_name(owner_team), cls="name-cell"),
            ]) + "</tr>")
    if not rows:
        return ""
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Projected Draft Order</h2><span class="muted small-copy">reverse of current standings (lottery luck not simulated) · green badge = pick changed hands</span></div>
      {table_html(["Pick", "Rd", "Slot (record)", "Owned by"], rows, table_id="lottery", empty_message="No draft picks found.", wrap_cls="fit-table")}
    </section>
    """


def render_draft_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    prospects = draft_prospects(data)
    draft_years = sorted({(p.get("draft") or {}).get("year") for p in prospects if (p.get("draft") or {}).get("year")})
    draft_year = draft_years[0] if draft_years else season
    sorted_prospects = sorted(
        prospects,
        key=lambda p: (-safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    rating_ranges: dict[str, tuple[float, float]] = {}
    for key in [k for k, _ in TEAM_RATING_RANK_KEYS] + ["pot"]:
        values = []
        for p in sorted_prospects:
            value = latest_rating(p).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers: list = ["Name", "Pos", "Age", "Ht", "Ovr", "Pot"]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [prospect_row(p, season, rating_ranges) for p in sorted_prospects]
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Draft {esc(draft_year)}</h1>
        <p class="muted">{len(sorted_prospects)} prospects · sorted by potential · ratings color-scaled against this class</p>
      </div>
    </section>
    {projected_lottery_html(data, teams, season, draft_year)}
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="prospects" placeholder="Filter prospects…" aria-label="Filter prospects">
      </div>
      {table_html(headers, rows, table_id="prospects", empty_message="No draft prospects in this export.")}
    </section>
    """
    return page_html("Draft", body, teams, root="", active="draft")


def contract_efficiency_table(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    rows_data = []
    for player in players:
        if safe_int(player.get("tid"), -9) < 0:
            continue
        contract = player.get("contract") or {}
        amount = safe_float(contract.get("amount"))
        if amount < 1000:
            continue  # minimum contracts are trivially "efficient"
        stat = season_regular_stat(player, season)
        ws = safe_float(stat.get("ows")) + safe_float(stat.get("dws"))
        vorp = safe_float(stat.get("vorp"))
        ws_per_m = ws / (amount / 1000.0)
        rows_data.append((player, amount, contract.get("exp"), ws, vorp, ws_per_m))
    if not rows_data:
        return ""
    eff_values = [r[5] for r in rows_data]
    lo, hi = min(eff_values), max(eff_values)
    rows_data.sort(key=lambda r: -r[5])
    rows = []
    for player, amount, exp, ws, vorp, ws_per_m in rows_data:
        rows.append("".join([
            td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
            td(f'{team_dot(player.get("tid"), palette)}{team_label(player.get("tid"), teams_by_tid, root)}', sort=team_label(player.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season), sort=age(player, season)),
            td(esc(latest_rating(player, season).get("ovr", "—")), sort=latest_rating(player, season).get("ovr")),
            td(fmt_money(amount), sort=amount),
            td(esc(exp or "—"), sort=exp),
            td(fmt_number(ws, 1), sort=ws),
            td(fmt_number(vorp, 1), sort=vorp),
            td(fmt_number(player.get("value"), 1), sort=player.get("value")),
            td(fmt_number(ws_per_m * 10, 2), sort=ws_per_m, style=heat_style(ws_per_m, lo, hi, 1)),
        ]))
    headers = ["Player", "Team", "Age", "Ovr", "Salary", "Thru", "WS", "VORP", "Value", "WS per $10M"]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Contract Efficiency</h2><span class="muted small-copy">production per salary dollar, non-minimum contracts · this season</span></div>
      <div class="toolbar">
        <input class="table-search" data-table-filter="contracts" placeholder="Filter contracts…" aria-label="Filter contracts">
      </div>
      {table_html(headers, rows, table_id="contracts", empty_message="No contracts found.")}
    </section>
    """


def trading_block_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    blocks = data.get("savedTradingBlock") or []
    if not isinstance(blocks, list) or not blocks:
        return ""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    palette = team_palette_by_tid(teams)
    cards = []
    for block in blocks:
        tid = safe_int(block.get("tid"), -10)
        team = teams_by_tid.get(tid)
        if team is None:
            continue
        asked_pids = block.get("pids") or []
        asked_html = []
        asked_value = 0.0
        for pid in asked_pids:
            player = ALL_PLAYERS_BY_PID.get(safe_int(pid, -10))
            if not player:
                continue
            asked_value += safe_float(player.get("value"))
            asked_html.append(
                f'<span class="pick-chip">{event_player_link(pid, ALL_PLAYERS_BY_PID, root)} '
                f'<span class="muted small-copy">{fmt_number(player.get("value"), 0)}</span></span>'
            )
        offer_rows = []
        for offer in block.get("offers") or []:
            offer_tid = safe_int(offer.get("tid"), -10)
            offer_team = teams_by_tid.get(offer_tid)
            names = []
            offer_value = 0.0
            for pid in offer.get("pids") or []:
                player = ALL_PLAYERS_BY_PID.get(safe_int(pid, -10))
                if not player:
                    continue
                offer_value += safe_float(player.get("value"))
                names.append(event_player_link(pid, ALL_PLAYERS_BY_PID, root))
            picks_count = len(offer.get("dpids") or [])
            if picks_count:
                names.append(f"{picks_count} draft pick{'s' if picks_count > 1 else ''}")
            delta = offer_value - asked_value
            offer_rows.append((delta, "".join([
                td(f'{team_dot(offer_tid, palette)}{team_anchor(offer_team)}' if offer_team else "—", sort=team_full_name(offer_team) if offer_team else "", cls="name-cell"),
                td(", ".join(names) or '<span class="muted">nothing</span>', sort=offer_value, cls="offer-cell"),
                td(fmt_number(offer_value, 0), sort=offer_value),
                td(fmt_signed(delta, 0), sort=delta, cls=plus_minus_class(delta)),
            ])))
        offer_rows.sort(key=lambda pair: -pair[0])
        offers_table = table_html(
            ["Team", "Their offer", "Offer value", "vs asked"],
            [row for _, row in offer_rows],
            table_id=f"block-{tid}",
            empty_message="No offers on record.",
        )
        cards.append(f"""
        <section class="card home-section">
          <div class="section-title-row"><h2>Trading Block · {esc(team_abbrev(team))}</h2><span class="muted small-copy">players shopped and the offers other teams have made</span></div>
          <div class="pick-row">{''.join(asked_html) or '<span class="muted">No players listed.</span>'}</div>
          <p class="muted small-copy">Asked value: {fmt_number(asked_value, 0)} (BBGM trade value)</p>
          {offers_table}
        </section>
        """)
    return "".join(cards)


def trade_machine_payload(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, cap: float) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    out_teams = []
    for team in sorted(teams, key=team_abbrev):
        tid = safe_int(team.get("tid"))
        roster = [p for p in players if safe_int(p.get("tid"), -9) == tid]
        roster.sort(key=lambda p: -safe_float((p.get("contract") or {}).get("amount")))
        payroll = team_payroll(roster, season)
        picks = []
        for dp in data.get("draftPicks", []):
            if safe_int(dp.get("tid"), -10) != tid or not isinstance(dp.get("season"), int):
                continue
            via = ""
            if safe_int(dp.get("originalTid"), -10) != tid:
                via = team_abbrev(teams_by_tid.get(safe_int(dp.get("originalTid"), -10)))
            picks.append({
                "id": dp.get("dpid"),
                "label": f"{dp.get('season')} {'1st' if safe_int(dp.get('round')) == 1 else '2nd'}" + (f" (via {via})" if via else ""),
            })
        out_teams.append({
            "tid": tid,
            "abbrev": team_abbrev(team),
            "name": team_full_name(team),
            "payroll": payroll,
            "players": [
                {
                    "pid": p.get("pid"),
                    "n": player_name(p),
                    "pos": latest_rating(p, season).get("pos", ""),
                    "age": age(p, season),
                    "ovr": latest_rating(p, season).get("ovr"),
                    "amt": safe_float((p.get("contract") or {}).get("amount")),
                    "exp": (p.get("contract") or {}).get("exp"),
                    "value": round(safe_float(p.get("value")), 1),
                    "u": player_url(p),
                }
                for p in roster
            ],
            "picks": picks,
        })
    payload = {"cap": cap, "teams": out_teams}
    return json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


TRADE_MACHINE_JS = r"""
(function () {
  const dataEl = document.getElementById('trade-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const fmtM = (k) => {
    const sign = k < 0 ? '-' : '';
    const m = Math.abs(k) / 1000;
    return sign + '$' + (Math.round(m * 100) / 100) + 'M';
  };
  const sides = [
    { sel: document.querySelector('[data-trade-team="0"]'), list: document.querySelector('[data-trade-list="0"]'), picked: new Set(), pickedPicks: new Set() },
    { sel: document.querySelector('[data-trade-team="1"]'), list: document.querySelector('[data-trade-list="1"]'), picked: new Set(), pickedPicks: new Set() },
  ];
  const summary = document.querySelector('[data-trade-summary]');

  sides.forEach((side, index) => {
    data.teams.forEach((team) => {
      const opt = document.createElement('option');
      opt.value = team.tid;
      opt.textContent = team.abbrev + ' — ' + team.name;
      side.sel.appendChild(opt);
    });
    side.sel.selectedIndex = index === 0 ? 0 : 1;
    side.sel.addEventListener('change', () => { side.picked.clear(); side.pickedPicks.clear(); renderSide(index); renderSummary(); });
  });

  function teamOf(side) {
    return data.teams.find((t) => String(t.tid) === String(side.sel.value));
  }

  function renderSide(index) {
    const side = sides[index];
    const team = teamOf(side);
    side.list.innerHTML = '';
    team.players.forEach((p) => {
      const row = document.createElement('label');
      row.className = 'trade-row';
      row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + p.n + '</span>'
        + '<span class="muted">' + p.pos + ' · ' + p.age + 'y · ' + p.ovr + ' ovr</span>'
        + '<span class="trade-amt">' + fmtM(p.amt) + '/' + (p.exp || '—') + '</span>'
        + '<span class="trade-val">' + p.value + '</span>';
      const box = row.querySelector('input');
      box.checked = side.picked.has(p.pid);
      box.addEventListener('change', () => {
        if (box.checked) side.picked.add(p.pid); else side.picked.delete(p.pid);
        renderSummary();
      });
      side.list.appendChild(row);
    });
    if (team.picks.length) {
      team.picks.forEach((pick) => {
        const row = document.createElement('label');
        row.className = 'trade-row trade-pick';
        row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + pick.label + '</span><span class="muted">draft pick</span><span class="trade-amt"></span><span class="trade-val">—</span>';
        const box = row.querySelector('input');
        box.checked = side.pickedPicks.has(pick.id);
        box.addEventListener('change', () => {
          if (box.checked) side.pickedPicks.add(pick.id); else side.pickedPicks.delete(pick.id);
          renderSummary();
        });
        side.list.appendChild(row);
      });
    }
  }

  function sideAssets(side) {
    const team = teamOf(side);
    const players = team.players.filter((p) => side.picked.has(p.pid));
    const picks = team.picks.filter((pick) => side.pickedPicks.has(pick.id));
    const salary = players.reduce((s, p) => s + p.amt, 0);
    const value = players.reduce((s, p) => s + p.value, 0);
    return { team, players, picks, salary, value };
  }

  function renderSummary() {
    const a = sideAssets(sides[0]);
    const b = sideAssets(sides[1]);
    if (String(a.team.tid) === String(b.team.tid)) {
      summary.innerHTML = '<p class="muted">Pick two different teams.</p>';
      return;
    }
    const newPayrollA = a.team.payroll - a.salary + b.salary;
    const newPayrollB = b.team.payroll - b.salary + a.salary;
    const capFlag = (payroll) => payroll > data.cap
      ? ' <span class="delta-down">(' + fmtM(payroll - data.cap) + ' over the cap)</span>'
      : ' <span class="delta-up">(' + fmtM(data.cap - payroll) + ' under)</span>';
    const diff = a.value - b.value;
    let verdict = 'Even value trade.';
    if (Math.abs(diff) > 1) {
      const winner = diff > 0 ? b.team.abbrev : a.team.abbrev;
      verdict = winner + ' wins this trade by ' + Math.abs(Math.round(diff * 10) / 10) + ' value' + (a.picks.length || b.picks.length ? ' (draft picks not valued)' : '');
    }
    const lines = [];
    const describe = (from, to) => {
      const bits = from.players.map((p) => p.n).concat(from.picks.map((pick) => pick.label));
      return '<p><strong>' + from.team.abbrev + ' → ' + to.team.abbrev + ':</strong> ' + (bits.join(', ') || '<span class="muted">nothing</span>')
        + ' <span class="muted">(salary ' + fmtM(from.salary) + ', value ' + (Math.round(from.value * 10) / 10) + ')</span></p>';
    };
    lines.push(describe(a, b));
    lines.push(describe(b, a));
    lines.push('<p><strong>' + a.team.abbrev + '</strong> payroll after: ' + fmtM(newPayrollA) + capFlag(newPayrollA) + '</p>');
    lines.push('<p><strong>' + b.team.abbrev + '</strong> payroll after: ' + fmtM(newPayrollB) + capFlag(newPayrollB) + '</p>');
    const blocked = (newPayrollA > data.cap && b.salary > a.salary) || (newPayrollB > data.cap && a.salary > b.salary);
    if (blocked) {
      lines.push('<p class="delta-down"><strong>⚠ Likely blocked:</strong> a team over the hard cap cannot take back more salary than it sends out.</p>');
    }
    lines.push('<p class="trade-verdict">' + verdict + '</p>');
    summary.innerHTML = lines.join('');
  }

  renderSide(0);
  renderSide(1);
  renderSummary();
})();
"""


def render_trade_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, cap: float) -> str:
    payload = trade_machine_payload(data, teams, players, season, cap)
    machine = f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Trade Machine</h2><span class="muted small-copy">check assets on both sides · salaries vs the {fmt_money(cap)} hard cap · BBGM trade values</span></div>
      <div class="trade-grid">
        <div class="trade-side">
          <label class="select-label">Team A <select data-trade-team="0"></select></label>
          <div class="trade-list" data-trade-list="0"></div>
        </div>
        <div class="trade-side">
          <label class="select-label">Team B <select data-trade-team="1"></select></label>
          <div class="trade-list" data-trade-list="1"></div>
        </div>
      </div>
      <div class="trade-summary" data-trade-summary></div>
    </section>
    <script type="application/json" id="trade-data">{payload}</script>
    <script>{TRADE_MACHINE_JS}</script>
    """
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Trade Center</h1>
        <p class="muted">Build trades, see what teams are shopping, and find contract bargains</p>
      </div>
    </section>
    {machine}
    {trading_block_card(data, teams, season)}
    {contract_efficiency_table(players, teams, season)}
    """
    return page_html("Trade Center", body, teams, root="", active="trade")


COMPARE_JS = r"""
(function () {
  const dataEl = document.getElementById('compare-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const byPid = {};
  data.players.forEach((p) => { byPid[p.pid] = p; });
  const selects = Array.from(document.querySelectorAll('[data-compare-select]'));
  const out = document.querySelector('[data-compare-out]');

  selects.forEach((sel) => {
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '— none —';
    sel.appendChild(blank);
    data.players.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.pid;
      opt.textContent = p.n + ' (' + p.t + ')';
      sel.appendChild(opt);
    });
    sel.addEventListener('change', () => { syncHash(); render(); });
  });

  const fromHash = (location.hash || '').replace(/^#/, '').split(',').filter(Boolean);
  if (fromHash.length) {
    fromHash.slice(0, 3).forEach((pid, i) => { if (byPid[pid]) selects[i].value = pid; });
  } else {
    if (data.players[0]) selects[0].value = data.players[0].pid;
    if (data.players[1]) selects[1].value = data.players[1].pid;
  }

  function syncHash() {
    const pids = selects.map((s) => s.value).filter(Boolean);
    history.replaceState(null, '', '#' + pids.join(','));
  }

  const RATINGS = data.ratingKeys;
  const STATS = [
    ['gp', 'Games'], ['mpg', 'MP/G'], ['pts', 'PTS/G'], ['trb', 'TRB/G'], ['ast', 'AST/G'],
    ['stl', 'STL/G'], ['blk', 'BLK/G'], ['tov', 'TOV/G'], ['ts', 'TS%'], ['per', 'PER'],
    ['bpm', 'BPM'], ['ws', 'WS'],
  ];

  function render() {
    const chosen = selects.map((s) => byPid[s.value]).filter(Boolean);
    if (chosen.length < 2) {
      out.innerHTML = '<p class="muted">Pick at least two players.</p>';
      return;
    }
    let html = '<div class="table-wrap fit-table"><table class="cmp-players"><thead><tr><th></th>';
    chosen.forEach((p) => {
      html += '<th><a href="' + p.u + '">' + p.n + '</a><span class="muted"> ' + p.t + ' · ' + p.pos + ' · ' + p.age + 'y</span></th>';
    });
    html += '</tr></thead><tbody>';
    const row = (label, values, fmt, withBar) => {
      html += '<tr><td class="cmp-label">' + label + '</td>';
      const nums = values.map(Number).filter(Number.isFinite);
      const best = nums.length ? Math.max(...nums) : null;
      values.forEach((v) => {
        const num = Number(v);
        const isBest = Number.isFinite(num) && num === best && nums.length > 1;
        let cell = (v === null || v === undefined || v === '') ? '—' : (fmt ? fmt(num) : v);
        if (withBar && Number.isFinite(num)) {
          cell = '<span class="cmp-bar"><i style="width:' + Math.max(2, Math.min(100, num)) + '%"></i></span>' + cell;
        }
        html += '<td class="' + (isBest ? 'cmp-best' : '') + '">' + cell + '</td>';
      });
      html += '</tr>';
    };
    row('Overall', chosen.map((p) => p.ovr), null, true);
    row('Potential', chosen.map((p) => p.pot), null, true);
    row('Contract', chosen.map((p) => p.contract), (v) => v, false);
    row('Trade value', chosen.map((p) => p.value));
    RATINGS.forEach(([key, label]) => row(label, chosen.map((p) => p.r[key]), null, true));
    STATS.forEach(([key, label]) => row(label, chosen.map((p) => p.s[key])));
    html += '</tbody></table></div>';
    out.innerHTML = html;
  }
  render();
})();
"""


def render_compare_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    payload_players = []
    pool = sorted(players, key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
    for p in pool:
        rating = latest_rating(p, season)
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        contract = p.get("contract") or {}
        contract_text = fmt_money(contract.get("amount"))
        if contract.get("exp") is not None:
            contract_text += f"/{contract.get('exp')}"
        payload_players.append({
            "pid": p.get("pid"),
            "n": player_name(p),
            "t": team_abbrev_for_tid(p.get("tid"), teams_by_tid) if safe_int(p.get("tid"), -1) >= 0 else "FA",
            "pos": rating.get("pos", ""),
            "age": age(p, season),
            "ovr": rating.get("ovr"),
            "pot": rating.get("pot"),
            "contract": contract_text,
            "value": round(safe_float(p.get("value")), 1),
            "u": player_url(p),
            "r": {key: rating.get(key) for key in RATING_LABELS},
            "s": {
                "gp": int(gp),
                "mpg": round(per_game(stat, "min") or 0, 1),
                "pts": round(per_game(stat, "pts") or 0, 1),
                "trb": round(total_rebounds(stat) / gp, 1) if gp else 0,
                "ast": round(per_game(stat, "ast") or 0, 1),
                "stl": round(per_game(stat, "stl") or 0, 1),
                "blk": round(per_game(stat, "blk") or 0, 1),
                "tov": round(per_game(stat, "tov") or 0, 1),
                "ts": round(ts_pct(stat) or 0, 1) if ts_pct(stat) is not None else None,
                "per": round(safe_float(stat.get("per")), 1),
                "bpm": round(safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm")), 1),
                "ws": round(safe_float(stat.get("ows")) + safe_float(stat.get("dws")), 1),
            },
        })
    payload = {
        "ratingKeys": [[key, label] for key, label in RATING_LABELS.items()],
        "players": payload_players,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Compare Players</h1>
        <p class="muted">Pick two or three players · best value in each row is highlighted · share the URL to share the comparison</p>
      </div>
    </section>
    <section class="card">
      <div class="toolbar compare-toolbar">
        <label class="select-label">Player 1 <select data-compare-select></select></label>
        <label class="select-label">Player 2 <select data-compare-select></select></label>
        <label class="select-label">Player 3 <select data-compare-select></select></label>
      </div>
      <div data-compare-out></div>
    </section>
    <script type="application/json" id="compare-data">{payload_json}</script>
    <script>{COMPARE_JS}</script>
    """
    return page_html("Compare Players", body, teams, root="", active="players")


def transactions_archive_html(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    wanted = {"freeAgent", "reSigned", "release", "trade"}
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in data.get("events", []):
        if event.get("type") in wanted and isinstance(event.get("season"), int):
            by_season[event["season"]].append(event)
    if not by_season:
        return ""
    season_blocks = []
    for season in sorted(by_season, reverse=True):
        events = sorted(by_season[season], key=lambda e: -safe_int(e.get("eid")))
        items = []
        for event in events:
            html_text = compose_event_html(event, all_players_by_pid, teams_by_tid, season, set(), "")
            if not html_text:
                continue
            label, badge_cls = EVENT_BADGES.get(event.get("type"), ("NEWS", "badge-muted"))
            items.append(f'<li><span class="badge {badge_cls}">{esc(label)}</span><span>{html_text}</span></li>')
        if not items:
            continue
        open_attr = " open" if season == max(by_season) else ""
        season_blocks.append(
            f'<details class="tx-season"{open_attr}><summary>Season {season} <span class="count-pill">{len(items)} moves</span></summary>'
            f'<ul class="news-list">{"".join(items)}</ul></details>'
        )
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Transaction Log</h2><span class="muted small-copy">every signing, trade, and waiver on record</span></div>
      {''.join(season_blocks)}
    </section>
    """


def render_history_page(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    awards_by_season = {a.get("season"): a for a in data.get("awards", []) if isinstance(a, dict)}
    playoffs_by_season = {ps.get("season"): ps for ps in data.get("playoffSeries", []) if isinstance(ps, dict)}
    seasons = sorted(set(awards_by_season) | set(playoffs_by_season), reverse=True)

    # summary table
    summary_rows = []
    for season in seasons:
        ps = playoffs_by_season.get(season) or {}
        champion = runner_up = None
        rounds = ps.get("series") or []
        if rounds:
            final = rounds[-1][0] if rounds[-1] else {}
            home, away = final.get("home") or {}, final.get("away") or {}
            if home and away:
                champion = home if safe_int(home.get("won")) > safe_int(away.get("won")) else away
                runner_up = away if champion is home else home
        award = awards_by_season.get(season) or {}
        def team_cell(side):
            if not side:
                return '<span class="muted">—</span>'
            team = teams_by_tid.get(safe_int(side.get("tid"), -10))
            return f'{team_anchor(team)}' if team else "—"
        summary_rows.append("".join([
            td(esc(season), sort=season),
            td(team_cell(champion), cls="name-cell"),
            td(team_cell(runner_up)),
            td(award_winner_html(award.get("finalsMvp"), all_players_by_pid, teams_by_tid, ""), cls="name-cell"),
            td(award_winner_html(award.get("mvp"), all_players_by_pid, teams_by_tid, ""), cls="name-cell"),
        ]))

    season_cards = []
    for season in seasons:
        award = awards_by_season.get(season) or {}
        ps = playoffs_by_season.get(season)
        award_rows = "".join(
            f'<div class="detail-item"><span>{esc(label)}</span><strong>{award_winner_html(award.get(key), all_players_by_pid, teams_by_tid, "")}</strong></div>'
            for key, label in AWARD_DISPLAY if award.get(key)
        )
        bracket = playoff_bracket_html(ps, teams_by_tid, "") if ps else ""
        leaders = past_season_leaders_html(data, season, all_players_by_pid, teams_by_tid, "")
        honors = honors_html(award, all_players_by_pid, teams_by_tid, "")
        season_cards.append(f"""
        <section class="card home-section">
          <div class="section-title-row"><h2>Season {season}</h2></div>
          {bracket}
          {leaders}
          <div class="details-grid history-awards">{award_rows}</div>
          {honors}
        </section>
        """)

    body = f"""
    <section class="page-hero">
      <div>
        <h1>League History</h1>
        <p class="muted">Champions, awards, and playoff brackets from past seasons</p>
      </div>
    </section>
    <section class="card home-section">
      <div class="section-title-row"><h2>Champions</h2></div>
      {table_html(["Season", "Champion", "Runner-up", "Finals MVP", "MVP"], summary_rows, table_id="champions", empty_message="No completed seasons yet.")}
    </section>
    {''.join(season_cards)}
    {transactions_archive_html(data, teams)}
    """
    return page_html("History", body, teams, root="", active="history")


def all_time_leaders_html(data: dict[str, Any], teams: list[dict[str, Any]], root: str = "") -> str:
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    totals = []
    for player in data.get("players", []):
        rows = [s for s in player.get("stats", []) if isinstance(s, dict) and not s.get("playoffs")]
        if not rows:
            continue
        combined = combine_stat_rows(rows)
        if stat_gp(combined) <= 0:
            continue
        totals.append((player, combined))
    if not totals:
        return ""

    def box(title, value_fn, digits=0):
        scored = []
        for player, stat in totals:
            value = value_fn(stat)
            if value is None:
                continue
            scored.append((float(value), player))
        scored.sort(key=lambda x: (-x[0], player_name(x[1])))
        rows = []
        for rank, (value, player) in enumerate(scored[:10], 1):
            retired = player.get("retiredYear") is not None
            name = event_player_link(player.get("pid"), all_players_by_pid, root)
            tag = ' <span class="muted small-copy">(ret.)</span>' if retired else ""
            rows.append(
                f'<li><span class="leader-rank">{rank}</span><span>{name}{tag}</span>'
                f'<span class="leader-value">{fmt_number(value, digits)}</span></li>'
            )
        return f'<div class="leader-box"><h3>{esc(title)}</h3><ol class="leader-list">{"".join(rows)}</ol></div>'

    boxes = [
        box("Career Points", lambda s: s.get("pts")),
        box("Career Rebounds", lambda s: total_rebounds(s)),
        box("Career Assists", lambda s: s.get("ast")),
        box("Career Steals", lambda s: s.get("stl")),
        box("Career Blocks", lambda s: s.get("blk")),
        box("Career Threes", lambda s: s.get("tp")),
        box("Career Win Shares", lambda s: safe_float(s.get("ows")) + safe_float(s.get("dws")), digits=1),
        box("Career VORP", lambda s: s.get("vorp"), digits=1),
        box("Games Played", lambda s: s.get("gp")),
    ]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>All-Time Leaders</h2><span class="muted small-copy">regular season, all seasons on record, including retired players</span></div>
      <div class="leader-grid">{''.join(boxes)}</div>
    </section>
    """


def feat_badges(stats: dict[str, Any]) -> list[str]:
    badges = []
    pts = safe_int(stats.get("pts"))
    if pts >= 60:
        badges.append(f"{pts}-point game")
    elif pts >= 50:
        badges.append("50+ points")
    if safe_int(stats.get("fxf")):
        badges.append("5x5")
    if safe_int(stats.get("qd")):
        badges.append("Quadruple-double")
    elif safe_int(stats.get("td")):
        badges.append("Triple-double")
    trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
    if trb >= 25:
        badges.append(f"{trb} rebounds")
    if safe_int(stats.get("ast")) >= 20:
        badges.append(f"{stats.get('ast')} assists")
    if safe_int(stats.get("tp")) >= 10:
        badges.append(f"{stats.get('tp')} threes")
    if safe_int(stats.get("blk")) >= 10:
        badges.append(f"{stats.get('blk')} blocks")
    if safe_int(stats.get("stl")) >= 10:
        badges.append(f"{stats.get('stl')} steals")
    return badges or ["Feat"]


def render_records_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    current_gids = {str(g.get("gid")) for g in data.get("games", []) if g.get("season") == season}
    feats = [f for f in data.get("playerFeats", []) if isinstance(f, dict)]
    feats.sort(key=lambda f: (-safe_int(f.get("season")), -safe_int((f.get("stats") or {}).get("pts"))))
    rows = []
    for feat in feats:
        stats = feat.get("stats") or {}
        trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
        badges = " ".join(f'<span class="badge badge-accent">{esc(b)}</span>' for b in feat_badges(stats))
        result_text = f"{esc(feat.get('result', ''))} {esc(feat.get('score', ''))}"
        if str(feat.get("gid")) in current_gids and safe_int(feat.get("season")) == season:
            result_text = f'<a href="games/{esc(game_slug_from_gid(feat.get("gid")))}.html">{result_text}</a>'
        line = (
            f"{safe_int(stats.get('pts'))} PTS · {trb} TRB · {safe_int(stats.get('ast'))} AST · "
            f"{safe_int(stats.get('stl'))} STL · {safe_int(stats.get('blk'))} BLK"
        )
        rows.append("".join([
            td(esc(feat.get("season")), sort=feat.get("season")),
            td(event_player_link(feat.get("pid"), all_players_by_pid, "", label=feat.get("name")), sort=feat.get("name"), cls="name-cell"),
            td(team_label(feat.get("tid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("tid"), teams_by_tid)),
            td(team_label(feat.get("oppTid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("oppTid"), teams_by_tid)),
            td(result_text, sort=feat.get("score")),
            td(line, sort=safe_int(stats.get("pts"))),
            td(badges, sort=" ".join(feat_badges(stats))),
        ]))
    headers = ["Season", "Player", "Team", "Opp", "Result", "Line", "Feat"]
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Records &amp; Feats</h1>
        <p class="muted">All-time leaderboards and {len(rows)} notable single-game performances</p>
      </div>
    </section>
    {all_time_leaders_html(data, teams)}
    <section class="card">
      <div class="section-title-row"><h2>Single-Game Feats</h2></div>
      <div class="toolbar">
        <input class="table-search" data-table-filter="feats" placeholder="Filter feats…" aria-label="Filter feats">
      </div>
      {table_html(headers, rows, table_id="feats", empty_message="No feats recorded yet.")}
    </section>
    """
    return page_html("Records", body, teams, root="", active="records")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def stylesheet() -> str:
    return r"""
:root {
  --bg: #101317;
  --panel: #171b21;
  --panel-2: #1f242c;
  --panel-3: #272d36;
  --line: #2b313a;
  --text: #e8ecf1;
  --muted: #939ca7;
  --accent: #5b9dff;
  --good: #3fbf72;
  --bad: #e2566b;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 14px;
  line-height: 1.4;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- header / nav ---------- */
.site-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  gap: .4rem 1rem;
  align-items: center;
  justify-content: space-between;
  padding: .5rem clamp(.75rem, 2.5vw, 1.5rem);
  background: rgba(16, 19, 23, .96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}
.brand a {
  color: var(--text);
  font-weight: 700;
  font-size: .95rem;
  letter-spacing: .01em;
  text-decoration: none;
}
.primary-nav {
  display: flex;
  flex-wrap: wrap;
  gap: .2rem;
  align-items: center;
}
.primary-nav a {
  white-space: nowrap;
  padding: .3rem .6rem;
  border: 1px solid transparent;
  border-radius: .4rem;
  color: var(--muted);
  font-size: .85rem;
  font-weight: 500;
  text-decoration: none;
}
.primary-nav a:hover, .primary-nav a.active {
  color: var(--text);
  background: var(--panel-2);
  border-color: var(--line);
}
.team-dropdown { position: relative; flex: 0 0 auto; }
.team-dropdown summary {
  list-style: none;
  cursor: pointer;
  white-space: nowrap;
  padding: .3rem .6rem;
  border: 1px solid transparent;
  border-radius: .4rem;
  color: var(--muted);
  font-size: .85rem;
  font-weight: 500;
}
.team-dropdown summary::-webkit-details-marker { display: none; }
.team-dropdown summary::after { content: " ▾"; color: var(--muted); font-size: .75rem; }
.team-dropdown[open] summary, .team-dropdown.active summary, .team-dropdown summary:hover {
  color: var(--text);
  background: var(--panel-2);
  border-color: var(--line);
}
.team-menu {
  position: absolute;
  top: calc(100% + .35rem);
  right: 0;
  z-index: 40;
  display: grid;
  gap: .1rem;
  width: max-content;
  min-width: 13rem;
  max-height: min(70vh, 26rem);
  overflow-y: auto;
  padding: .35rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel);
  box-shadow: 0 10px 30px rgba(0,0,0,.45);
}
.team-menu a {
  display: block;
  white-space: nowrap;
  padding: .35rem .55rem;
  border-radius: .35rem;
  color: var(--muted);
  font-size: .85rem;
  font-weight: 500;
  text-decoration: none;
}
.team-menu a:hover, .team-menu a.active { color: var(--text); background: var(--panel-2); }

/* ---------- layout ---------- */
.page-shell {
  width: min(100%, 1560px);
  margin: 0 auto;
  padding: 1rem clamp(.75rem, 2vw, 1.5rem) 2.5rem;
}
.page-hero, .card {
  border: 1px solid var(--line);
  border-radius: .6rem;
  background: var(--panel);
}
.page-hero { margin-bottom: .75rem; padding: .8rem 1rem; }
.eyebrow {
  margin: 0 0 .15rem;
  color: var(--muted);
  font-size: .7rem;
  font-weight: 600;
  letter-spacing: .09em;
  text-transform: uppercase;
}
h1, h2 { margin: 0; line-height: 1.2; }
h1 { font-size: 1.3rem; font-weight: 700; }
h2 { font-size: .8rem; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.muted { color: var(--muted); }
.small-copy { font-size: .78rem; }
.number { display: inline-block; min-width: 1.3rem; text-align: right; margin-right: .15rem; color: var(--muted); }
.card { margin-bottom: .75rem; padding: .75rem; }
.compact-card { padding: .55rem; }
.section-title-row, .toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: .75rem;
  margin-bottom: .5rem;
}
.count-pill, .mini-skill, .mood-chip, .award-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-3);
  color: var(--text);
  font-weight: 500;
}
.count-pill { padding: .08rem .5rem; color: var(--muted); font-size: .75rem; }
.mini-skill { padding: .02rem .26rem; margin-left: .15rem; font-size: .66rem; color: var(--muted); }
.mood-chip { padding: .02rem .32rem; margin-right: .12rem; color: var(--good); font-size: .75rem; }
.award-chip { padding: .12rem .5rem; margin: .12rem .18rem .12rem 0; font-size: .75rem; }

/* ---------- tables ---------- */
.table-wrap { overflow-x: auto; border-radius: .5rem; border: 1px solid var(--line); }
table { width: 100%; border-collapse: collapse; background: var(--panel); font-size: .8rem; }
th, td { padding: .32rem .55rem; border-bottom: 1px solid rgba(255,255,255,.05); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; position: sticky; left: 0; z-index: 2; }
td:first-child { background: inherit; }
th:first-child { z-index: 4; }
thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--panel-2);
  color: var(--muted);
  font-size: .72rem;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--line);
}
table[data-sortable] thead th:hover { color: var(--text); }
thead th.sort-asc::after { content: " ↑"; color: var(--accent); }
thead th.sort-desc::after { content: " ↓"; color: var(--accent); }
tbody tr:nth-child(odd) { background: #1a1f26; }
tbody tr:nth-child(even) { background: var(--panel); }
tbody tr:hover { background: var(--panel-3); }
tbody tr:last-child td { border-bottom: 0; }
.name-cell { min-width: 11rem; }
.player-link { color: var(--text); font-weight: 600; }
.player-link:hover { color: var(--accent); }
.delta-up { color: var(--good); font-weight: 600; }
.delta-down { color: var(--bad); font-weight: 600; }
.healthy { color: var(--good); }
.injured { color: var(--bad); }
.row-rank { display: inline-block; min-width: 1.5rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.clinch { color: var(--muted); font-weight: 700; margin-left: .2rem; }
tr.playoff-cut > td { border-top: 2px solid var(--accent); }
tr.avg-row > td { border-top: 1px solid var(--line); color: var(--muted); font-style: italic; }

/* ---------- controls ---------- */
.table-search {
  width: min(100%, 20rem);
  padding: .45rem .65rem;
  border-radius: .45rem;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--text);
  font: inherit;
  font-size: .85rem;
  outline: none;
}
.table-search:focus { border-color: var(--accent); }
.empty-state { margin: .6rem 0 0; color: var(--muted); font-size: .85rem; }
.select-label { display: flex; align-items: center; gap: .5rem; color: var(--muted); font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; }
.select-label select {
  min-width: 9rem;
  padding: .4rem .55rem;
  border-radius: .45rem;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--text);
  font: inherit;
  font-size: .85rem;
  text-transform: none;
  letter-spacing: 0;
}
.view-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: .45rem; overflow: hidden; }
.view-toggle button {
  padding: .4rem .8rem;
  border: 0;
  background: var(--bg);
  color: var(--muted);
  font: inherit;
  font-size: .8rem;
  font-weight: 600;
  cursor: pointer;
}
.view-toggle button + button { border-left: 1px solid var(--line); }
.view-toggle button.active { background: var(--panel-3); color: var(--text); }
#players-index .col-adv, #players-index .col-p36 { display: none; }
#players-index.show-adv .col-adv { display: table-cell; }
#players-index.show-adv .col-basic, #players-index.show-adv .col-p36 { display: none; }
#players-index.show-p36 .col-p36 { display: table-cell; }
#players-index.show-p36 .col-basic, #players-index.show-p36 .col-adv { display: none; }

/* ---------- scores ---------- */
.score-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: .5rem;
}
.score-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: .6rem;
  padding: .5rem .7rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
  font-variant-numeric: tabular-nums;
}
.score-line:hover { border-color: var(--accent); text-decoration: none; }
.score-match { font-size: .9rem; color: var(--muted); }
.score-match strong { color: var(--text); font-weight: 700; }
.score-match em { font-style: normal; color: var(--muted); font-size: .78rem; }
.score-status { font-size: .7rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.score-status.final { color: var(--accent); }
.day-panel[hidden] { display: none; }

/* ---------- schedule grid ---------- */
.schedule-grid th, .schedule-grid td { text-align: center; }
.schedule-grid td:first-child, .schedule-grid th:first-child { text-align: center; }
.schedule-grid td { padding: .18rem .3rem; }
.day-label { color: var(--muted); font-variant-numeric: tabular-nums; }
.off-day { background: rgba(255,255,255,.015); }
.sched-cell { display: block; padding: .12rem .25rem; border-radius: .3rem; color: var(--text); font-size: .76rem; line-height: 1.25; text-decoration: none; }
.sched-cell:hover { background: var(--panel-3); text-decoration: none; }
.sched-result { display: block; font-size: .68rem; font-variant-numeric: tabular-nums; }
.sched-win .sched-result { color: var(--good); }
.sched-loss .sched-result { color: var(--bad); }

/* ---------- section blocks ---------- */
.block-title {
  margin: 1.1rem 0 .5rem;
  font-size: .95rem;
  font-weight: 700;
  letter-spacing: .02em;
  text-transform: none;
  color: var(--text);
}
th.group-start, td.group-start { border-left: 2px solid rgba(255,255,255,.18); }
td.cur-season, th.cur-season { background: rgba(91,157,255,.07); }
thead th.cur-season { background: rgba(91,157,255,.14); color: var(--text); }
tr.total-row td.cur-season { background: rgba(91,157,255,.12); }

/* ---------- scatter chart ---------- */
.chart-controls { display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; }
.chart-wrap { position: relative; }
.chart-wrap canvas { display: block; width: 100%; height: 460px; border: 1px solid var(--line); border-radius: .5rem; background: #14181d; cursor: crosshair; }
.chart-tooltip {
  position: absolute;
  z-index: 10;
  pointer-events: none;
  padding: .4rem .55rem;
  border: 1px solid var(--line);
  border-radius: .4rem;
  background: rgba(16, 19, 23, .96);
  font-size: .76rem;
  line-height: 1.35;
  white-space: nowrap;
  box-shadow: 0 6px 18px rgba(0,0,0,.4);
}
.chart-tooltip strong { display: block; font-size: .82rem; }
.chart-tooltip span { color: var(--muted); }
.chart-legend { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .5rem; }
.chart-legend button {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  padding: .22rem .55rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel-2);
  color: var(--text);
  font: inherit;
  font-size: .75rem;
  font-weight: 600;
  cursor: pointer;
}
.chart-legend button .dot { width: .55rem; height: .55rem; border-radius: 50%; background: var(--dot, var(--muted)); }
.chart-legend button.off { opacity: .35; }

/* ---------- player page ---------- */
.player-hero {
  display: grid;
  grid-template-columns: 120px minmax(260px, 1fr) minmax(360px, 600px);
  gap: 1rem;
  align-items: start;
}
.portrait-wrap { display: flex; justify-content: center; align-items: flex-start; }
.portrait {
  width: 120px;
  height: 120px;
  border-radius: .6rem;
  object-fit: cover;
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.portrait.placeholder { display: grid; place-items: center; font-size: 2rem; font-weight: 700; color: var(--muted); }
.details-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .35rem .6rem;
  margin-top: .75rem;
}
.detail-item {
  display: flex;
  justify-content: space-between;
  gap: .6rem;
  padding: .3rem .45rem;
  background: var(--panel-2);
  border: 1px solid rgba(255,255,255,.04);
  border-radius: .4rem;
  font-size: .8rem;
}
.detail-item span { color: var(--muted); }
.detail-item strong { text-align: right; font-weight: 600; }
.rating-panel { display: grid; gap: .6rem; }
.rating-topline { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem; }
.big-rating {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: .55rem .7rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
}
.big-rating span { color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .07em; font-size: .7rem; }
.big-rating strong { font-size: 1.4rem; font-weight: 700; }
.full-rating-panel { min-width: min(100%, 480px); }
.rating-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; }
.rating-group {
  padding: .55rem .6rem;
  border: 1px solid rgba(255,255,255,.05);
  border-radius: .5rem;
  background: var(--panel-2);
}
.rating-group h3 {
  margin: 0 0 .3rem;
  padding-bottom: .3rem;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-size: .8rem;
}
.rating-row { display: flex; justify-content: space-between; gap: .6rem; padding: .12rem 0; font-size: .8rem; }
.rating-row span { color: var(--muted); }
.rating-row strong { text-align: right; font-weight: 600; white-space: nowrap; }
.awards-strip { display: flex; flex-wrap: wrap; }
.summary-wrap table { min-width: 700px; }
.home-hero { margin-bottom: .75rem; }
.home-section { margin-bottom: .75rem; }
.award-name strong { display: block; font-size: .9rem; color: var(--text); }
.award-name span { display: block; color: var(--muted); font-size: .72rem; }
.candidate-cell { min-width: 12rem; text-align: left; }
.candidate-card { display: flex; align-items: center; gap: .5rem; min-width: 11rem; text-align: left; }
.candidate-card > div:last-child { display: grid; gap: .05rem; }
.candidate-card span { color: var(--muted); font-size: .72rem; }
.candidate-img {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  border-radius: .4rem;
  object-fit: cover;
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.candidate-img.placeholder { display: grid; place-items: center; color: var(--muted); font-weight: 700; font-size: .68rem; }

/* ---------- team page ---------- */
.team-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; }
.team-hero::before { background: linear-gradient(180deg, var(--team-primary, var(--accent)), var(--team-secondary, var(--accent))); }
.page-hero { position: relative; overflow: hidden; }
.page-hero::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: .25rem;
  background: var(--accent);
}
.salary-summary {
  width: min(100%, 20rem);
  padding: .55rem .7rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
}
.salary-copy { display: flex; justify-content: space-between; gap: .6rem; margin-bottom: .35rem; font-size: .8rem; }
.salary-copy span { color: var(--muted); font-weight: 500; }
.salary-copy strong { color: var(--text); }
.salary-bar { height: .45rem; border-radius: 999px; overflow: hidden; background: var(--bg); border: 1px solid rgba(255,255,255,.07); }
.salary-bar span { display: block; height: 100%; background: var(--accent); }
.salary-summary.over .salary-copy strong { color: var(--bad); }

/* ---------- game pages ---------- */
.click-row { cursor: pointer; }
.button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: .4rem .65rem;
  border: 1px solid var(--line);
  border-radius: .45rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
  font-weight: 600;
  font-size: .82rem;
}
.button-link:hover { text-decoration: none; border-color: var(--accent); }
.button-link.disabled { opacity: .45; pointer-events: none; }
.box-score-hero {
  display: grid;
  grid-template-columns: auto minmax(0, 48rem) auto;
  align-items: center;
  justify-content: center;
  gap: .75rem;
  margin-bottom: .75rem;
}
.scoreboard-core { text-align: center; }
.scoreboard-core h1 {
  font-size: 1.1rem;
  display: flex;
  justify-content: center;
  align-items: baseline;
  gap: .4rem;
  flex-wrap: wrap;
}
.scoreboard-core h1 span { color: var(--text); font-weight: 700; }
.scoreboard-core h1 em { color: var(--muted); font-style: normal; font-size: .82rem; }
.scoreboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; margin-top: .55rem; }
.mini-score-table.table-wrap { border-radius: .45rem; }
.mini-score-table table { min-width: 0; width: 100%; }
.mini-score-table th, .mini-score-table td { padding: .26rem .4rem; font-size: .76rem; }
.mini-score-table thead th { cursor: default; }
.score-team { color: var(--text); font-weight: 700; }
.final-score { font-weight: 700; }
.series-note { margin: .4rem 0 0; color: var(--accent); font-weight: 600; }
.scheduled-note { color: var(--muted); margin: .5rem 0 0; font-size: .85rem; }
.box-team-section { margin-bottom: .9rem; }
.box-team-section h2 { margin: 0 0 .4rem; font-size: .95rem; text-transform: none; letter-spacing: 0; color: var(--text); }
.box-score-table { min-width: 1080px; }
.bench-start td { border-top: 2px solid rgba(255,255,255,.25); }
.total-row td, .pct-row td { font-weight: 700; background: var(--panel-2); }
.total-label { color: var(--text); }
.pct-row td { border-bottom: 0; }

@media (max-width: 900px) {
  .site-header { flex-direction: column; align-items: flex-start; }
  .nav-search { flex: none; width: 100%; }
  .player-hero { grid-template-columns: 1fr; }
  .portrait-wrap { justify-content: flex-start; }
  .details-grid { grid-template-columns: 1fr; }
  .rating-groups { grid-template-columns: 1fr; }
  .rating-topline { grid-template-columns: 1fr; }
  .team-hero { display: block; }
  .salary-summary { margin-top: .75rem; }
  .team-dropdown { width: 100%; }
  .team-menu { position: static; width: 100%; max-height: 14rem; margin-top: .3rem; box-shadow: none; }
  .box-score-hero { grid-template-columns: 1fr; text-align: left; }
  .scoreboard-core { text-align: left; }
  .scoreboard-core h1 { justify-content: flex-start; }
  .scoreboard-grid { grid-template-columns: 1fr; }
  th, td { padding: .3rem .45rem; }
}

/* ---------- home dashboard ---------- */
.home-columns { display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 3fr); gap: .75rem; align-items: start; }
.home-main, .home-side { min-width: 0; }
@media (max-width: 1150px) { .home-columns { grid-template-columns: 1fr; } }
.badge {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  padding: .08rem .42rem;
  border-radius: .3rem;
  font-size: .62rem;
  font-weight: 700;
  letter-spacing: .05em;
  margin-right: .5rem;
  white-space: nowrap;
}
.badge-bad { background: rgba(226,86,107,.16); color: var(--bad); }
.badge-good { background: rgba(63,191,114,.16); color: var(--good); }
.badge-accent { background: rgba(91,157,255,.16); color: var(--accent); }
.badge-muted { background: rgba(147,162,173,.16); color: var(--muted); }
.news-list { list-style: none; margin: 0; padding: 0; }
.news-list li {
  display: flex;
  align-items: baseline;
  gap: .1rem;
  padding: .42rem .1rem;
  border-bottom: 1px solid rgba(255,255,255,.05);
  font-size: .8rem;
  line-height: 1.4;
}
.news-list li:last-child { border-bottom: 0; }
.leader-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .6rem; }
.leader-box { padding: .5rem .6rem; border: 1px solid rgba(255,255,255,.05); border-radius: .5rem; background: var(--panel-2); }
.leader-box h3 { margin: 0 0 .35rem; font-size: .7rem; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.leader-list { list-style: none; margin: 0; padding: 0; }
.leader-list li { display: flex; align-items: center; gap: .4rem; padding: .16rem 0; font-size: .8rem; }
.leader-rank { color: var(--muted); min-width: .9rem; text-align: right; font-variant-numeric: tabular-nums; }
.leader-team { color: var(--muted); font-size: .7rem; }
.leader-value { margin-left: auto; font-weight: 600; font-variant-numeric: tabular-nums; }
.team-dot { display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin-right: .4rem; vertical-align: baseline; }
.group-head { text-align: center !important; border-left: 1px solid var(--line); }
#four-factors th, #four-factors td { text-align: right; }
#four-factors th:first-child, #four-factors td:first-child { text-align: left; }
#four-factors td:nth-child(7), #four-factors th:nth-child(7) { border-left: 1px solid var(--line); }
#four-factors td:nth-child(11), #four-factors th:nth-child(11) { border-left: 1px solid var(--line); }

/* ---------- finances ---------- */
.fit-table { width: max-content; max-width: 100%; }
.fit-table table { width: auto; }
.capcell { min-width: 6.5rem; }
.capbar { display: inline-block; width: 3rem; height: .4rem; margin-right: .45rem; border-radius: 999px; background: rgba(255,255,255,.07); overflow: hidden; vertical-align: middle; }
.capbar i { display: block; height: 100%; background: var(--accent); }
.salary-bar { position: relative; }
.floor-mark { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--muted); opacity: .8; }
.salary-note { margin: .35rem 0 0; font-size: .74rem; }

/* ---------- schedule extras ---------- */
tr.next-day > td { background: rgba(91,157,255,.10); }
tr.next-day > td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
.col-hl { background: rgba(255,255,255,.05); }
.h2h-grid th, .h2h-grid td { text-align: center; }
.h2h-grid th:first-child, .h2h-grid td:first-child { text-align: left; }
.h2h-self { background: rgba(255,255,255,.03); }

/* ---------- team page ---------- */
.vitals-row { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .6rem; }
.vital-tile {
  display: grid;
  gap: .05rem;
  padding: .4rem .65rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
}
.vital-tile span { color: var(--muted); font-size: .66rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
.vital-tile strong { font-size: .92rem; }
.game-strip { display: flex; flex-wrap: wrap; gap: .45rem; }
.game-chip {
  display: grid;
  gap: .05rem;
  min-width: 6.2rem;
  padding: .4rem .6rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
  font-size: .76rem;
}
.game-chip:hover { border-color: var(--accent); text-decoration: none; }
.game-chip span { color: var(--muted); font-size: .68rem; }
.chip-win strong { color: var(--good); }
.chip-loss strong { color: var(--bad); }
.chip-next strong { color: var(--text); }
.depth-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .6rem; }
@media (max-width: 900px) { .depth-grid { grid-template-columns: repeat(2, 1fr); } }
.depth-col { padding: .5rem .6rem; border: 1px solid rgba(255,255,255,.05); border-radius: .5rem; background: var(--panel-2); }
.depth-col h3 { margin: 0 0 .35rem; font-size: .7rem; font-weight: 700; letter-spacing: .07em; color: var(--muted); }
.pick-row { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .4rem; }
.pick-chip {
  display: inline-flex;
  align-items: center;
  gap: .3rem;
  padding: .26rem .55rem;
  border-radius: .4rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  font-size: .78rem;
  font-weight: 600;
}
.pick-own { border-left: 3px solid var(--accent); }
.pick-acquired { border-left: 3px solid var(--good); }

/* ---------- game pages ---------- */
.series-row { display: flex; flex-wrap: wrap; gap: .45rem; }
.series-chip {
  padding: .35rem .6rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
  color: var(--text);
  font-size: .78rem;
  text-decoration: none;
  font-variant-numeric: tabular-nums;
}
.series-chip:hover { border-color: var(--accent); text-decoration: none; }
.series-chip.current { border-color: var(--accent); }
.cmp-table th, .cmp-table td { text-align: center; min-width: 7rem; }
.cmp-table .cmp-label { color: var(--muted); font-size: .7rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
.preview-injuries { margin-top: .6rem; }
.preview-injuries h3 { margin: 0 0 .25rem; letter-spacing: .07em; }
.preview-injuries p { margin: .15rem 0; }

/* ---------- dev chart ---------- */
.dev-chart { width: 100%; max-width: 680px; height: auto; display: block; }
.chart-grid { stroke: rgba(255,255,255,.07); stroke-width: 1; }
.chart-tick { fill: var(--muted); font-size: 10px; }
.line-ovr { fill: none; stroke: var(--accent); stroke-width: 2; }
.line-ovr-dot { fill: var(--accent); }
.line-pot { fill: none; stroke: var(--muted); stroke-width: 1.6; stroke-dasharray: 4 3; }
.line-pot-dot { fill: var(--muted); }
.chart-key { display: inline-block; width: .8rem; height: 2px; vertical-align: middle; margin-right: .25rem; }
.chart-key-ovr { background: var(--accent); height: 3px; }
.chart-key-pot { background: var(--muted); }

/* ---------- history ---------- */
.bracket { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; margin-bottom: .6rem; }
.bracket-round h4 { margin: 0 0 .3rem; font-size: .68rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.bracket-series {
  min-width: 11rem;
  margin-bottom: .45rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
  overflow: hidden;
}
.bracket-series > div { display: flex; justify-content: space-between; gap: .8rem; padding: .32rem .6rem; font-size: .8rem; }
.bracket-win { background: rgba(63,191,114,.08); font-weight: 600; }
.bracket-loss { color: var(--muted); }
.leaders-inline { display: flex; flex-wrap: wrap; gap: .4rem 1.1rem; margin-bottom: .6rem; }
.leader-inline { font-size: .78rem; color: var(--muted); }
.leader-inline strong { color: var(--text); margin-right: .25rem; }
.history-awards { margin-top: .35rem; }

/* ---------- global search ---------- */
.nav-search { position: relative; flex: 0 1 16rem; min-width: 9rem; }
.nav-search input {
  width: 100%;
  padding: .34rem .6rem;
  border-radius: .45rem;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--text);
  font: inherit;
  font-size: .82rem;
  outline: none;
}
.nav-search input:focus { border-color: var(--accent); }
.search-results {
  position: absolute;
  top: calc(100% + .3rem);
  left: 0;
  right: 0;
  z-index: 50;
  max-height: 20rem;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel);
  box-shadow: 0 10px 30px rgba(0,0,0,.45);
}
.search-results a {
  display: flex;
  justify-content: space-between;
  gap: .6rem;
  padding: .42rem .6rem;
  color: var(--text);
  font-size: .82rem;
  text-decoration: none;
}
.search-results a .muted { font-size: .72rem; }
.search-results a:hover, .search-results a.selected { background: var(--panel-2); text-decoration: none; }
.search-empty { padding: .45rem .6rem; color: var(--muted); font-size: .78rem; }

/* ---------- favorite team ---------- */
.fav-star {
  margin-right: .4rem;
  padding: 0 .2rem;
  border: 0;
  background: none;
  color: var(--muted);
  font: inherit;
  font-size: 1.1rem;
  cursor: pointer;
  vertical-align: baseline;
}
.fav-star.active { color: #f2c14e; }
.fav-star:hover { color: #f2c14e; }
.fav-pin::before { content: "★ "; color: #f2c14e; }
tr.fav-row > td { background: rgba(242,193,78,.07); }
tr.fav-row > td:first-child { box-shadow: inset 2px 0 0 #f2c14e; }
th.fav-row { color: #f2c14e !important; }

/* ---------- round 3 ---------- */
.rank-move { display: inline-block; min-width: 1.6rem; font-size: .68rem; font-variant-numeric: tabular-nums; }
.rank-flat { color: var(--muted); opacity: .5; }
.l10-dots { display: inline-flex; gap: 2px; align-items: center; }
.l10-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.l10-w { background: var(--good); }
.l10-l { background: var(--bad); opacity: .7; }
.high-row { display: flex; flex-wrap: wrap; gap: .45rem; }
.high-chip {
  display: inline-flex;
  align-items: baseline;
  gap: .4rem;
  padding: .3rem .6rem;
  border: 1px solid var(--line);
  border-radius: .45rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
}
.high-chip:hover { border-color: var(--accent); text-decoration: none; }
.high-chip span { color: var(--muted); font-size: .68rem; font-weight: 600; letter-spacing: .06em; }
.high-chip strong { font-size: 1rem; }
.history-row { display: flex; flex-wrap: wrap; gap: .75rem; align-items: flex-start; }
.history-row .card { flex: 0 1 auto; }
.qtr-table th, .qtr-table td { text-align: right; min-width: 3.2rem; }
.qtr-table th:first-child, .qtr-table td:first-child { text-align: left; }
.profile-row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start; }
tr.dead-row > td { opacity: .65; }
.dead-money { font-style: italic; }
.honors { margin-top: .6rem; display: grid; gap: .3rem; }
.honor-row { display: flex; gap: .6rem; font-size: .8rem; align-items: baseline; }
.honor-label { flex: 0 0 9.5rem; color: var(--muted); font-size: .68rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.tx-season { border: 1px solid var(--line); border-radius: .5rem; background: var(--panel-2); padding: .45rem .7rem; margin-bottom: .5rem; }
.tx-season summary { cursor: pointer; font-weight: 600; font-size: .85rem; display: flex; align-items: center; gap: .5rem; }
.tx-season[open] summary { margin-bottom: .35rem; }
.potg { margin: .5rem 0 0; font-size: .82rem; }

/* trade machine */
.trade-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
@media (max-width: 900px) { .trade-grid { grid-template-columns: 1fr; } }
.trade-side .select-label { margin-bottom: .45rem; }
.trade-list {
  max-height: 22rem;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
}
.trade-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1.3fr) minmax(0, 1fr) auto auto;
  gap: .5rem;
  align-items: center;
  padding: .32rem .55rem;
  border-bottom: 1px solid rgba(255,255,255,.05);
  font-size: .8rem;
  cursor: pointer;
}
.trade-row:hover { background: var(--panel-3); }
.trade-row .muted { font-size: .72rem; }
.trade-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.trade-amt { font-variant-numeric: tabular-nums; color: var(--muted); }
.trade-val { font-variant-numeric: tabular-nums; font-weight: 600; min-width: 2.2rem; text-align: right; }
.trade-pick .trade-name { color: var(--accent); }
.trade-summary {
  margin-top: .7rem;
  padding: .6rem .75rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--panel-2);
  font-size: .84rem;
}
.trade-summary p { margin: .25rem 0; }
.trade-verdict { font-weight: 700; color: var(--accent); }
.offer-cell { max-width: 32rem; white-space: normal; }

/* compare */
.compare-toolbar { flex-wrap: wrap; justify-content: flex-start; gap: 1rem; }
.cmp-players th { text-align: left; min-width: 11rem; }
.cmp-players th .muted { display: block; font-weight: 500; text-transform: none; letter-spacing: 0; }
.cmp-players td { text-align: left; }
.cmp-players .cmp-label { color: var(--muted); font-size: .72rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; }
.cmp-best { color: var(--good); font-weight: 700; }
.cmp-bar { display: inline-block; width: 4.5rem; height: .4rem; margin-right: .5rem; border-radius: 999px; background: rgba(255,255,255,.07); overflow: hidden; vertical-align: middle; }
.cmp-bar i { display: block; height: 100%; background: var(--accent); }
.cmp-best .cmp-bar i { background: var(--good); }

@media (max-width: 900px) {
  .nav-search { flex: none; width: 100%; }
  .home-columns { grid-template-columns: 1fr; }
}

""".strip() + "\n"


def javascript() -> str:
    return r"""
(function () {
  function cellValue(row, index) {
    const cell = row.children[index];
    if (!cell) return "";
    return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
  }

  function compareValues(a, b) {
    const na = Number(a);
    const nb = Number(b);
    const aNumeric = a !== "" && Number.isFinite(na);
    const bNumeric = b !== "" && Number.isFinite(nb);
    if (aNumeric && bNumeric) return na - nb;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = table.querySelectorAll("thead th");
    headers.forEach((header, index) => {
      header.addEventListener("click", () => {
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.rows);
        const descending = header.classList.contains("sort-asc");
        headers.forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
        header.classList.add(descending ? "sort-desc" : "sort-asc");
        rows.sort((ra, rb) => {
          const result = compareValues(cellValue(ra, index), cellValue(rb, index));
          return descending ? -result : result;
        });
        rows.forEach((row) => tbody.appendChild(row));
      });
    });
  });

  document.querySelectorAll("[data-table-filter]").forEach((input) => {
    const table = document.getElementById(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", () => {
      const needle = input.value.trim().toLowerCase();
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
      });
    });
  });
  document.querySelectorAll('[data-schedule-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.scheduleFilter);
    if (!table) return;
    const apply = () => {
      const value = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = value !== 'all' && row.dataset.scheduleTeam !== value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('[data-day-select]').forEach((select) => {
    const panels = Array.from(document.querySelectorAll('[data-day-panel]'));
    const apply = () => {
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.dayPanel !== select.value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('.click-row[data-href]').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.closest && target.closest('a')) return;
      window.location.href = row.dataset.href;
    });
  });

  document.querySelectorAll('[data-view-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.viewToggle);
    if (!table) return;
    wrap.querySelectorAll('button').forEach((button) => {
      button.addEventListener('click', () => {
        wrap.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
        button.classList.add('active');
        table.classList.remove('show-adv', 'show-p36');
        if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      });
    });
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('details.team-dropdown[open]').forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute('open');
    });
  });

  // ---------- player scatter chart ----------
  const chartCanvas = document.querySelector('[data-player-chart]');
  const chartDataEl = document.getElementById('player-chart-data');
  if (chartCanvas && chartDataEl) {
    const data = JSON.parse(chartDataEl.textContent);
    const labels = {};
    data.metrics.forEach((m) => { labels[m.key] = m.label; });
    const colors = {};
    data.teams.forEach((t) => { colors[t.abbrev] = t.color; });
    const hidden = new Set();
    const tooltip = document.querySelector('[data-chart-tooltip]');
    const legend = document.querySelector('[data-chart-legend]');
    const selX = document.querySelector('[data-chart-axis=\"x\"]');
    const selY = document.querySelector('[data-chart-axis=\"y\"]');
    const selPos = document.querySelector('[data-chart-pos]');
    const minMinInput = document.querySelector('[data-chart-minmin]');
    const labelsInput = document.querySelector('[data-chart-labels]');
    let xKey = data.defaultX;
    let yKey = data.defaultY;
    let drawn = [];

    // restore state from URL hash: #x=usg&y=ts&pos=G&min=20&labels=1
    const hashParams = new URLSearchParams((location.hash || '').replace(/^#/, ''));
    const validKeys = new Set(data.metrics.map((m) => m.key));
    if (validKeys.has(hashParams.get('x'))) xKey = hashParams.get('x');
    if (validKeys.has(hashParams.get('y'))) yKey = hashParams.get('y');
    if (selX) selX.value = xKey;
    if (selY) selY.value = yKey;
    if (selPos && ['G', 'F', 'C'].includes(hashParams.get('pos'))) selPos.value = hashParams.get('pos');
    if (minMinInput && hashParams.get('min')) minMinInput.value = hashParams.get('min');
    if (labelsInput && hashParams.get('labels') === '1') labelsInput.checked = true;

    function syncHash() {
      const params = new URLSearchParams();
      params.set('x', xKey);
      params.set('y', yKey);
      if (selPos && selPos.value !== 'all') params.set('pos', selPos.value);
      if (minMinInput && Number(minMinInput.value) > 0) params.set('min', minMinInput.value);
      if (labelsInput && labelsInput.checked) params.set('labels', '1');
      history.replaceState(null, '', '#' + params.toString());
    }

    data.teams.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.setProperty('--dot', t.color);
      btn.innerHTML = '<span class=\"dot\"></span>' + t.abbrev;
      btn.addEventListener('click', () => {
        if (hidden.has(t.abbrev)) hidden.delete(t.abbrev); else hidden.add(t.abbrev);
        btn.classList.toggle('off', hidden.has(t.abbrev));
        draw();
      });
      legend.appendChild(btn);
    });

    function niceTicks(lo, hi, count) {
      const span = hi - lo || 1;
      const step0 = span / Math.max(1, count);
      const mag = Math.pow(10, Math.floor(Math.log10(step0)));
      const norm = step0 / mag;
      const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
      const ticks = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
      return { ticks, step };
    }

    function fmtTick(value, step) {
      const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
      return value.toFixed(digits);
    }

    function draw() {
      if (tooltip) tooltip.hidden = true;
      const dpr = window.devicePixelRatio || 1;
      const cw = chartCanvas.clientWidth;
      const ch = chartCanvas.clientHeight;
      chartCanvas.width = cw * dpr;
      chartCanvas.height = ch * dpr;
      const ctx = chartCanvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';

      const posFilter = selPos ? selPos.value : 'all';
      const minMin = minMinInput ? Number(minMinInput.value) || 0 : 0;
      const pts = data.players.filter((p) =>
        !hidden.has(p.team)
        && Number.isFinite(p.v[xKey]) && Number.isFinite(p.v[yKey])
        && (posFilter === 'all' || (p.pos || '').includes(posFilter))
        && (!minMin || (Number.isFinite(p.v.min) && p.v.min >= minMin)));
      drawn = [];
      if (!pts.length) {
        ctx.fillStyle = '#939ca7';
        ctx.fillText('No data for this combination.', 16, 24);
        return;
      }
      let xLo = Math.min(...pts.map((p) => p.v[xKey]));
      let xHi = Math.max(...pts.map((p) => p.v[xKey]));
      let yLo = Math.min(...pts.map((p) => p.v[yKey]));
      let yHi = Math.max(...pts.map((p) => p.v[yKey]));
      const xPad = (xHi - xLo || 1) * 0.06;
      const yPad = (yHi - yLo || 1) * 0.08;
      xLo -= xPad; xHi += xPad; yLo -= yPad; yHi += yPad;

      const m = { left: 48, right: 14, top: 12, bottom: 34 };
      const plotW = cw - m.left - m.right;
      const plotH = ch - m.top - m.bottom;
      const px = (v) => m.left + ((v - xLo) / (xHi - xLo)) * plotW;
      const py = (v) => m.top + plotH - ((v - yLo) / (yHi - yLo)) * plotH;

      const xt = niceTicks(xLo, xHi, 8);
      const yt = niceTicks(yLo, yHi, 6);
      ctx.strokeStyle = 'rgba(255,255,255,.06)';
      ctx.fillStyle = '#939ca7';
      ctx.lineWidth = 1;
      xt.ticks.forEach((v) => {
        const x = px(v);
        ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke();
        ctx.textAlign = 'center';
        ctx.fillText(fmtTick(v, xt.step), x, m.top + plotH + 16);
      });
      yt.ticks.forEach((v) => {
        const y = py(v);
        ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke();
        ctx.textAlign = 'right';
        ctx.fillText(fmtTick(v, yt.step), m.left - 7, y + 3.5);
      });
      // zero lines
      ctx.strokeStyle = 'rgba(255,255,255,.22)';
      if (xLo < 0 && xHi > 0) { const x = px(0); ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke(); }
      if (yLo < 0 && yHi > 0) { const y = py(0); ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke(); }
      // axis labels
      ctx.fillStyle = '#c6cdd5';
      ctx.textAlign = 'center';
      ctx.fillText(labels[xKey] || xKey, m.left + plotW / 2, ch - 6);
      ctx.save();
      ctx.translate(12, m.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(labels[yKey] || yKey, 0, 0);
      ctx.restore();

      pts.forEach((p) => {
        const x = px(p.v[xKey]);
        const y = py(p.v[yKey]);
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.team] || '#939ca7';
        ctx.globalAlpha = 0.9;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = 'rgba(0,0,0,.5)';
        ctx.stroke();
        drawn.push({ x, y, p });
      });

      // optionally label the most extreme points on the current axes
      if (labelsInput && labelsInput.checked && pts.length) {
        const meanX = pts.reduce((s, p) => s + p.v[xKey], 0) / pts.length;
        const meanY = pts.reduce((s, p) => s + p.v[yKey], 0) / pts.length;
        const sdX = Math.sqrt(pts.reduce((s, p) => s + (p.v[xKey] - meanX) ** 2, 0) / pts.length) || 1;
        const sdY = Math.sqrt(pts.reduce((s, p) => s + (p.v[yKey] - meanY) ** 2, 0) / pts.length) || 1;
        const ranked = pts.slice().sort((a, b) =>
          (Math.abs((b.v[xKey] - meanX) / sdX) + Math.abs((b.v[yKey] - meanY) / sdY))
          - (Math.abs((a.v[xKey] - meanX) / sdX) + Math.abs((a.v[yKey] - meanY) / sdY)));
        ctx.fillStyle = '#c6cdd5';
        ctx.textAlign = 'left';
        ranked.slice(0, Math.min(14, ranked.length)).forEach((p) => {
          const lx = px(p.v[xKey]) + 7;
          const ly = py(p.v[yKey]) + 3;
          ctx.fillText(p.name.split(' ').slice(-1)[0], lx, ly);
        });
      }
    }

    function nearest(event) {
      const rect = chartCanvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      let best = null;
      let bestDist = 144;
      drawn.forEach((d) => {
        const dist = (d.x - mx) * (d.x - mx) + (d.y - my) * (d.y - my);
        if (dist < bestDist) { bestDist = dist; best = d; }
      });
      return best;
    }

    chartCanvas.addEventListener('mousemove', (event) => {
      const hit = nearest(event);
      if (!hit) { tooltip.hidden = true; chartCanvas.style.cursor = 'crosshair'; return; }
      chartCanvas.style.cursor = 'pointer';
      tooltip.innerHTML = '<strong>' + hit.p.name + ' · ' + hit.p.team + '</strong>'
        + '<span>' + (labels[xKey] || xKey) + ': ' + hit.p.v[xKey] + ' · '
        + (labels[yKey] || yKey) + ': ' + hit.p.v[yKey] + '</span>';
      tooltip.hidden = false;
      const wrapRect = chartCanvas.parentElement.getBoundingClientRect();
      const rect = chartCanvas.getBoundingClientRect();
      let left = hit.x + (rect.left - wrapRect.left) + 12;
      let top = hit.y + (rect.top - wrapRect.top) - 12;
      if (left + tooltip.offsetWidth > wrapRect.width - 4) left = left - tooltip.offsetWidth - 24;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    });
    chartCanvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });
    chartCanvas.addEventListener('click', (event) => {
      const hit = nearest(event);
      if (hit && hit.p.url) window.location.href = hit.p.url;
    });
    if (selX) selX.addEventListener('change', () => { xKey = selX.value; syncHash(); draw(); });
    if (selY) selY.addEventListener('change', () => { yKey = selY.value; syncHash(); draw(); });
    if (selPos) selPos.addEventListener('change', () => { syncHash(); draw(); });
    if (minMinInput) minMinInput.addEventListener('input', () => { syncHash(); draw(); });
    if (labelsInput) labelsInput.addEventListener('change', () => { syncHash(); draw(); });
    window.addEventListener('resize', draw);
    draw();
  }


  // ---------- schedule/h2h column hover ----------
  document.querySelectorAll('.schedule-grid, .h2h-grid').forEach((table) => {
    table.addEventListener('mouseover', (event) => {
      const cell = event.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      const idx = cell.cellIndex;
      if (idx > 0) {
        table.querySelectorAll('tr').forEach((tr) => {
          const target = tr.cells[idx];
          if (target) target.classList.add('col-hl');
        });
      }
    });
    table.addEventListener('mouseleave', () => {
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
    });
  });

  // ---------- global search ----------
  const searchInput = document.querySelector('[data-global-search]');
  const searchResults = document.querySelector('[data-search-results]');
  if (searchInput && searchResults) {
    const root = document.body.dataset.root || '';
    let index = null;
    let selected = -1;
    const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    function load() {
      if (index) return Promise.resolve(index);
      return fetch(root + 'assets/search-index.json')
        .then((r) => r.json())
        .then((data) => { index = data; return index; })
        .catch(() => ({ players: [], teams: [] }));
    }

    function close() { searchResults.hidden = true; selected = -1; }

    function renderResults(matches) {
      if (!matches.length) {
        searchResults.innerHTML = '<div class="search-empty">No matches.</div>';
        searchResults.hidden = false;
        return;
      }
      searchResults.innerHTML = matches.map((m) =>
        '<a href="' + root + m.u + '"><span>' + m.n + '</span><span class="muted">' + m.t + '</span></a>').join('');
      searchResults.hidden = false;
      selected = -1;
    }

    function update() {
      const q = norm(searchInput.value.trim());
      if (q.length < 2) { close(); return; }
      load().then((data) => {
        const score = (name) => {
          const n = norm(name);
          if (n.startsWith(q)) return 0;
          if (n.split(' ').some((w) => w.startsWith(q))) return 1;
          if (n.includes(q)) return 2;
          return -1;
        };
        const matches = [];
        (data.teams || []).forEach((t) => { const s = score(t.n); if (s >= 0) matches.push({ ...t, s: s - 0.5 }); });
        (data.players || []).forEach((p) => { const s = score(p.n); if (s >= 0) matches.push({ ...p, s }); });
        matches.sort((a, b) => a.s - b.s || a.n.localeCompare(b.n));
        renderResults(matches.slice(0, 8));
      });
    }

    searchInput.addEventListener('input', update);
    searchInput.addEventListener('focus', () => { load(); if (searchInput.value.trim().length >= 2) update(); });
    searchInput.addEventListener('keydown', (event) => {
      const links = Array.from(searchResults.querySelectorAll('a'));
      if (event.key === 'Escape') { close(); searchInput.blur(); return; }
      if (!links.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, links.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = links[Math.max(0, selected)];
        if (target) window.location.href = target.href;
        return;
      } else { return; }
      links.forEach((l, i) => l.classList.toggle('selected', i === selected));
    });
    document.addEventListener('click', (event) => {
      if (!searchInput.contains(event.target) && !searchResults.contains(event.target)) close();
    });
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

  // ---------- favorite team ----------
  const FAV_KEY = 'smp-fav-tid';
  const favTid = localStorage.getItem(FAV_KEY);
  document.querySelectorAll('[data-fav-team]').forEach((btn) => {
    const tid = btn.dataset.favTeam;
    const sync = () => btn.classList.toggle('active', localStorage.getItem(FAV_KEY) === tid);
    sync();
    btn.addEventListener('click', () => {
      const current = localStorage.getItem(FAV_KEY);
      if (current === tid) localStorage.removeItem(FAV_KEY);
      else localStorage.setItem(FAV_KEY, tid);
      sync();
      applyFavorite();
    });
  });

  function applyFavorite() {
    const fav = localStorage.getItem(FAV_KEY);
    document.querySelectorAll('.fav-row').forEach((el) => el.classList.remove('fav-row'));
    document.querySelectorAll('.fav-pin').forEach((el) => el.remove());
    if (!fav) return;
    document.querySelectorAll('tr[data-tid="' + fav + '"], th[data-tid="' + fav + '"]').forEach((el) => el.classList.add('fav-row'));
    const menuLink = document.querySelector('.team-menu a[data-tid="' + fav + '"]');
    const nav = document.querySelector('.primary-nav');
    if (menuLink && nav) {
      const pin = document.createElement('a');
      pin.href = menuLink.href;
      pin.textContent = menuLink.dataset.abbrev || menuLink.textContent;
      pin.className = 'fav-pin' + (menuLink.classList.contains('active') ? ' active' : '');
      nav.insertBefore(pin, nav.firstElementChild);
    }
  }
  applyFavorite();

})();
""".strip() + "\n"


def previous_day_json(json_path: Path) -> Path | None:
    """Find the closest earlier day*.json next to the given export."""
    match = re.fullmatch(r"day(\d+)", json_path.stem)
    if not match:
        return None
    day = int(match.group(1))
    for prev_day in range(day - 1, max(-1, day - 15), -1):
        candidate = json_path.with_name(f"day{prev_day}.json")
        if candidate.exists():
            return candidate
    return None


def generate_site(
    json_path: Path,
    out_dir: Path,
    start_season: int = 2026,
    clean: bool = False,
    schedule_season: int | None = None,
    schedule_days: int | None = None,
    prev_json_path: Path | None = None,
) -> dict[str, int | str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    season = current_season(data)
    teams = sorted(data.get("teams", []), key=team_sort_key)
    players = active_players(data)
    fa_players = free_agents(data)
    cap = get_salary_cap(data)
    ga = data.get("gameAttributes") or {}
    ALL_PLAYERS_BY_PID.clear()
    ALL_PLAYERS_BY_PID.update({safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None})
    if prev_json_path is None:
        prev_json_path = previous_day_json(json_path)
    if prev_json_path and prev_json_path.exists():
        try:
            prev_data = json.loads(prev_json_path.read_text(encoding="utf-8"))
            prev_season = current_season(prev_data)
            prev_teams = sorted(prev_data.get("teams", []), key=team_sort_key)
            order = standings_order(active_teams_for_season(prev_teams, prev_season), prev_season)
            SITE_META["prev_ranks"] = {tid: rank for rank, tid in enumerate(order, 1)}
        except Exception:
            SITE_META["prev_ranks"] = None
    else:
        SITE_META["prev_ranks"] = None
    SITE_META["season"] = season
    SITE_META["day"] = max((safe_int(g.get("day")) for g in data.get("games", []) if g.get("season") == season), default=0)
    SITE_META["cap"] = cap
    SITE_META["min_payroll"] = safe_float(get_attr_value(ga.get("minPayroll"), season), 0.0) or None
    game_items, score_label = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    schedule_items, schedule_label = schedule_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)

    if clean and out_dir.exists():
        if out_dir.resolve() in {Path("/").resolve(), Path.cwd().resolve()}:
            raise RuntimeError(f"Refusing to clean unsafe output directory: {out_dir}")
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(out_dir / "assets" / "styles.css", stylesheet())
    write_text(out_dir / "assets" / "site.js", javascript())

    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    search_index = {
        "teams": [
            {"n": team_full_name(t), "t": team_abbrev(t), "u": team_url(t)}
            for t in teams
        ],
        "players": [
            {
                "n": player_name(p),
                "t": team_abbrev_for_tid(p.get("tid"), teams_by_tid) if safe_int(p.get("tid"), -1) >= 0 else "FA",
                "u": player_url(p),
            }
            for p in sorted(players, key=player_name)
        ] + [
            {"n": player_name(p), "t": "Draft", "u": player_url(p)}
            for p in sorted(draft_prospects(data), key=player_name)
        ],
    }
    write_text(out_dir / "assets" / "search-index.json", json.dumps(search_index, separators=(",", ":")))

    write_text(out_dir / "index.html", render_home_page(data, teams, players, season, start_season))
    write_text(out_dir / "schedule.html", render_schedule_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days))
    write_text(out_dir / "free-agency.html", render_free_agency_page(fa_players, teams, season, start_season))
    write_text(out_dir / "players" / "index.html", render_players_index(players, teams, season, start_season))
    write_text(out_dir / "history.html", render_history_page(data, teams))
    write_text(out_dir / "records.html", render_records_page(data, teams, season))
    write_text(out_dir / "draft.html", render_draft_page(data, teams, season))
    write_text(out_dir / "trade.html", render_trade_page(data, teams, players, season, cap))
    write_text(out_dir / "compare.html", render_compare_page(data, teams, players, season, start_season))

    for team in teams:
        roster = [player for player in players if player.get("tid") == team.get("tid")]
        write_text(out_dir / "teams" / f"{team_slug(team)}.html", render_team_page(team, roster, teams, season, start_season, cap, data=data, game_items=game_items))

    prospects = draft_prospects(data)
    for prospect in prospects:
        write_text(out_dir / "players" / f"{player_slug(prospect)}.html", render_player_page(prospect, teams, season, start_season))

    game_logs = build_game_logs(data, season)
    for player in players:
        write_text(
            out_dir / "players" / f"{player_slug(player)}.html",
            render_player_page(player, teams, season, start_season, log_entries=game_logs.get(safe_int(player.get("pid"), -1))),
        )

    for item in game_items:
        write_text(out_dir / "games" / f"{game_slug_from_gid(item.get('gid'))}.html", render_game_page(item, game_items, teams, players, safe_int(item.get("season"), season)))

    completed_scores = [item for item in game_items if is_completed_game_item(item)]
    return {
        "season": season,
        "teams": len(teams),
        "players": len(players),
        "free_agents": len(fa_players),
        "team_pages": len(teams),
        "player_pages": len(players),
        "schedule_games": len(schedule_items),
        "score_games": len(game_items),
        "completed_scores": len(completed_scores),
        "game_pages": len(game_items),
        "schedule_label": schedule_label,
        "score_label": score_label,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static HTML basketball league site from a JSON export.")
    parser.add_argument("json_file", type=Path, nargs="?", default=None, help="Path to the Basketball GM-style JSON file. Defaults to the newest day*.json in the current directory.")
    parser.add_argument("--out", type=Path, default=Path("site"), help="Output directory for the generated website")
    parser.add_argument("--start-season", type=int, default=2026, help="First season to show on player stat pages")
    parser.add_argument("--schedule-season", type=int, default=None, help="Season to use for Schedule/Scores pages. Defaults to an exported schedule, or the upcoming season during offseason exports.")
    parser.add_argument("--schedule-days", type=int, default=None, help="Optional target number of calendar days for a generated schedule, such as 46.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before generating")
    parser.add_argument("--prev", type=Path, default=None, help="Previous export for day-over-day standings movement. Defaults to the closest earlier day*.json.")
    return parser.parse_args()


def newest_day_json() -> Path | None:
    candidates = []
    for path in Path.cwd().glob("day*.json"):
        match = re.fullmatch(r"day(\d+)", path.stem)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        return None
    return max(candidates)[1]


def main() -> None:
    args = parse_args()
    if args.json_file is None:
        args.json_file = newest_day_json()
        if args.json_file is None:
            raise SystemExit("No JSON file given and no day*.json found in the current directory.")
        print(f"Using newest export: {args.json_file.name}")
    summary = generate_site(
        args.json_file,
        args.out,
        start_season=args.start_season,
        clean=args.clean,
        schedule_season=args.schedule_season,
        schedule_days=args.schedule_days,
        prev_json_path=args.prev,
    )
    print(f"Generated site in {args.out.resolve()}")
    print(f"Season: {summary['season']}")
    print(f"Schedule/Scores: {summary['schedule_label']} / {summary['score_label']}")
    print(f"Teams: {summary['teams']}; team pages: {summary['team_pages']}")
    print(f"Players: {summary['players']}; player pages: {summary['player_pages']}; free agents: {summary['free_agents']}")
    print(f"Schedule games: {summary['schedule_games']}; score rows: {summary['score_games']}; completed scores: {summary['completed_scores']}; game pages: {summary['game_pages']}")


if __name__ == "__main__":
    main()
