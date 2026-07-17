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

# Projection engine (faithful zengm port + Monte Carlo). Imported defensively so
# the site still builds if numpy / projections.py is unavailable -- in that case
# projection charts gracefully fall back to the static development chart.
try:
    import projections as _proj
except Exception:  # pragma: no cover - degraded build path
    _proj = None

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

THEME_SNIPPET = (
    '<script>document.documentElement.dataset.theme = '
    'localStorage.getItem("theme") || '
    '(matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");'
    "</script>"
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
    # Hide scrub free agents: drop anyone below 50 ovr or below 50 pot.
    out = []
    for p in active_players(data):
        if p.get("tid") != FREE_AGENT_TID:
            continue
        if p.get("_fa_bid") is None:  # forced-release players (Gooners waive) always show
            rating = latest_rating(p)
            if safe_int(rating.get("ovr")) < 50 or safe_int(rating.get("pot")) < 50:
                continue
        out.append(p)
    return out


def contract_expiring_players(players: list[dict[str, Any]], exp_year: int, rostered_only: bool = True) -> list[dict[str, Any]]:
    rows = []
    for player in players:
        if player.get("retiredYear") is not None:
            continue
        tid = safe_int(player.get("tid"), RETIRED_TID)
        if rostered_only and tid < 0:
            continue
        if not rostered_only and tid < FREE_AGENT_TID:
            continue
        if safe_int((player.get("contract") or {}).get("exp"), -1) == exp_year:
            rows.append(player)
    return rows


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
    "SRS": "Simple Rating System: scoring margin adjusted for opponent strength",
    "Finals%": "Simulated chance of reaching the Finals",
    "Title%": "Simulated chance of winning the championship",
    "GB": "Games behind the leader",
    "PS": "Points scored per game",
    "PA": "Points allowed per game",
    "PER": "Player Efficiency Rating (league average is 15)",
    "WS": "Win Shares: estimated wins contributed",
    "VORP": "Value Over Replacement Player",
    "OBPM": "Offensive Box Plus/Minus per 100 possessions",
    "DBPM": "Defensive Box Plus/Minus per 100 possessions",
    "BPM": "Box Plus/Minus per 100 possessions vs league average",
    "STL": "Steals per game",
    "BLK": "Blocks per game",
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
    "Form": "Last 5 games vs season average, by Game Score",
    "WS/$M": "Win Shares per million of current salary",
    "YWT": "Years with team",
    "Ovr": "Current overall rating",
    "Pot": "Potential rating ceiling",
}


def th(label: str, cls: str = "", scope: str = "col") -> str:
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    scope_attr = f' scope="{esc(scope)}"' if scope else ""
    title = GLOSSARY.get(label)
    title_attr = f' title="{esc(title)}"' if title else ""
    return f"<th{scope_attr}{cls_attr}{title_attr}>{esc(label)}</th>"


POS_FILTER_OPTIONS = [
    ("all", "All positions"), ("G", "Guards"), ("F", "Forwards"), ("C", "Centers"),
    ("PG", "PG"), ("SG", "SG"), ("SF", "SF"), ("PF", "PF"),
]


def table_html(headers: list, rows: list[str], table_id: str | None = None, empty_message: str = "No players found.", wrap_cls: str = "", caption: str | None = None, pos_filter: bool = False) -> str:
    table_id_attr = f' id="{esc(table_id)}"' if table_id else ""
    if not rows:
        return f'<p class="empty-state">{esc(empty_message)}</p>'
    header_html = "".join(th(label) if isinstance(label, str) else th(label[0], label[1]) for label in headers)
    body_html = "\n".join(row if row.lstrip().startswith("<tr") else f"<tr>{row}</tr>" for row in rows)
    wrap_cls_attr = f" {wrap_cls}" if wrap_cls else ""
    caption_text = caption or (table_id.replace("-", " ").title() if table_id else "")
    caption_html = f'<caption class="sr-only">{esc(caption_text)}</caption>' if caption_text else ""
    # Optional position filter: only when a "Pos" column exists and the table has an id (for JS wiring).
    pos_bar, pos_attr = "", ""
    if pos_filter and table_id:
        labels = [label if isinstance(label, str) else label[0] for label in headers]
        if "Pos" in labels:
            pos_attr = f' data-pos-col="{labels.index("Pos")}"'
            options = "".join(f'<option value="{esc(v)}">{esc(l)}</option>' for v, l in POS_FILTER_OPTIONS)
            pos_bar = (f'<div class="toolbar pos-filter-bar"><label class="select-label">Position '
                       f'<select data-pos-filter="{esc(table_id)}">{options}</select></label></div>')
    return f"""
    {pos_bar}
    <div class="table-wrap{wrap_cls_attr}">
      <table{table_id_attr}{pos_attr} data-sortable>
        {caption_html}
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
        current = ' aria-current="page"' if key == active else ""
        return f'<a class="{klass}" href="{href}"{current}>{esc(label)}</a>'

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
        current = ' aria-current="page"' if key == active else ""
        team_links.append(
            f'<a class="{klass}" data-tid="{esc(team.get("tid"))}" data-abbrev="{esc(team.get("abbrev", ""))}" '
            f'href="{team_url(team, root)}"{current}>{esc(team_full_name(team))}</a>'
        )

    dropdown_class = "team-dropdown active" if active.startswith("team-") else "team-dropdown"
    return f"""
    <header class="site-header">
      <div class="brand"><a href="{root}index.html">SMP Basketball League</a></div>
      <div class="nav-search">
        <input type="search" placeholder="Search players &amp; teams…" data-global-search autocomplete="off" aria-label="Search players and teams" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="global-search-results" aria-activedescendant="">
        <div class="search-results" id="global-search-results" data-search-results role="listbox" hidden></div>
      </div>
      <button class="nav-burger" type="button" aria-label="Toggle menu" aria-controls="primary-nav" aria-expanded="false" data-nav-burger>☰ Menu</button>
      <nav class="primary-nav" id="primary-nav">
        {''.join(main_links)}
        <details class="{dropdown_class}">
          <summary>Teams</summary>
          <div class="team-menu" aria-label="Teams">{''.join(team_links)}</div>
        </details>
      </nav>
    </header>
    """


def page_html(title: str, body: str, teams: list[dict[str, Any]], root: str = "", active: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>{THEME_SNIPPET}
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
</body>
</html>
"""


def prior_team_tid(player: dict[str, Any], season: int) -> int | None:
    """The team the player last suited up for BEFORE ``season`` (most recent prior
    regular-season stat on a real team), or None if they have no prior history.

    Sort is by season only; for a mid-season trade (two rows in the same prior season)
    this relies on Basketball GM storing stat rows chronologically, so the stable sort
    keeps the later team last. That holds for these exports.
    """
    rows = sorted(
        (s for s in player.get("stats", []) if isinstance(s, dict) and not s.get("playoffs")
         and isinstance(s.get("season"), int) and s["season"] < season and safe_int(s.get("tid"), -9) >= 0),
        key=lambda s: s["season"],
    )
    return safe_int(rows[-1].get("tid")) if rows else None


def acquisition_html(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    season = SITE_META.get("season")
    blank = '<span class="muted">—</span>'
    transactions = [t for t in (player.get("transactions") or []) if isinstance(t, dict)]
    cur_tid = safe_int(player.get("tid"), -9)
    prev_tid = prior_team_tid(player, season) if isinstance(season, int) else None

    # (A) Changed teams since last season -> acquired this offseason. A recorded trade
    # into the current team reads as a trade; otherwise it was a free-agent signing.
    if isinstance(season, int) and cur_tid >= 0 and prev_tid is not None and prev_tid != cur_tid:
        trades = [t for t in transactions if t.get("type") == "trade" and safe_int(t.get("tid"), -9) == cur_tid]
        if trades:
            from_team = teams_by_tid.get(safe_int(trades[-1].get("fromTid"), -10))
            return f"Trade '{str(season)[-2:]}" + (f" from {esc(team_abbrev(from_team))}" if from_team else "")
        return f"FA '{str(season)[-2:]}"

    # (B) Same team (or no history) -> read the most recent draft/trade/FA transaction.
    relevant = [t for t in transactions if t.get("type") in ("draft", "trade", "freeAgent")]
    if not relevant:
        # No recorded move: a brand-new arrival reads as a current-season signing;
        # a long-tenured player with no transaction just shows blank.
        return (f"FA '{str(season)[-2:]}" if season and prev_tid is None else blank)
    tx = relevant[-1]
    tx_type = tx.get("type")
    season_short = f"'{str(tx.get('season'))[-2:]}" if tx.get("season") else ""
    if tx_type == "draft":
        # The 2026 inaugural draft only seeded rosters, and a "draft" whose season does
        # not match the player's actual draft year is an expansion/dispersal assignment
        # (e.g. Ithaca's 2028 expansion draft) -- neither is a real draft, so show nothing.
        tx_season = safe_int(tx.get("season"))
        if tx_season == 2026 or tx_season != safe_int((player.get("draft") or {}).get("year"), -1):
            return blank
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
    has_bpm = stat.get("obpm") is not None or stat.get("dbpm") is not None
    bpm = (safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))) if has_bpm else None
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
        td(fmt_number(per_game(stat, "stl"), 1), sort=per_game(stat, "stl")),
        td(fmt_number(per_game(stat, "blk"), 1), sort=per_game(stat, "blk")),
        td(fmt_signed(bpm, 1) if bpm is not None else "—", sort=bpm),
        td(acquisition_html(player, teams_by_tid or {}), sort=((player.get("transactions") or [{}])[-1] or {}).get("season")),
    ])


def team_finances_table(roster: list[dict[str, Any]], season: int, data: dict[str, Any] | None = None, tid: int | None = None) -> str:
    highlight_season = season + 1
    seasons = list(range(season + 1, season + 6))  # upcoming five seasons (drop the finished one)
    players = sorted(
        roster,
        key=lambda p: (-safe_float((p.get("contract") or {}).get("amount"), 0.0), player_name(p)),
    )
    headers = ["Pos", "Name"] + [(str(s), "cur-season" if s == highlight_season else "") for s in seasons]
    rows = []
    totals = {s: 0.0 for s in seasons}
    under_contract = {s: 0 for s in seasons}

    def salary_for(player: dict[str, Any], salary_season: int) -> float:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        if salary_season > exp:
            return 0.0
        exact = [
            salary for salary in player.get("salaries", [])
            if isinstance(salary, dict) and safe_int(salary.get("season"), -1) == salary_season
        ]
        if exact:
            return safe_float(exact[-1].get("amount"), 0.0)
        return safe_float(contract.get("amount"), 0.0)

    for player in players:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        rating = latest_rating(player, season)
        cells = [
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(player_link(player, "../"), sort=player_name(player), cls="name-cell"),
        ]
        for s in seasons:
            season_amount = salary_for(player, s)
            if s <= exp and season_amount > 0:
                totals[s] += season_amount
                under_contract[s] += 1
                cells.append(td(fmt_money(season_amount), sort=season_amount, cls="cur-season" if s == highlight_season else ""))
            else:
                cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
        rows.append("".join(cells))

    # Dead money: released players whose contracts are still owed.
    if data is not None and tid is not None:
        for released in data.get("releasedPlayers", []):
            if safe_int(released.get("tid"), -10) != tid:
                continue
            contract = released.get("contract") or {}
            amount = safe_float(contract.get("amount"), 0.0)
            exp = safe_int(contract.get("exp"), season)
            ghost = ALL_PLAYERS_BY_PID.get(safe_int(released.get("pid"), -10))
            name = player_name(ghost) if ghost else f"Released player {released.get('pid')}"
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Waived; contract still owed">{esc(name)} <span class="muted small-copy">(dead money)</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and amount > 0:
                    totals[s] += amount
                    cells.append(td(fmt_money(amount), sort=amount, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    # Retained salary from trades: the payer keeps its share (+); the roster team gets a credit (−).
    if tid is not None:
        for pid, r in FIN_RETENTION.items():
            retained_player = ALL_PLAYERS_BY_PID.get(pid)
            if retained_player is None:
                continue
            held_by = safe_int(r.get("held_by"), -10)
            roster_tid = safe_int(retained_player.get("tid"), -11)
            if tid not in (held_by, roster_tid):
                continue
            signed = safe_float(r.get("amount"), 0.0) * (1 if tid == held_by else -1)
            exp = safe_int((retained_player.get("contract") or {}).get("exp"), season)
            name = player_name(retained_player)
            tag = "retained salary" if tid == held_by else f'retained by {r.get("note", "another team")}'
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Salary retained in a trade">{esc(name)} <span class="muted small-copy">({tag})</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and abs(signed) > 1e-9:
                    totals[s] += signed
                    cells.append(td(fmt_money(signed), sort=signed, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    counts_cells = [td(""), td("Under Contract", cls="name-cell total-label")]
    totals_cells = [td(""), td("Committed Salary", cls="name-cell total-label")]
    for s in seasons:
        cur = " cur-season" if s == highlight_season else ""
        counts_cells.append(td(fmt_number(under_contract[s], 0), sort=under_contract[s], cls=cur.strip()))
        totals_cells.append(td(fmt_money(totals[s]), sort=totals[s], cls=cur.strip()))
    rows.append(f'<tr class="total-row">{"".join(counts_cells)}</tr>')
    rows.append(f'<tr class="total-row">{"".join(totals_cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Salaries</h2>
        <span class="muted small-copy">Salary commitments through {seasons[-1]}</span>
      </div>
      {table_html(headers, rows, table_id="team-finances", empty_message="No contracts found.", wrap_cls="fit-table")}
    </section>
    """


# ---------- league finance model ----------
# All amounts in Basketball GM "thousands" units (300000 == $300M). No hard cap.
FIN_START = 75000       # every team starts the season with $75M
FIN_BASE = 160000       # base league payout: +$160M
FIN_PER_WIN = 2000      # +$2M per regular-season win
FIN_PLAYOFF = 15000     # +$15M for a playoff appearance
FIN_FINALS = 15000      # +$15M for a finals appearance
FIN_CHAMP = 15000       # +$15M for a championship (bonuses stack: champion earns 15+15+15=$45M)
FIN_SOFT_CAP = 300000   # soft cap: $1 luxury tax per $1 of payroll over $300M

# Manual cash adjustments outside the auto-computed ledger (thousands), keyed by tid.
# Cash that changes hands in a trade, since BBGM exports don't record it. Signed:
# negative = cash out, positive = cash in. ponytail: hand-maintained; add rows as trades happen.
FIN_ADJUSTMENTS: dict[int, dict[str, Any]] = {
    2: {"amount": -1000, "note": "Cash to Waltham (trade)"},    # Cambridge Platypuses
    6: {"amount":  1000, "note": "Cash from Cambridge (trade)"},  # Waltham Bears
}

# Salary retained in a trade: the original team keeps paying part of a traded player's
# salary while the player sits on the new roster at full contract. BBGM exports don't
# record retention, so we move the retained share (thousands/yr) off the roster team's
# books onto the payer's — for payroll, luxury tax, and the salaries table — every season
# through the contract's exp. Keyed by pid. ponytail: hand-maintained; add rows as trades happen.
FIN_RETENTION: dict[int, dict[str, Any]] = {
    # (Cody Williams pid 1789 was waived to free agency in the 2031 offseason, so Waltham's
    # old $17M retention no longer applies — that entry was removed.)
    # 2031 trade: Ajay Mitchell + Trae Young to the Gooners with Waltham paying them in FULL,
    # so the retained share equals each contract and the Gooners carry $0 for both.
    1765: {"held_by": 6, "amount": 21000, "note": "Waltham (trade)"},  # Ajay Mitchell (roster tid 5)
    1325: {"held_by": 6, "amount": 18000, "note": "Waltham (trade)"},  # Trae Young (roster tid 5)
}

# Cumulative bankroll each team carries into next season (thousands), keyed by tid.
# The auto ledger resets to FIN_START each year, so in the offseason (phase >= 8) we show
# this hand-kept balance instead. ponytail: hand-maintained; refresh once per offseason.
FIN_NEXT_BALANCE: dict[int, int] = {
    7: 396000,  # Stony Brook Stingrays
    4: 365000,  # Toronto Jays
    2: 345000,  # Cambridge Platypuses
    3: 336000,  # Queens Pigeons
    0: 331000,  # Durham Destroyers
    6: 290000,  # Waltham Bears      (310 − 20 sent to the Gooners in the 2031 Mitchell/Young trade)
    1: 308000,  # Rochester Dragons
    8: 287000,  # Manhattan Elephants
    9: 245000,  # Ithaca Thunder
    5: 98000,   # Gooning Gooners    (78 + 20 received from Waltham in that trade)
}

# 2031 offseason roster move: the Gooners (tid 5) waive everyone but these keepers. Each waived
# player enters free agency asking their current contract price. ponytail: hand-maintained.
GOONERS_TID = 5
# Cason Wallace (1304) is kept at his existing $16M-thru-2031 deal.
GOONERS_KEEP_PIDS = {113, 1284, 1293, 1304, 1663, 1729}  # Ruutli, Tyson, Smith Jr., Wallace, Edgecombe, Avdalas

# 2031 offseason trades (hand-maintained). Applied AFTER the Gooners waive pass so incoming
# players aren't swept back out by it. Contracts already match the agreed terms, so only the
# roster team changes; salary that stays with the old team is handled by FIN_RETENTION above.
TRADE_MOVES: dict[int, int] = {   # pid -> destination tid
    118: 5,   # Espoir Ndinga: Toronto -> Gooners ($1M thru 2031)
    1765: 5,  # Ajay Mitchell: Waltham -> Gooners ($21M thru 2033, paid by Waltham)
    1325: 5,  # Trae Young:    Waltham -> Gooners ($18M thru 2032, paid by Waltham)
}
TRADE_PICKS: dict[tuple[int, int], int] = {   # (draft season, originalTid) -> new owning tid
    (2032, 5): 6,  # Gooners' 2032 pick -> Waltham
}


def apply_roster_moves(data: dict[str, Any]) -> None:
    """Mutate the loaded export to reflect hand-entered offseason roster moves.

    - Send the non-keeper Gooners to free agency (tid -1) and tag each with the contract price
      it should ask for (`_fa_bid`, thousands) so the FA page shows that instead of the formula.
    - Reprice this year's drafted rookies onto the salary formula (BBGM rookie-scale contracts
      don't match our economy).
    - Apply hand-entered trades (TRADE_MOVES / TRADE_PICKS), last so incoming players stick.

    Runs before active_players/free_agents are computed.
    """
    season = current_season(data)
    for p in data.get("players", []):
        if safe_int(p.get("tid"), -99) == GOONERS_TID and safe_int(p.get("pid"), -1) not in GOONERS_KEEP_PIDS:
            p["_fa_bid"] = safe_float((p.get("contract") or {}).get("amount"), 0.0)
            p["tid"] = FREE_AGENT_TID

        # Rookies drafted this year, now on a roster: price their contract off the formula.
        draft = p.get("draft") or {}
        if safe_int(draft.get("year"), -1) == season and safe_int(p.get("tid"), -99) >= 0:
            rating = latest_rating(p, season)
            born = (p.get("born") or {}).get("year")
            age_val = (season - born) if isinstance(born, int) else 22
            priced = fa_salary_by_length(safe_int(rating.get("ovr")), safe_int(rating.get("pot")), age_val)[0] * 1000
            contract = p.setdefault("contract", {})
            contract["amount"] = priced
            # Keep the per-season salaries[] array in sync (the Owed Payroll table reads it first).
            for salary in p.get("salaries", []):
                if isinstance(salary, dict):
                    salary["amount"] = priced

    by_pid = {safe_int(p.get("pid"), -1): p for p in data.get("players", [])}
    for pid, new_tid in TRADE_MOVES.items():
        traded = by_pid.get(pid)
        if traded is not None:
            from_tid = safe_int(traded.get("tid"), -1)
            traded["tid"] = new_tid
            # Log the move so the roster's "Acquired" column reads as a trade, not a signing.
            traded.setdefault("transactions", []).append(
                {"season": season, "phase": phase_value(data), "tid": new_tid, "type": "trade", "fromTid": from_tid}
            )
    for dp in data.get("draftPicks", []):
        new_tid = TRADE_PICKS.get((safe_int(dp.get("season"), -1), safe_int(dp.get("originalTid"), -1)))
        if new_tid is not None:
            dp["tid"] = new_tid


def team_retention_delta(tid: int, season: int) -> float:
    """Net salary-retention adjustment to a team's payroll for ``season`` (thousands).

    The payer (``held_by``) carries its retained share; the roster team is relieved of it.
    Only counts while the player is still under contract (``season <= exp``).
    """
    delta = 0.0
    for pid, r in FIN_RETENTION.items():
        player = ALL_PLAYERS_BY_PID.get(pid)
        if not player:
            continue
        exp = safe_int((player.get("contract") or {}).get("exp"), season)
        if season > exp:
            continue
        amount = safe_float(r.get("amount"), 0.0)
        if safe_int(r.get("held_by"), -10) == tid:
            delta += amount                       # payer keeps this on their books
        if safe_int(player.get("tid"), -10) == tid:
            delta -= amount                       # roster team is relieved of it
    return delta


FIN_FINALS_GAMES_TO_WIN = 4  # ponytail: best-of-7 finals (this league); read games-to-win if the format changes


def playoff_status(data: dict[str, Any], tid: int, season: int) -> tuple[bool, bool, bool]:
    """(made_playoffs, made_finals, won_championship) for a team in a season.

    Read from ``playoffSeries``; during the regular season there is no series yet,
    so this returns all-False and the playoff bonuses stay $0 until earned.

    ``playoffSeries.series`` GROWS one round at a time, so ``rounds[-1]`` is only the
    Finals once the bracket reaches its last round. The Finals is round index
    ``expected_rounds - 1`` (= log2(first-round matchups) + 1 total rounds); until that
    round exists no team has "made the finals", and the title is awarded only once the
    Finals series is clinched. This keeps the bonuses honest mid-playoff.
    """
    series_by_season = {safe_int(ps.get("season")): ps for ps in (data.get("playoffSeries") or []) if isinstance(ps, dict)}
    rounds = [rnd for rnd in ((series_by_season.get(season) or {}).get("series") or []) if rnd]
    if not rounds:
        return (False, False, False)

    matchups = lambda rnd: [m for m in (rnd or []) if isinstance(m, dict)]

    def in_matchup(m: dict[str, Any]) -> bool:
        return tid in (safe_int((m.get("home") or {}).get("tid"), -91), safe_int((m.get("away") or {}).get("tid"), -92))

    made = any(in_matchup(m) for rnd in rounds for m in matchups(rnd))
    first_round = matchups(rounds[0])
    expected_rounds = (int(round(math.log2(len(first_round)))) + 1) if first_round else len(rounds)

    made_finals = won_champ = False
    if len(rounds) >= expected_rounds:
        finals = matchups(rounds[expected_rounds - 1])
        made_finals = any(in_matchup(m) for m in finals)
        for m in finals:
            home, away = m.get("home") or {}, m.get("away") or {}
            hw, aw = safe_int(home.get("won")), safe_int(away.get("won"))
            if max(hw, aw) < FIN_FINALS_GAMES_TO_WIN:
                continue  # Finals series not clinched yet
            winner = safe_int(home.get("tid")) if hw > aw else safe_int(away.get("tid"))
            if winner == tid:
                won_champ = True
    return (made, made_finals, won_champ)


def team_dead_money(data: dict[str, Any] | None, tid: int, season: int) -> float:
    """Salary still owed to this team's waived players in ``season`` (dead money).

    A released player keeps being paid through their contract's ``exp`` year, so it
    counts against payroll/luxury tax even though they're off the roster.
    """
    total = 0.0
    for released in ((data or {}).get("releasedPlayers") or []):
        if safe_int(released.get("tid"), -10) != tid:
            continue
        contract = released.get("contract") or {}
        amount = safe_float(contract.get("amount"), 0.0)
        if amount > 0 and season <= safe_int(contract.get("exp"), season):
            total += amount
    return total


def compute_league_finances(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, odds: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-team cash-flow ledger for the season, recomputed each build from game results.

    Returns ``{"teams": {tid: ledger}, "pool", "share", "n_under", "soft_cap"}``.
    Luxury tax (payroll over the soft cap) is pooled and split equally among the
    teams under the cap. "Projected" figures use the 10k-sim projected wins and the
    expected value of the playoff bonuses (prob-weighted).
    """
    odds = odds or {}
    fin: dict[int, dict[str, Any]] = {}
    for team in teams:
        tid = safe_int(team.get("tid"), -99)
        if tid < 0 or team.get("disabled"):
            continue
        roster = [p for p in players if safe_int(p.get("tid"), -98) == tid]
        dead = team_dead_money(data, tid, season)
        retained = team_retention_delta(tid, season)  # traded-away salary kept on the books
        payroll = team_payroll(roster, season) + dead + retained  # waived + retained still get paid
        # Full next-season commitment (roster + dead money + retained) — matches the Owed Payroll
        # table's committed-salary total, so "available to spend" nets out every 2031 obligation.
        payroll_next = (team_payroll(roster, season + 1)
                        + team_dead_money(data, tid, season + 1)
                        + team_retention_delta(tid, season + 1))
        ts = latest_team_season(team, season)
        won, lost = safe_int(ts.get("won"), 0), safe_int(ts.get("lost"), 0)
        luxtax = max(0.0, payroll - FIN_SOFT_CAP)
        made_po, made_finals, won_champ = playoff_status(data, tid, season)
        earned_playoff = (FIN_PLAYOFF if made_po else 0) + (FIN_FINALS if made_finals else 0) + (FIN_CHAMP if won_champ else 0)
        o = odds.get(tid) or {}
        proj_w = safe_float(o.get("proj_w"), float(won))
        po_p, fin_p, champ_p = safe_float(o.get("po")), safe_float(o.get("finals")), safe_float(o.get("champ"))
        proj_playoff = FIN_PLAYOFF * po_p + FIN_FINALS * fin_p + FIN_CHAMP * champ_p
        adj_info = FIN_ADJUSTMENTS.get(tid) or {}
        fin[tid] = {
            "adj": safe_float(adj_info.get("amount"), 0.0), "adj_note": adj_info.get("note", ""),
            "payroll": payroll, "payroll_next": payroll_next, "dead": dead, "retained": retained, "won": won, "lost": lost, "luxtax": luxtax,
            "under_cap": payroll < FIN_SOFT_CAP, "over_cap": payroll > FIN_SOFT_CAP,
            "win_rev_now": FIN_PER_WIN * won, "win_rev_proj": FIN_PER_WIN * proj_w,
            "earned_playoff": earned_playoff, "proj_playoff": proj_playoff,
            "proj_w": proj_w, "po": po_p, "finals": fin_p, "champ": champ_p,
            "rev_now": FIN_BASE + FIN_PER_WIN * won + earned_playoff,
            "rev_proj": FIN_BASE + FIN_PER_WIN * proj_w + proj_playoff,
        }
    pool = sum(f["luxtax"] for f in fin.values())
    under = [t for t, f in fin.items() if f["under_cap"]]
    share = pool / len(under) if under else 0.0
    offseason = phase_value(data) >= 8
    for tid, f in fin.items():
        f["tax_share"] = share if f["under_cap"] else 0.0
        f["cash_now"] = FIN_START + f["rev_now"] - f["payroll"] - f["luxtax"] + f["tax_share"] + f["adj"]
        f["cash_proj"] = FIN_START + f["rev_proj"] - f["payroll"] - f["luxtax"] + f["tax_share"] + f["adj"]
        if offseason and tid in FIN_NEXT_BALANCE:
            # Offseason: the single-season ledger is over, so show the hand-kept cumulative
            # bankroll carried into next season (available to spend in free agency).
            f["cash_now"] = f["cash_proj"] = float(FIN_NEXT_BALANCE[tid])
            f["offseason"] = True
            f["bankroll_year"] = season + 1
        # Cash left after next season's committed roster salaries are paid.
        f["avail"] = f["cash_now"] - f["payroll_next"]
    return {"teams": fin, "pool": pool, "share": share, "n_under": len(under), "soft_cap": FIN_SOFT_CAP}


def fmt_money_pm(amount: Any) -> str:
    """Money with an explicit +/- sign; $0 for zero."""
    a = safe_float(amount, 0.0)
    if abs(a) < 1e-9:
        return "$0"
    return ("+" + fmt_money(a)) if a > 0 else fmt_money(a)


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
    involved.sort(key=game_sort_key)
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


def team_games_table(team: dict[str, Any], game_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int) -> str:
    tid = safe_int(team.get("tid"))
    involved = [
        item for item in game_items
        if safe_int(item.get("season")) == season
        and not item.get("playoffs")
        and tid in (safe_int(item.get("home_tid")), safe_int(item.get("away_tid")))
    ]
    involved.sort(key=game_sort_key)
    if not involved:
        return ""
    rows = []
    for item in involved:
        home = safe_int(item.get("home_tid")) == tid
        opp_tid = item.get("away_tid") if home else item.get("home_tid")
        completed = is_completed_game_item(item)
        result = team_schedule_result(item, tid)
        ot = game_ot_label(item)
        if ot and completed:
            result += f" {ot}"
        team_pts = item_team_points(item, tid)
        opp_pts = item_team_points(item, safe_int(opp_tid))
        # Opponent + home/away in one cell: "vs. GOO" at home, "@ GOO" on the road.
        opp_prefix = "vs." if home else "@"
        opp_cell = f'{opp_prefix} {team_label(opp_tid, teams_by_tid, "../")}'
        # `result` already includes the score (e.g. "W 112-108"), which is why the old
        # Result and Score columns were redundant — collapse to just this one.
        result_cell = esc(result) if completed else "Upcoming"
        margin = (safe_float(team_pts) - safe_float(opp_pts)) if completed else -999
        note = game_recap_text(item, teams_by_tid) if completed else "Scheduled"
        cls = "game-log-win" if result.startswith("W") else "game-log-loss" if result.startswith("L") else "game-log-next"
        rows.append(
            f'<tr class="click-row {cls}" data-href="{esc(game_url(item, "../"))}">'
            + "".join([
                td(fmt_number(item.get("day"), 0), sort=safe_int(item.get("day"))),
                td(opp_cell, sort=team_abbrev_for_tid(opp_tid, teams_by_tid), cls="name-cell"),
                td(result_cell, sort=margin),
                td(esc(note), sort=note, cls="game-note"),
                td(f'<a class="button-link table-link" href="{esc(game_url(item, "../"))}">View</a>', sort=safe_int(item.get("day"))),
            ])
            + "</tr>"
        )
    completed_count = sum(1 for item in involved if is_completed_game_item(item))
    headers = ["Day", "Opponent", "Result", "Note", "Link"]
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>All Games</h2><span class="muted small-copy">{completed_count} completed · {len(involved) - completed_count} upcoming</span></div>
      {table_html(headers, rows, table_id=f"team-{tid}-games", empty_message="No games found.", caption=f"{team_full_name(team)} current-season game log")}
    </section>
    """


def depth_chart_card(roster: list[dict[str, Any]], season: int) -> str:
    slots = ["PG", "SG", "SF", "PF", "C"]

    def preferred_slot(player: dict[str, Any]) -> str:
        rating = latest_rating(player, season)
        pos = rating.get("pos") or ""
        if pos in slots:
            return pos
        height = safe_int(player.get("hgt"), 0)
        if pos == "G":
            playmaking = safe_int(rating.get("pss")) + safe_int(rating.get("drb"))
            scoring = safe_int(rating.get("tp")) + safe_int(rating.get("fg"))
            return "PG" if playmaking >= scoring else "SG"
        if pos == "GF":
            return "SG" if height and height < 79 else "SF"
        if pos == "F":
            return "SF" if height and height < 81 else "PF"
        if pos == "FC":
            return "PF" if height and height < 83 else "C"
        if height:
            if height < 76:
                return "PG"
            if height < 79:
                return "SG"
            if height < 81:
                return "SF"
            if height < 83:
                return "PF"
        return "C"

    buckets: dict[str, list[dict[str, Any]]] = {slot: [] for slot in slots}
    for player in roster:
        buckets[preferred_slot(player)].append(player)
    columns = []
    for slot in slots:
        fits = buckets[slot]
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
      <div class="section-title-row"><h2>Depth Chart</h2><span class="muted small-copy">single best position fit · ✚ currently injured</span></div>
      <div class="depth-grid">{''.join(columns)}</div>
    </section>
    """


def rotation_map_card(team: dict[str, Any], roster: list[dict[str, Any]], game_items: list[dict[str, Any]], game_logs: dict[int, list[dict[str, Any]]], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    completed = [
        item for item in game_items
        if is_completed_game_item(item)
        and safe_int(item.get("season")) == season
        and not item.get("playoffs")
        and tid in (safe_int(item.get("home_tid")), safe_int(item.get("away_tid")))
    ]
    completed.sort(key=game_sort_key)
    window = completed
    if not window:
        return ""
    gids = [str(item.get("gid")) for item in window]
    gid_set = set(gids)
    header_cells = ['<th class="name-cell">Player</th>']
    for item in window:
        won = game_winner_tid(item) == tid
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        loc = "vs" if safe_int(item.get("home_tid")) == tid else "@"
        cls = "rot-w" if won else "rot-l"
        header_cells.append(
            f'<th class="{cls}" title="Day {safe_int(item.get("day"))} {loc} {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}">'
            f'{safe_int(item.get("day"))}</th>'
        )

    rows_by_pid: dict[int, dict[str, Any]] = {}
    for pid, entries in game_logs.items():
        for entry in entries:
            if safe_int(entry.get("tid"), -999) != tid:
                continue
            gid = str(entry.get("gid"))
            if gid not in gid_set:
                continue
            minutes = safe_float((entry.get("box") or {}).get("min"))
            if minutes <= 0:
                continue
            box = entry.get("box") or {}
            player = ALL_PLAYERS_BY_PID.get(pid)
            name = player_name(player) if player else str(box.get("name") or f"Player {pid}")
            label = player_link(player, "../", show_number=False) if player else f'<span class="player-link">{esc(name)}</span>'
            row = rows_by_pid.setdefault(pid, {"name": name, "label": label, "minutes_by_gid": defaultdict(float)})
            row["minutes_by_gid"][gid] += minutes

    rows = []
    max_minutes = max(
        (
            minutes
            for row in rows_by_pid.values()
            for minutes in row["minutes_by_gid"].values()
        ),
        default=0.0,
    )
    for row in rows_by_pid.values():
        minutes_by_gid = row["minutes_by_gid"]
        window_minutes = [minutes_by_gid.get(gid, 0.0) for gid in gids]
        total = sum(window_minutes)
        if total <= 0:
            continue
        cells = [td(row["label"], sort=row["name"], cls="name-cell")]
        for minutes in window_minutes:
            if minutes <= 0:
                cells.append(td('<span class="muted">·</span>', sort=0, cls="rot-cell"))
            else:
                frac = min(1.0, minutes / max_minutes) if max_minutes > 0 else 0.0
                hue = 4 + 126 * frac
                alpha = 0.18 + 0.34 * frac
                style = f"background-color: hsla({hue:.0f}, 58%, 42%, {alpha:.2f})"
                cells.append(td(fmt_number(minutes, 0), sort=minutes, cls="rot-cell", style=style))
        rows.append((total, row["name"], "".join(cells)))
    if not rows:
        return ""
    rows.sort(key=lambda pair: (-pair[0], pair[1]))
    body_html = "".join(f"<tr>{cells}</tr>" for _, _, cells in rows)
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Rotation Map</h2><span class="muted small-copy">{len(window)} completed games this season · red to green = minutes load · · = DNP</span></div>
      <div class="table-wrap fit-table">
        <table class="rotation-map">
          <thead><tr>{''.join(header_cells)}</tr></thead>
          <tbody>{body_html}</tbody>
        </table>
      </div>
    </section>
    """


SHOT_ZONES = [("AtRim", "Rim"), ("LowPost", "Post"), ("MidRange", "Mid"), ("", "3P")]


def shot_zone_cells(box: dict[str, Any]) -> list[str]:
    cells = []
    for suffix, label in SHOT_ZONES:
        if label == "3P":
            made, att = safe_float(box.get("tp")), safe_float(box.get("tpa"))
        else:
            made, att = safe_float(box.get("fg" + suffix)), safe_float(box.get("fga" + suffix))
        pct = made_pct(made, att)
        cells.append(td(f"{fmt_number(made, 0)}-{fmt_number(att, 0)} <span class=\"muted\">({fmt_pct(pct, 0)}%)</span>" if att else "—", sort=pct))
    return cells


def game_shot_profile(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    if not is_completed_game_item(item):
        return ""
    rows = []
    for box_key in ("away_box", "home_box"):
        box = item.get(box_key) or {}
        cells = [td(team_label(box.get("tid"), teams_by_tid, root), cls="name-cell")] + shot_zone_cells(box)
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(th(label) for label in ["Team", "Rim", "Post", "Mid", "3P"])
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Shot Zones</h2><span class="muted small-copy">made-attempted (FG%) by area</span></div>
      <div class="table-wrap fit-table">
        <table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>
      </div>
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

    # aggregate shot zones for the season
    zone_totals = defaultdict(float)
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            own_box = item.get("home_box") or {}
        elif safe_int(item.get("away_tid")) == tid:
            own_box = item.get("away_box") or {}
        else:
            continue
        for key in ("fgAtRim", "fgaAtRim", "fgLowPost", "fgaLowPost", "fgMidRange", "fgaMidRange", "tp", "tpa"):
            zone_totals[key] += safe_float(own_box.get(key))
    total_fga = zone_totals["fgaAtRim"] + zone_totals["fgaLowPost"] + zone_totals["fgaMidRange"] + zone_totals["tpa"]
    shot_rows = ""
    if total_fga > 0:
        mix_cells = []
        pct_cells = []
        for made_key, att_key in (("fgAtRim", "fgaAtRim"), ("fgLowPost", "fgaLowPost"), ("fgMidRange", "fgaMidRange"), ("tp", "tpa")):
            att = zone_totals[att_key]
            mix = 100 * att / total_fga
            pct = made_pct(zone_totals[made_key], att)
            mix_cells.append(td(fmt_number(mix, 0) + "%", sort=mix))
            pct_cells.append(td(fmt_pct(pct, 1), sort=pct))
        shot_rows = (
            '<tr>' + td("Shot mix", cls="name-cell") + "".join(mix_cells) + '</tr>'
            '<tr>' + td("FG%", cls="name-cell") + "".join(pct_cells) + '</tr>'
        )
    shot_table = f"""
    <div class="table-wrap fit-table">
      <table class="qtr-table">
        <thead><tr><th></th><th>Rim</th><th>Post</th><th>Mid</th><th>3P</th></tr></thead>
        <tbody>{shot_rows}</tbody>
      </table>
    </div>
    """ if shot_rows else ""

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
    {shot_table}
    """
    team_season = latest_team_season(team, season)
    home_rec = fmt_record(team_season.get("wonHome"), team_season.get("lostHome"))
    road_rec = fmt_record(team_season.get("wonAway"), team_season.get("lostAway"))
    top4 = set(standings_order(active_teams_for_season([t for t in teams_by_tid.values()], season), season)[:4])
    top4_w = top4_l = 0
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            opp = safe_int(item.get("away_tid"))
        elif safe_int(item.get("away_tid")) == tid:
            opp = safe_int(item.get("home_tid"))
        else:
            continue
        if opp in top4:
            if game_winner_tid(item) == tid:
                top4_w += 1
            else:
                top4_l += 1
    tiles = "".join([
        f'<div class="vital-tile"><span>Home / Road</span><strong>{esc(home_rec)} / {esc(road_rec)}</strong></div>',
        f'<div class="vital-tile"><span>vs top 4</span><strong>{top4_w}-{top4_l}</strong></div>',
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
        rnd = "" if safe_int(dp.get("round")) == 1 else " 2nd"  # single-round league: no "1st"
        own = safe_int(dp.get("originalTid"), -10) == tid
        via = "" if own else f' <span class="muted">via {esc(team_abbrev(teams_by_tid.get(safe_int(dp.get("originalTid"), -10))))}</span>'
        chips.append(f'<span class="pick-chip{" pick-own" if own else " pick-acquired"}">{esc(dp.get("season"))}{rnd}{via}</span>')
    traded_away = [
        dp for dp in data.get("draftPicks", [])
        if isinstance(dp, dict) and safe_int(dp.get("originalTid"), -10) == tid and safe_int(dp.get("tid"), -10) != tid
    ]
    away_note = ""
    if traded_away:
        away_bits = []
        for dp in sorted(traded_away, key=lambda dp: (dp.get("season"), safe_int(dp.get("round")))):
            rnd = "" if safe_int(dp.get("round")) == 1 else " 2nd"
            holder = team_abbrev(teams_by_tid.get(safe_int(dp.get("tid"), -10)))
            away_bits.append(f"{dp.get('season')}{rnd} → {holder}")
        away_note = f'<p class="muted small-copy">Traded away: {esc(" · ".join(away_bits))}</p>'
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Draft Picks</h2><span class="count-pill">{len(picks)} owned</span></div>
      <div class="pick-row">{''.join(chips)}</div>
      {away_note}
    </section>
    """


def hero_finance_chip(tfin: dict[str, Any] | None) -> str:
    if not tfin:
        return ""
    now, proj = tfin["cash_now"], tfin["cash_proj"]
    nc = "delta-up" if now >= 0 else "delta-down"
    if tfin.get("offseason"):
        avail = tfin.get("avail", now)
        ac = "delta-up" if avail >= 0 else "delta-down"
        return f"""
    <div class="hero-finance">
      <div class="hero-fin-row"><span>Cash on hand</span><strong class="{nc}">{fmt_money(now)}</strong></div>
      <div class="hero-fin-row"><span>Available to spend</span><strong class="{ac}">{fmt_money(avail)}</strong></div>
    </div>"""
    pc = "delta-up" if proj >= 0 else "delta-down"
    return f"""
    <div class="hero-finance">
      <div class="hero-fin-row"><span>Cash on hand</span><strong class="{nc}">{fmt_money(now)}</strong></div>
      <div class="hero-fin-row"><span>Projected EOS</span><strong class="{pc}">{fmt_money(proj)}</strong></div>
    </div>"""


def team_subnav(team: dict[str, Any], active_sub: str) -> str:
    slug = team_slug(team)
    items = [("roster", "Roster", f"{slug}.html"), ("games", "Games", f"{slug}-games.html"), ("finances", "Finances", f"{slug}-finances.html")]
    links = []
    for key, label, href in items:
        active = " active" if key == active_sub else ""
        cur = ' aria-current="page"' if key == active_sub else ""
        links.append(f'<a class="subnav-link{active}" href="{href}"{cur}>{esc(label)}</a>')
    return f'<nav class="team-subnav" aria-label="Team sections">{"".join(links)}</nav>'


def team_hero_html(team: dict[str, Any], season: int, sorted_roster: list[dict[str, Any]], teams: list[dict[str, Any]], tfin: dict[str, Any] | None) -> str:
    primary = team_palette_by_tid(teams).get(safe_int(team.get("tid"), -1), "#5b9dff")
    ts = latest_team_season(team, season)
    record = fmt_record(ts.get("won"), ts.get("lost"))
    streak = streak_text(ts.get("streak"))
    bits = [esc(team.get("abbrev", ""))]
    if record != "—":
        bits.append(record)
    if streak != "—":
        bits.append(streak)
    bits.append(f"{len(sorted_roster)} players")
    return f"""
    <section class="page-hero team-hero" style="--team-primary:{esc(primary)};--team-secondary:{esc(primary)}">
      <div>
        <p class="eyebrow">Team</p>
        <h1>{esc(team_full_name(team))}</h1>
        <p class="muted">{' · '.join(bits)}</p>
      </div>
      {hero_finance_chip(tfin)}
    </section>"""


def _payroll_note(f: dict[str, Any]) -> str:
    """Small-copy parenthetical explaining what's baked into the payroll figure."""
    parts = []
    if f.get("dead"):
        parts.append(f'incl. {fmt_money(f["dead"])} dead money')
    retained = safe_float(f.get("retained"), 0.0)
    if retained > 1e-9:
        parts.append(f'incl. {fmt_money(retained)} retained salary')
    elif retained < -1e-9:
        parts.append(f'net of {fmt_money(-retained)} retained elsewhere')
    return f' <span class="muted small-copy">({"; ".join(parts)})</span>' if parts else ""


def finance_ledger_card(tfin: dict[str, Any] | None) -> str:
    if not tfin:
        return ""
    f = tfin

    if f.get("offseason"):
        # Offseason: the season ledger has closed, so headline the carried-over bankroll and
        # how much of it is still free once next season's roster is paid.
        bal = f["cash_now"]
        committed = f.get("payroll_next", 0.0)
        avail = f.get("avail", bal - committed)
        year = f.get("bankroll_year", "")
        nc = "delta-up" if bal >= 0 else "delta-down"
        ac = "delta-up" if avail >= 0 else "delta-down"
        return f"""
    <section class="card">
      <div class="section-title-row"><h2>Cash on Hand</h2><span class="muted small-copy">available to spend in free agency</span></div>
      <div class="vitals-row">
        <div class="vital-tile"><span>Balance entering {year}</span><strong class="{nc}">{fmt_money(bal)}</strong></div>
        <div class="vital-tile"><span>{year} payroll</span><strong>{fmt_money(committed)}</strong></div>
        <div class="vital-tile"><span>Available to spend</span><strong class="{ac}">{fmt_money(avail)}</strong></div>
      </div>
    </section>"""

    def row(label: str, now: str, proj: str, cls: str = "") -> str:
        cls_attr = f' class="{cls}"' if cls else ""
        return f'<tr{cls_attr}><td class="ledger-label">{label}</td><td class="ledger-num">{now}</td><td class="ledger-num">{proj}</td></tr>'

    payroll_cell = f'<span class="delta-down">{fmt_money(-f["payroll"])}</span>'
    luxtax_cell = f'<span class="delta-down">{fmt_money(-f["luxtax"])}</span>' if f["luxtax"] > 0 else "$0"
    share_cell = f'<span class="delta-up">{fmt_money_pm(f["tax_share"])}</span>' if f["tax_share"] > 0 else "$0"
    cash_now = f'<strong class="{"delta-up" if f["cash_now"] >= 0 else "delta-down"}">{fmt_money(f["cash_now"])}</strong>'
    cash_proj = f'<strong class="{"delta-up" if f["cash_proj"] >= 0 else "delta-down"}">{fmt_money(f["cash_proj"])}</strong>'
    rows = [
        row("Starting balance", fmt_money(FIN_START), fmt_money(FIN_START)),
        row("Base league payout", fmt_money_pm(FIN_BASE), fmt_money_pm(FIN_BASE)),
        row(f'Win bonus <span class="muted small-copy">({fmt_money(FIN_PER_WIN)} × W)</span>',
            f'{fmt_money_pm(f["win_rev_now"])} <span class="muted small-copy">({f["won"]} W)</span>',
            f'{fmt_money_pm(f["win_rev_proj"])} <span class="muted small-copy">(proj {fmt_number(f["proj_w"], 1)} W)</span>'),
        row('Playoff bonuses <span class="muted small-copy">(EV projected)</span>', fmt_money_pm(f["earned_playoff"]), fmt_money_pm(f["proj_playoff"])),
        row("Total revenue", f'<strong>{fmt_money(f["rev_now"])}</strong>', f'<strong>{fmt_money(f["rev_proj"])}</strong>', cls="ledger-subtotal"),
        row("Player payroll" + _payroll_note(f), payroll_cell, payroll_cell),
        row('Luxury tax <span class="muted small-copy">(over $300M)</span>', luxtax_cell, luxtax_cell),
        row('Tax distribution <span class="muted small-copy">(under-cap share)</span>', share_cell, share_cell),
    ]
    if abs(f.get("adj", 0)) > 1e-9:
        adj_cls = "delta-up" if f["adj"] > 0 else "delta-down"
        adj_label = "Trade adjustment"
        if f.get("adj_note"):
            adj_label += f' <span class="muted small-copy">({esc(f["adj_note"])})</span>'
        adj_cell = f'<span class="{adj_cls}">{fmt_money_pm(f["adj"])}</span>'
        rows.append(row(adj_label, adj_cell, adj_cell))
    rows.append(row("Cash on hand", cash_now, cash_proj, cls="ledger-total"))
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Cash Flow</h2><span class="muted small-copy">live ledger · projected = 10k-sim wins + playoff EV</span></div>
      <div class="table-wrap">
        <table class="ledger-table">
          <thead><tr><th>Item</th><th>Now</th><th>Projected (EOS)</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def luxury_tax_card(tfin: dict[str, Any] | None, league_fin: dict[str, Any]) -> str:
    if not tfin:
        return ""
    f = tfin
    cap = league_fin.get("soft_cap", FIN_SOFT_CAP)
    tiles = [("Payroll", fmt_money(f["payroll"]), "")]
    if f["over_cap"]:
        tiles.append(("Over cap by", fmt_money(f["payroll"] - cap), "delta-down"))
        tiles.append(("Luxury tax paid", fmt_money(-f["luxtax"]), "delta-down"))
    elif f["under_cap"]:
        tiles.append(("Under cap by", fmt_money(cap - f["payroll"]), "delta-up"))
        tiles.append(("Tax distribution", fmt_money_pm(f["tax_share"]), "delta-up"))
    else:
        tiles.append(("At the cap", "$0", ""))
    tile_html = "".join(f'<div class="vital-tile"><span>{esc(l)}</span><strong class="{c}">{v}</strong></div>' for l, v, c in tiles)
    n_under = safe_int(league_fin.get("n_under"), 0)
    note = f'League luxury-tax pool {fmt_money(league_fin.get("pool", 0))} split equally among {n_under} under-cap team{"" if n_under == 1 else "s"} ({fmt_money(league_fin.get("share", 0))} each).'
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Luxury Tax</h2><span class="muted small-copy">soft cap {fmt_money(cap)} · $1 per $1 over · redistributed to under-cap teams</span></div>
      <div class="vitals-row">{tile_html}</div>
      <p class="muted small-copy">{note}</p>
    </section>"""


def finance_rules_card() -> str:
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>How Finances Work</h2></div>
      <div class="fin-rules">
        <div>
          <h3>Revenue</h3>
          <ul class="fin-list">
            <li>Starting balance <strong>{fmt_money(FIN_START)}</strong></li>
            <li>Base league payout <strong>+{fmt_money(FIN_BASE)}</strong></li>
            <li>Per win <strong>+{fmt_money(FIN_PER_WIN)}</strong></li>
            <li>Playoff appearance <strong>+{fmt_money(FIN_PLAYOFF)}</strong></li>
            <li>Finals appearance <strong>+{fmt_money(FIN_FINALS)}</strong></li>
            <li>Championship <strong>+{fmt_money(FIN_CHAMP)}</strong></li>
          </ul>
        </div>
        <div>
          <h3>Spending</h3>
          <ul class="fin-list">
            <li>Player payroll <span class="muted small-copy">(full-season salaries + dead money)</span></li>
            <li>Luxury tax <strong>$1 per $1</strong> over the <strong>{fmt_money(FIN_SOFT_CAP)}</strong> soft cap</li>
            <li>Collected tax is split equally among the teams under the cap</li>
          </ul>
        </div>
      </div>
    </section>"""


def _age_sort(player: dict[str, Any], season: int) -> int | None:
    yr = (player.get("born") or {}).get("year")
    return (season - yr) if isinstance(yr, int) else None


def roster_advanced_row(player: dict[str, Any], season: int, start_season: int, root: str) -> str:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    fga, fta = safe_float(stat.get("fga")), safe_float(stat.get("fta"))
    fg, tp, pts = safe_float(stat.get("fg")), safe_float(stat.get("tp")), safe_float(stat.get("pts"))
    ts = (pts / (2.0 * (fga + 0.44 * fta))) if (fga + 0.44 * fta) > 0 else None
    efg = ((fg + 0.5 * tp) / fga) if fga > 0 else None
    has_bpm = stat.get("obpm") is not None or stat.get("dbpm") is not None
    bpm = (safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))) if has_bpm else None
    return "".join([
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=_age_sort(player, season)),
        td(fmt_number(gp, 0), sort=gp),
        td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
        td(fmt_number(ts * 100, 1) if ts is not None else "—", sort=ts),
        td(fmt_number(efg * 100, 1) if efg is not None else "—", sort=efg),
        td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg")),
        td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg")),
        td(fmt_signed(stat.get("obpm"), 1) if stat.get("obpm") is not None else "—", sort=stat.get("obpm")),
        td(fmt_signed(stat.get("dbpm"), 1) if stat.get("dbpm") is not None else "—", sort=stat.get("dbpm")),
        td(fmt_signed(bpm, 1) if bpm is not None else "—", sort=bpm),
        td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp")),
        td(fmt_signed(stat.get("pm"), 0) if stat.get("pm") is not None else "—", sort=stat.get("pm")),
    ])


def roster_ratings_row(player: dict[str, Any], season: int, root: str, rating_ranges: dict[str, tuple[float, float]]) -> str:
    rating = latest_rating(player, season)
    cells = [
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=_age_sort(player, season)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
    return "".join(cells)


def roster_tabs(sorted_roster: list[dict[str, Any]], season: int, start_season: int, root: str, teams_by_tid: dict[int, dict[str, Any]], game_logs: dict[int, list[dict[str, Any]]] | None) -> str:
    """One sortable spreadsheet of the whole roster, toggled between three column sets."""
    ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        vals = [float(latest_rating(p, season)[key]) for p in sorted_roster
                if isinstance(latest_rating(p, season).get(key), (int, float))]
        ranges[key] = (min(vals), max(vals)) if vals else (0.0, 0.0)

    stats_headers = ["Name", "Pos", "Age", "Ovr", "Pot", "Contract", "Health", "G", "MP", "PTS", "TRB", "AST", "STL", "BLK", "BPM", "Acquired"]
    stats_rows = [roster_row(p, season, start_season, root, teams_by_tid) for p in sorted_roster]
    adv_headers = ["Name", "Pos", "Age", "G", "MP", "TS%", "eFG%", "ORtg", "DRtg", "OBPM", "DBPM", "BPM", "VORP", "+/-"]
    adv_rows = [roster_advanced_row(p, season, start_season, root) for p in sorted_roster]
    rat_headers: list = ["Name", "Pos", "Age", "Ovr", "Pot"]
    for key, label in TEAM_RATING_RANK_KEYS:
        rat_headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rat_rows = [roster_ratings_row(p, season, root, ranges) for p in sorted_roster]

    def tab(tid: str, label: str, first: bool) -> str:
        return (f'<button type="button" class="{"active" if first else ""}" role="tab" id="tab-{tid}" '
                f'aria-controls="panel-{tid}" aria-selected="{"true" if first else "false"}" '
                f'tabindex="{"0" if first else "-1"}" data-tab-target="panel-{tid}">{esc(label)}</button>')

    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Players</h2><span class="muted small-copy">click a column header to sort · {len(sorted_roster)} players</span></div>
      <div class="tabs" role="tablist" aria-label="Roster stat views" data-tabs>
        {tab("rstats", "Stats", True)}{tab("radv", "Advanced", False)}{tab("rrat", "Ratings", False)}
      </div>
      <div id="panel-rstats" role="tabpanel" aria-labelledby="tab-rstats" data-tab-panel>
        {table_html(stats_headers, stats_rows, table_id="roster-stats", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True)}
      </div>
      <div id="panel-radv" role="tabpanel" aria-labelledby="tab-radv" data-tab-panel hidden>
        {table_html(adv_headers, adv_rows, table_id="roster-advanced", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True)}
      </div>
      <div id="panel-rrat" role="tabpanel" aria-labelledby="tab-rrat" data-tab-panel hidden>
        {table_html(rat_headers, rat_rows, table_id="roster-ratings", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True)}
      </div>
    </section>"""


def _sorted_team_roster(roster: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    return sorted(roster, key=lambda p: (p.get("rosterOrder", 10**9), -latest_rating(p, season).get("ovr", 0), player_name(p)))


def render_team_roster_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, game_items: list[dict[str, Any]] | None = None, game_logs: dict[int, list[dict[str, Any]]] | None = None, tfin: dict[str, Any] | None = None) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = _sorted_team_roster(roster, season)
    rotation = rotation_map_card(team, sorted_roster, game_items or [], game_logs or {}, season, teams_by_tid) if game_items and game_logs else ""
    picks = draft_picks_card(data, team, teams_by_tid) if data else ""
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin)}
    {team_subnav(team, "roster")}
    {roster_tabs(sorted_roster, season, start_season, "../", teams_by_tid, game_logs)}
    {depth_chart_card(sorted_roster, season)}
    {rotation}
    {picks}
    """
    return page_html(team_full_name(team), body, teams, root="../", active=f"team-{team.get('tid')}")


def render_team_games_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, game_items: list[dict[str, Any]] | None = None, game_logs: dict[int, list[dict[str, Any]]] | None = None, tfin: dict[str, Any] | None = None) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = _sorted_team_roster(roster, season)
    strip = team_games_strip(team, game_items or [], teams_by_tid) if game_items else ""
    games_table = team_games_table(team, game_items or [], teams_by_tid, season) if game_items else ""
    profile = team_quarter_profile(team, data, season, teams_by_tid) if data else ""
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin)}
    {team_subnav(team, "games")}
    {strip}
    {games_table}
    {profile}
    """
    return page_html(f"{team_full_name(team)} — Games", body, teams, root="../", active=f"team-{team.get('tid')}")


def render_team_finances_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, tfin: dict[str, Any] | None = None, league_fin: dict[str, Any] | None = None) -> str:
    sorted_roster = _sorted_team_roster(roster, season)
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin)}
    {team_subnav(team, "finances")}
    {finance_ledger_card(tfin)}
    {luxury_tax_card(tfin, league_fin or {})}
    <h2 class="block-title">Owed Payroll</h2>
    {team_finances_table(sorted_roster, season, data=data, tid=safe_int(team.get("tid")))}
    {finance_rules_card()}
    """
    return page_html(f"{team_full_name(team)} — Finances", body, teams, root="../", active=f"team-{team.get('tid')}")


RATING_GROUP_STARTS = {"hgt", "ins", "oiq"}


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


def free_agent_row(player: dict[str, Any], season: int, root: str, rating_ranges: dict[str, tuple[float, float]]) -> str:
    rating = latest_rating(player, season)
    born = (player.get("born") or {}).get("year")
    age_val = (season - born) if isinstance(born, int) else 25
    cells = [
        td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - born if isinstance(born, int) else None)),
        td(esc(rating.get("ovr") if rating.get("ovr") is not None else "—"), sort=rating.get("ovr")),
        td(esc(rating.get("pot") if rating.get("pot") is not None else "—"), sort=rating.get("pot")),
    ]
    # Starting bid: a released player (Gooners waive) asks their current contract price; everyone
    # else asks the model's 1-year annual value. Both in BBGM thousands.
    override = player.get("_fa_bid")
    if override is not None:
        bid_k = safe_float(override)
    else:
        bid_k = fa_salary_by_length(safe_int(rating.get("ovr")), safe_int(rating.get("pot")), age_val)[0] * 1000
    cells.append(td(fmt_money(bid_k), sort=bid_k, cls="group-start"))
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
    return "".join(cells)


def render_free_agency_page(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, all_players: list[dict[str, Any]] | None = None, market_year: int | None = None) -> str:
    market_year = market_year if market_year is not None else season

    def market_sort_key(player: dict[str, Any]) -> tuple[int, int, str]:
        rating = latest_rating(player, season)
        return (-safe_int(rating.get("ovr")), -safe_int(rating.get("pot")), player_name(player))

    sorted_players = sorted(players, key=market_sort_key)

    rating_ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        values = []
        for p in sorted_players:
            value = latest_rating(p, season).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers: list = ["Name", "Pos", "Age", "Ovr", "Pot", ("Starting Bid", "group-start")]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [free_agent_row(p, season, "", rating_ranges) for p in sorted_players]

    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">Free Agency</p>
        <h1>{market_year} Free Agents</h1>
        <p class="muted">Every unsigned player available this offseason. Starting bid is the annual value of a one-year deal, derived from the player's overall, potential, and age.</p>
      </div>
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Available Players</h2><span class="count-pill">{len(sorted_players)}</span></div>
      <div class="toolbar">
        <input class="table-search" data-table-filter="free-agents" placeholder="Filter free agents…" aria-label="Filter free agents">
      </div>
      {table_html(headers, rows, table_id="free-agents", empty_message="No free agents found.", caption=f"{market_year} free agents", pos_filter=True)}
    </section>
    """
    return page_html("Free Agents", body, teams, root="", active="free-agency")


def render_players_index(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    rostered = [p for p in players if isinstance(p.get("tid"), int) and p.get("tid") >= 0]
    sorted_players = sorted(rostered, key=lambda p: (p.get("tid", 999), p.get("rosterOrder", 9999), player_name(p)))
    fa_players = sorted(
        # Match the free-agency page: hide scrub FAs below 50 ovr or 50 pot.
        [p for p in players if p.get("tid") == FREE_AGENT_TID
         and safe_int(latest_rating(p, season).get("ovr")) >= 50
         and safe_int(latest_rating(p, season).get("pot")) >= 50],
        key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), -safe_int(latest_rating(p, season).get("pot")), player_name(p)),
    )
    prospects = sorted(
        draft_prospects(data) if data else [],
        key=lambda p: (safe_int((p.get("draft") or {}).get("year"), 9999), -safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    grouped_players: list[tuple[dict[str, Any], str]] = (
        [(p, "roster") for p in sorted_players] + [(p, "fa") for p in fa_players] + [(p, "draft") for p in prospects]
    )

    def group_rating(p: dict[str, Any], group: str) -> dict[str, Any]:
        # Prospects only carry their draft-class ratings row; everyone else uses this season's.
        return latest_rating(p) if group == "draft" else latest_rating(p, season)

    rating_ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        values = []
        for p, group in grouped_players:
            value = group_rating(p, group).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers = [
        "Name", "Team", "Pos", "Age", "Ovr", "Pot", "G", "MP",
        ("Contract", "col-basic"), ("PTS", "col-basic"), ("TRB", "col-basic"), ("AST", "col-basic"),
        ("TS%", "col-adv"), ("USG%", "col-adv"), ("ORtg", "col-adv"), ("DRtg", "col-adv"),
        ("OBPM", "col-adv"), ("DBPM", "col-adv"), ("BPM", "col-adv"), ("VORP", "col-adv"),
        ("Value", "col-adv"),
        ("PTS/36", "col-p36"), ("TRB/36", "col-p36"), ("AST/36", "col-p36"),
        ("STL/36", "col-p36"), ("BLK/36", "col-p36"), ("TOV/36", "col-p36"),
    ]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "col-rate group-start" if key in RATING_GROUP_STARTS else "col-rate"))
    rows = []
    for p, group in grouped_players:
        rating = group_rating(p, group)
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
        obpm = safe_float(stat.get("obpm"), 0.0)
        dbpm = safe_float(stat.get("dbpm"), 0.0)
        if group == "fa":
            team_cell = td('<span class="muted">FA</span>', sort="FA")
        elif group == "draft":
            draft_year = (p.get("draft") or {}).get("year")
            label = f"{draft_year} Draft" if isinstance(draft_year, int) else "Draft"
            team_cell = td(f'<span class="muted">{esc(label)}</span>', sort=draft_year if isinstance(draft_year, int) else "Draft")
        else:
            team_cell = td(team_label(p.get("tid"), teams_by_tid, "../"), sort=team_label(p.get("tid"), teams_by_tid, as_link=False))
        cells = [
            td(player_link(p, "../", show_number=False), sort=player_name(p), cls="name-cell"),
            team_cell,
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
            td(fmt_pct(ts_pct(stat)), sort=ts_pct(stat), cls="col-adv"),
            td(fmt_number(stat.get("usgp"), 1), sort=stat.get("usgp"), cls="col-adv"),
            td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg"), cls="col-adv"),
            td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg"), cls="col-adv"),
            td(fmt_number(obpm, 1), sort=obpm, cls="col-adv"),
            td(fmt_number(dbpm, 1), sort=dbpm, cls="col-adv"),
            td(fmt_number(obpm + dbpm, 1), sort=obpm + dbpm, cls="col-adv"),
            td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp"), cls="col-adv"),
            td(fmt_number(p.get("value"), 1), sort=p.get("value"), cls="col-adv"),
            td(fmt_number(per36(stat, "pts"), 1), sort=per36(stat, "pts"), cls="col-p36"),
            td(fmt_number(per36_trb(stat), 1), sort=per36_trb(stat), cls="col-p36"),
            td(fmt_number(per36(stat, "ast"), 1), sort=per36(stat, "ast"), cls="col-p36"),
            td(fmt_number(per36(stat, "stl"), 1), sort=per36(stat, "stl"), cls="col-p36"),
            td(fmt_number(per36(stat, "blk"), 1), sort=per36(stat, "blk"), cls="col-p36"),
            td(fmt_number(per36(stat, "tov"), 1), sort=per36(stat, "tov"), cls="col-p36"),
        ]
        for key, _ in TEAM_RATING_RANK_KEYS:
            value = rating.get(key)
            lo, hi = rating_ranges.get(key, (0.0, 0.0))
            cls = "col-rate group-start" if key in RATING_GROUP_STARTS else "col-rate"
            cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
        hidden_cls = "" if group == "roster" else " class=\"group-hidden\""
        rows.append(f'<tr data-group="{group}"{hidden_cls}>{"".join(cells)}</tr>')

    palette_teams = sorted((t for t in teams if t.get("tid") is not None and not t.get("disabled")), key=lambda t: team_abbrev(t))
    team_colors = {team_abbrev(t): TEAM_PALETTE[i % len(TEAM_PALETTE)] for i, t in enumerate(palette_teams)}
    chart_players = []
    # Rostered players plus free agents who logged games this season (the loop drops anyone
    # with 0 GP); FAs are colored by the team they actually played for (from the stat row).
    chart_pool = sorted_players + [p for p in players if p.get("tid") == FREE_AGENT_TID]
    for p in chart_pool:
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
            "ovr": rating.get("ovr"), "pot": rating.get("pot"), "gp": gp,
        }
        clean = {}
        for key, value in values.items():
            number = safe_float(value, float("nan"))
            clean[key] = round(number, 2) if math.isfinite(number) and value is not None else None
        color_tid = safe_int(p.get("tid"), -1)
        if color_tid < 0:
            color_tid = safe_int(stat.get("tid"), -1)
        chart_players.append({
            "name": player_name(p),
            "team": team_abbrev_for_tid(color_tid, teams_by_tid),
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
          <label class="select-label">Min GP
            <input type="number" data-chart-mingp value="36" min="0" step="1">
          </label>
          <label class="select-label check-label">Labels
            <input type="checkbox" data-chart-labels checked>
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
        <p class="muted">{len(sorted_players)} rostered · {len(fa_players)} free agents · {len(prospects)} draft prospects · deeper signing tools in the <a href="../free-agency.html">Free Agency</a> tab</p>
      </div>
      <div>
        <a class="button-link compare-cta" href="../compare.html">⇄ Compare Players</a>
      </div>
    </section>
    {chart_card}
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="players-index" placeholder="Filter players…" aria-label="Filter players">
        <div class="view-toggle group-toggle" data-group-toggle="players-index" role="group" aria-label="Player groups">
          <button type="button" class="active" data-group="roster">On teams</button>
          <button type="button" data-group="fa">Free agents</button>
          <button type="button" data-group="draft">Draft class</button>
        </div>
        <div class="view-toggle" data-view-toggle="players-index">
          <button type="button" class="active" data-view="basic">Per Game</button>
          <button type="button" data-view="p36">Per 36</button>
          <button type="button" data-view="adv">Advanced</button>
          <button type="button" data-view="rate">Ratings</button>
        </div>
      </div>
      {table_html(headers, rows, table_id="players-index", empty_message="No players found.", pos_filter=True)}
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


def render_player_hero(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int, start_season: int, compact: bool = False) -> str:
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
    if compact:
        # Sub-page header: just the essentials, since the full bio lives on Overview.
        details = "".join([
            detail_item("Team", team_html),
            detail_item("Position", esc(rating.get("pos", "—"))),
            detail_item("Age", age(player, season)),
            detail_item("Contract", fmt_contract(player)),
            detail_item("Injury", injury_html(player)),
        ])
    else:
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
      <div class="rating-panel{'' if compact else ' full-rating-panel'}">
        <div class="rating-topline">
          <div class="big-rating"><span>Overall</span><strong>{rating_delta_html(player, 'ovr', rating)}</strong></div>
          <div class="big-rating"><span>Potential</span><strong>{rating_delta_html(player, 'pot', rating)}</strong></div>
        </div>
        {'' if compact else f'<div class="rating-groups">{"".join(rating_groups_html)}</div><div class="awards-strip">{awards_html}</div>'}
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
                    "tid": own.get("tid"),
                    "opp_tid": opp.get("tid"),
                    "home": own_key == "home_box",
                    "team_pts": own.get("pts"),
                    "opp_pts": opp.get("pts"),
                    "box": box,
                    "overtimes": safe_int(game.get("overtimes")),
                    "playoffs": bool(game.get("playoffs")),
                })
    for entries in logs.values():
        entries.sort(key=game_sort_key)
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
    if len(ratings) < 1:
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


def power_ranking_bump_html(league_proj):
    """Projected Power Rankings -- the page centerpiece bump chart.

    Each team is a line tracing its league RANK (y-axis, 1 at top .. n_teams
    at bottom) across the projected seasons (x-axis), drawn in the team's own
    color, with a node dot at each season and the team abbrev labeled at both
    the left (start) and right (end) ends. Crossovers show who overtakes whom.

    The full chart is rendered statically in SVG (progressive enhancement) --
    it is fully meaningful with NO JavaScript. An embedded JSON blob
    (<script id="bump-data">) plus the JS module marked "power ranking bump"
    add line/label/chip highlighting (dim the rest) and a hover tooltip with
    that season's rank, projected strength (p50), and projected record
    (round(win_pct * num_games)). A legend of colored team chips lets the
    reader find a team. Rank ties are handled upstream (stable p50 order in
    ``ranks``); end labels are de-overlapped (clamped apart, with leaders).

    Returns "" when league_proj is None or fewer than 2 teams / seasons.
    Never raises.
    """
    if not league_proj:
        return ""
    teams = league_proj.get("teams") or []
    seasons = [safe_int(s) for s in (league_proj.get("seasons") or [])]
    num_games = [safe_int(g) for g in (league_proj.get("num_games") or [])]
    n_teams = safe_int(league_proj.get("n_teams"), len(teams))
    if len(teams) < 2 or len(seasons) < 2:
        return ""

    n_seasons = len(seasons)
    # Defensive: pad num_games to the season count.
    if len(num_games) < n_seasons:
        num_games = num_games + [num_games[-1] if num_games else 0] * (n_seasons - len(num_games))

    rows = max(n_teams, len(teams))

    # ---- Geometry (viewBox units) -------------------------------------
    # Left/right gutters hold the start/end abbrev labels.
    ML, MR = 76.0, 58.0
    MT, MB = 30.0, 26.0
    row_h = 34.0
    col_w = 92.0
    plot_w = col_w * (n_seasons - 1)
    plot_h = row_h * (rows - 1)
    width = ML + plot_w + MR
    height = MT + plot_h + MB

    def xs(i):
        return ML + (plot_w * (i / (n_seasons - 1)) if n_seasons > 1 else 0.0)

    def yr(rank):
        # rank 1 -> top row, rank == rows -> bottom row.
        r = min(max(safe_int(rank, 1), 1), rows)
        return MT + (r - 1) * row_h

    # Stable team order for deterministic z-stacking / legend: by current rank
    # (ranks[0], already tie-broken upstream), then tid.
    ordered = sorted(teams, key=lambda t: (safe_int((t.get("ranks") or [rows])[0], rows),
                                           safe_int(t.get("tid"), 0)))

    # ---- Background grid ---------------------------------------------
    grid = []
    for r in range(1, rows + 1):
        y = MT + (r - 1) * row_h
        grid.append('<line class="bump-rowline" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                    % (ML, y, ML + plot_w, y))
        grid.append('<text class="bump-rankaxis" x="%.1f" y="%.1f">%d</text>'
                    % (ML - 56.0, y + 3.0, r))
    for i, s in enumerate(seasons):
        x = xs(i)
        grid.append('<line class="bump-collline" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                    % (x, MT - 8.0, x, MT + plot_h))
        cap = "Now" if i == 0 else ("+%d" % i)
        grid.append('<text class="bump-seasontick" x="%.1f" y="%.1f">%s</text>'
                    % (x, MT - 14.0, esc(cap)))
        grid.append('<text class="bump-seasonyr" x="%.1f" y="%.1f">%s</text>'
                    % (x, height - 8.0, esc(str(s))))

    # ---- Team lines ---------------------------------------------------
    payload_teams = []
    lines = []
    start_labels = []
    end_labels = []

    for t in ordered:
        tid = safe_int(t.get("tid"), 0)
        color = t.get("color") or "#939ca7"
        if not (isinstance(color, str) and color.startswith("#")):
            color = "#939ca7"
        abbrev = esc(t.get("abbrev") or "")
        name = esc(t.get("name") or t.get("abbrev") or "")
        url = t.get("url") or ""
        ranks = [safe_int(v, rows) for v in (t.get("ranks") or [])][:n_seasons]
        p50 = [safe_float(v) for v in (t.get("p50") or [])][:n_seasons]
        win_pct = [safe_float(v) for v in (t.get("win_pct") or [])][:n_seasons]
        if len(ranks) < n_seasons:
            ranks = ranks + [rows] * (n_seasons - len(ranks))

        pts = [(xs(i), yr(ranks[i])) for i in range(n_seasons)]
        poly = " ".join("%.1f,%.1f" % p for p in pts)

        # A halo polyline (base fill = --bg, never relying on color-mix) keeps
        # the colored identity line legible over crossings on any theme.
        lines.append(
            '<g class="bump-team" data-bump-team data-tid="%d" style="--bump-color:%s">'
            '<polyline class="bump-halo" points="%s"/>'
            '<polyline class="bump-line" points="%s"/>'
            % (tid, esc(color), poly, poly))
        for i, (px, py) in enumerate(pts):
            lines.append('<circle class="bump-node" cx="%.1f" cy="%.1f" r="3.3" data-i="%d"/>'
                         % (px, py, i))
        # Wide invisible hit line for easy hovering + click-through to the team
        # page (wrapped in an SVG <a> so it works without JS).
        if url:
            lines.append('<a href="%s" class="bump-link" aria-label="%s">'
                         '<polyline class="bump-hit" points="%s"/></a>'
                         % (esc(url), name, poly))
        else:
            lines.append('<polyline class="bump-hit" points="%s"/>' % poly)
        lines.append('</g>')

        start_labels.append((yr(ranks[0]), tid, color, abbrev))
        end_labels.append((yr(ranks[-1]), tid, color, abbrev))

        records = [int(round(win_pct[i] * num_games[i])) if i < len(win_pct) else 0
                   for i in range(n_seasons)]
        payload_teams.append({
            "tid": tid, "abbrev": t.get("abbrev") or "", "name": t.get("name") or "",
            "color": color, "url": url, "ranks": ranks,
            "p50": [round(v, 1) for v in (p50 + [0.0] * n_seasons)[:n_seasons]],
            "rec": records, "games": num_games[:n_seasons],
        })

    # ---- End-label de-overlap (clamp >= gap apart, add leader if moved) --
    def declutter(labels):
        gap = 13.0
        labels = sorted(labels, key=lambda L: L[0])
        out = []
        prev_y = -1e9
        for (y, tid, color, abbrev) in labels:
            ny = max(y, prev_y + gap)
            out.append((y, ny, tid, color, abbrev))
            prev_y = ny
        return out

    label_svg = []
    for (anchor_y, ny, tid, color, abbrev) in declutter(start_labels):
        label_svg.append(
            '<text class="bump-endlabel bump-endlabel--start" data-bump-label data-tid="%d" '
            'x="%.1f" y="%.1f" style="--bump-color:%s">%s</text>'
            % (tid, ML - 9.0, ny + 3.0, esc(color), abbrev))
        if abs(ny - anchor_y) > 1.0:
            label_svg.append('<line class="bump-leader" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                             % (ML - 5.0, anchor_y, ML - 3.0, ny))
    for (anchor_y, ny, tid, color, abbrev) in declutter(end_labels):
        label_svg.append(
            '<text class="bump-endlabel bump-endlabel--end" data-bump-label data-tid="%d" '
            'x="%.1f" y="%.1f" style="--bump-color:%s">%s</text>'
            % (tid, ML + plot_w + 9.0, ny + 3.0, esc(color), abbrev))
        if abs(ny - anchor_y) > 1.0:
            label_svg.append('<line class="bump-leader" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                             % (ML + plot_w + 5.0, anchor_y, ML + plot_w + 3.0, ny))

    # ---- Legend chips (colored, intentionally quiet) -------------------
    legend = []
    for t in ordered:
        tid = safe_int(t.get("tid"), 0)
        color = t.get("color") or "#939ca7"
        if not (isinstance(color, str) and color.startswith("#")):
            color = "#939ca7"
        abbrev = esc(t.get("abbrev") or "")
        name = esc(t.get("name") or "")
        legend.append(
            '<button type="button" class="bump-chip" data-bump-chip data-tid="%d" '
            'style="--bump-color:%s" title="%s" aria-label="Highlight %s" aria-pressed="false">'
            '<span class="bump-chip-dot"></span>'
            '<span class="bump-chip-ab">%s</span>'
            '</button>'
            % (tid, esc(color), name, name, abbrev))

    ref = league_proj.get("league") or {}
    sub_bits = []
    ref_season = seasons[0] if seasons else ""
    if ref.get("contender") is not None:
        sub_bits.append("%s contender ≈ %d OVR" % (ref_season, int(round(safe_float(ref.get("contender"))))))
    if ref.get("avg") is not None:
        sub_bits.append("%s league avg ≈ %d" % (ref_season, int(round(safe_float(ref.get("avg"))))))
    sub = " · ".join(sub_bits)

    payload = {
        "seasons": seasons,
        "rows": rows,
        "g": {"ml": ML, "mr": MR, "mt": MT, "mb": MB,
              "rowh": row_h, "colw": col_w, "pw": plot_w, "ph": plot_h,
              "w": width, "h": height},
        "teams": payload_teams,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    n_label = "%d teams" % len(teams)

    summary_rows = []
    for t in payload_teams:
        ranks = [safe_int(r, rows) for r in t.get("ranks", [])]
        if not ranks:
            continue
        start_rank = ranks[0]
        end_rank = ranks[-1]
        best_rank = min(ranks)
        games = safe_int((t.get("games") or [0])[-1], 0)
        wins = safe_int((t.get("rec") or [0])[-1], 0)
        rec = "%d-%d" % (wins, max(0, games - wins)) if games > 0 else "n/a"
        move = start_rank - end_rank
        move_label = "Up %d" % move if move > 0 else "Down %d" % (-move) if move < 0 else "Steady"
        color = esc(t.get("color") or "#939ca7")
        url = esc(t.get("url") or "#")
        summary_rows.append(
            '<a class="bump-summary-row" href="%s" style="--bump-color:%s">'
            '<span class="bump-chip-dot"></span>'
            '<strong>%s</strong>'
            '<span>Now #%d</span>'
            '<span>Best #%d</span>'
            '<span>%s #%d</span>'
            '<span>%s %s</span>'
            '</a>'
            % (
                url, color, esc(t.get("abbrev") or t.get("name") or "Team"),
                start_rank, best_rank, move_label, end_rank,
                esc(str(seasons[-1])), esc(rec),
            )
        )

    return (
        '<section class="card bump-card">'
        '<div class="section-title-row">'
        '<h2>Projected Power Rankings</h2>'
        '<span class="count-pill">%s</span>'
        '</div>'
        '<p class="muted small-copy bump-sub">Each line follows a team’s league rank if every '
        'roster simply ages forward — no trades, draft, or signings. Crossovers are where one '
        'core overtakes another.%s</p>'
        '<div class="bump-legend" data-bump-legend>%s</div>'
        '<div class="chart-wrap bump-wrap" data-bump>'
        '<svg viewBox="0 0 %g %g" class="bump-chart" role="img" '
        'aria-label="Projected league power rankings over %d seasons" '
        'preserveAspectRatio="xMidYMid meet">'
        '<text class="bump-axislabel bump-axislabel--top" x="%.1f" y="%.1f">best</text>'
        '<text class="bump-axislabel bump-axislabel--bot" x="%.1f" y="%.1f">worst</text>'
        '%s%s%s'
        '</svg>'
        '<div class="chart-tooltip bump-tooltip" data-bump-tooltip hidden></div>'
        '</div>'
        '<div class="bump-summary">%s</div>'
        '<script type="application/json" id="bump-data">%s</script>'
        '</section>'
        % (n_label,
           (" " + sub if sub else ""),
           "".join(legend),
           width, height, n_seasons,
           ML - 56.0, MT - 14.0,
           ML - 56.0, MT + plot_h + 18.0,
           "".join(grid), "".join(lines), "".join(label_svg),
           "".join(summary_rows),
           payload_json)
    )


def projected_standings_html(league_proj: dict[str, Any] | None) -> str:
    """Projected Standings detail table for the league projections page.

    Rows = teams (current-rank order); columns = the 7 projected seasons. Each
    cell shows that team's projected strength (p50, rounded int) with a small
    league-rank badge for that season, plus an estimated record
    (round(win_pct * numGames)) on a secondary line / hover title. Cells are
    softly tinted by strength relative to the current-league avg/contender
    reference lines. The first season is the current-roster anchor, then the
    same roster ages forward with no trades, draft, or re-signings. Returns ""
    when no projection is available or fewer than two teams. Never raises.
    """
    if not league_proj:
        return ""
    seasons = [safe_int(s) for s in (league_proj.get("seasons") or [])]
    entries = list(league_proj.get("teams") or [])
    if len(seasons) < 1 or len(entries) < 2:
        return ""
    n_seasons = len(seasons)
    num_games = [safe_int(g) for g in (league_proj.get("num_games") or [])]
    league = league_proj.get("league") or {}
    avg = safe_float(league.get("avg")) if league.get("avg") is not None else None
    contender = safe_float(league.get("contender")) if league.get("contender") is not None else None

    # Rows sorted by current (seasons[0]) rank ascending; tie-break by current OVR.
    def _cur_rank(e: dict[str, Any]) -> int:
        r = e.get("ranks") or []
        return safe_int(r[0]) if r else 999
    rows_data = sorted(entries, key=lambda e: (_cur_rank(e), -safe_int(e.get("current"))))

    # Map a strength value to a tint relative to the league references. Always
    # emit a plain fallback before the color-mix declaration.
    def _tint(val: float) -> str:
        if avg is None or contender is None or contender <= avg:
            return ""  # no usable reference -> no tint
        span = contender - avg
        if val >= avg:
            frac = min(1.0, (val - avg) / span)
            pct = int(round(4 + frac * 12))  # 4%..16% toward --good
            return ("background: var(--panel-2);"
                    f"background: color-mix(in srgb, var(--good) {pct}%, transparent);")
        frac = min(1.0, (avg - val) / span)
        pct = int(round(4 + frac * 12))  # 4%..16% toward --bad
        return ("background: var(--panel-2);"
                f"background: color-mix(in srgb, var(--bad) {pct}%, transparent);")

    # Header: team column + one column per season (label current vs projected).
    head_cells = ['<th class="pstand-team-h" scope="col">Team</th>']
    for si, s in enumerate(seasons):
        anchor = " pstand-now" if si == 0 else ""
        tag = "now" if si == 0 else "proj"
        sub = "now" if si == 0 else "proj"
        head_cells.append(
            f'<th class="pstand-yr{anchor}" scope="col">'
            f'<span class="pstand-yr-num">{esc(s)}</span>'
            f'<span class="pstand-yr-tag pstand-yr-tag--{tag}">{esc(sub)}</span>'
            f"</th>"
        )
    head_html = "".join(head_cells)

    body_rows = []
    mobile_cards = []
    for e in rows_data:
        color = esc(e.get("color") or "#5b9dff")
        name = esc(e.get("name") or e.get("abbrev") or "Team")
        abbrev = esc(e.get("abbrev") or "")
        url = esc(e.get("url") or "#")
        p50 = e.get("p50") or []
        ranks = e.get("ranks") or []
        win_pct = e.get("win_pct") or []

        team_cell = (
            f'<th class="pstand-team" scope="row">'
            f'<a class="pstand-name" href="{url}">'
            f'<span class="pstand-dot" style="background:{color}"></span>'
            f'<span class="pstand-name-txt">{name}</span>'
            f'<span class="pstand-abbr">{abbrev}</span>'
            f"</a></th>"
        )

        cells = [team_cell]
        mobile_bits = []
        for si in range(n_seasons):
            raw = safe_float(p50[si]) if si < len(p50) else 0.0
            val = int(round(raw))
            rank = safe_int(ranks[si]) if si < len(ranks) else 0
            ng = num_games[si] if si < len(num_games) else 0
            wp = safe_float(win_pct[si]) if si < len(win_pct) else 0.0
            if ng > 0:
                wins = int(round(wp * ng))
                losses = max(0, ng - wins)
                rec = f"{wins}-{losses}"
            else:
                rec = f"{int(round(wp * 100))}%"
            anchor = " pstand-now" if si == 0 else ""
            rank_cls = " pstand-rank--hi" if 1 <= rank <= 3 else ""
            title = f"{name} — {seasons[si]}: median team OVR {val}, rank #{rank}, est. record {rec}"
            cells.append(
                f'<td class="pstand-cell{anchor}" style="{_tint(raw)}" title="{esc(title)}">'
                f'<span class="pstand-val">{esc(val)}</span>'
                f'<span class="pstand-rank{rank_cls}">#{esc(rank)}</span>'
                f'<span class="pstand-rec">{esc(rec)}</span>'
                f"</td>"
            )
            mobile_bits.append(
                f'<span class="pstand-mobile-season">'
                f'<em>{esc(seasons[si])}</em>'
                f'<strong>{esc(val)}</strong>'
                f'<small>#{esc(rank)} · {esc(rec)}</small>'
                f'</span>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
        mobile_cards.append(
            f'<article class="pstand-mobile-card">'
            f'<a class="pstand-name" href="{url}"><span class="pstand-dot" style="background:{color}"></span>'
            f'<span class="pstand-name-txt">{name}</span><span class="pstand-abbr">{abbrev}</span></a>'
            f'<div class="pstand-mobile-seasons">{"".join(mobile_bits)}</div>'
            f'</article>'
        )

    body_html = "\n".join(body_rows)
    mobile_html = "\n".join(mobile_cards)
    n_proj = max(0, n_seasons - 1)
    caption = (
        "Continuity scenario: every roster ages forward as-is — no trades, "
        "draft, or re-signings, so the signal is relative order. Records are model "
        "estimates from projected round-robin win rate."
    )

    return f"""
    <section class="card pstand" id="projected-standings">
      <div class="section-title-row">
        <h2>Projected Standings</h2>
        <span class="count-pill">{esc(n_proj)} seasons ahead</span>
      </div>
      <p class="muted small-copy pstand-caption">{esc(caption)}</p>
      <div class="table-wrap pstand-wrap">
        <table class="pstand-table">
          <caption class="sr-only">Projected standings continuity table by team and season</caption>
          <thead><tr>{head_html}</tr></thead>
          <tbody>
            {body_html}
          </tbody>
        </table>
      </div>
      <div class="pstand-mobile" aria-label="Projected standings compact cards">
        {mobile_html}
      </div>
      <div class="scout-tags pstand-legend" aria-hidden="true">
        <span class="scout-tag scout-tag--good">at / above contender</span>
        <span class="scout-tag scout-tag--neutral">near {esc(seasons[0])} league avg</span>
        <span class="scout-tag scout-tag--bad">below {esc(seasons[0])} league avg</span>
      </div>
    </section>
    """


def contract_horizon_html(team: dict[str, Any], roster: list[dict[str, Any]], season: int,
                          team_proj: dict[str, Any] | None = None) -> str:
    """A "Contract Horizon" Gantt timeline of guaranteed-core decline.

    One row per rostered player (sorted by current OVR desc, capped at 12 with a
    "+N more" note), each a horizontal bar spanning from the current season to the
    player's ``contract.exp`` year on a shared season axis (current .. current+6,
    matching the trajectory chart). Bars are colored by ``--team-primary`` and
    faded for lower-OVR players. A subtle per-season column shading plus a footer
    "under contract" count make the roster thinning legible (the count mirrors
    ``team_proj["core_counts"]`` when ``team_proj`` is supplied). Contracts that
    run past the window show a "->{exp}" overflow indicator. Returns "" on empty
    roster. Never raises.
    """
    if not roster:
        return ""

    season = safe_int(season)
    s_max = season + PROJ_SEASONS_AHEAD
    n_cols = PROJ_SEASONS_AHEAD + 1  # current .. current+6 inclusive
    seasons_axis = list(range(season, s_max + 1))

    # Collect rows: (ovr, name, exp, beyond) for active players, OVR desc.
    entries: list[tuple[int, str, int, bool]] = []
    for p in roster:
        if p.get("retiredYear") is not None:
            continue
        ovr = _player_current_ovr(p, season)
        if ovr is None:
            continue
        contract = p.get("contract") or {}
        # Missing exp -> treat as expiring this season (floor at current season).
        exp = safe_int(contract.get("exp"), season)
        if exp < season:
            exp = season
        beyond = exp > s_max
        entries.append((ovr, player_name(p), exp, beyond))
    if not entries:
        return ""

    entries.sort(key=lambda e: (-e[0], e[1]))
    total = len(entries)
    MAX_ROWS = 12
    shown = entries[:MAX_ROWS]
    extra = total - len(shown)

    ovrs = [e[0] for e in shown]
    hi_ovr = max(ovrs)
    lo_ovr = min(ovrs)

    # Per-season count of ALL eligible roster players still under contract (drives
    # the column shading; not limited to the <=12 displayed rows).
    roster_counts = [sum(1 for _o, _n, exp, _b in entries if exp >= s) for s in seasons_axis]

    # Footer: prefer team_proj["core_counts"] (full-roster truth) when present.
    core_counts = None
    if team_proj is not None:
        cc = team_proj.get("core_counts")
        if isinstance(cc, (list, tuple)) and len(cc) >= n_cols:
            core_counts = [safe_int(cc[i], 0) for i in range(n_cols)]
    footer_counts = core_counts if core_counts is not None else roster_counts
    footer_label = "Under contract (full roster)" if core_counts is not None else "Under contract"

    # --- SVG geometry (shared season axis across header, bars, footer) ---------
    width = 680.0
    ML, MR = 168.0, 16.0          # left gutter for labels, right margin
    plot_w = width - ML - MR
    col_w = plot_w / n_cols
    row_h = 22.0
    row_gap = 4.0
    head_h = 20.0
    foot_h = 26.0
    top_pad = head_h + 6.0
    n_rows = len(shown)
    plot_h = n_rows * row_h + max(0, n_rows - 1) * row_gap
    height = top_pad + plot_h + foot_h + 8.0

    def col_x(i: int) -> float:
        return ML + i * col_w

    parts: list[str] = []

    # Column shading: deepen as the roster thins (fewer players under contract).
    max_cnt = max(roster_counts) or 1
    for i, s in enumerate(seasons_axis):
        x = col_x(i)
        frac = roster_counts[i] / max_cnt
        shade = 0.04 + (1.0 - frac) * 0.10
        parts.append(
            f'<rect x="{x:.1f}" y="{top_pad:.1f}" width="{col_w:.1f}" height="{plot_h:.1f}" '
            f'class="tcon-col" style="fill:color-mix(in srgb, var(--muted) {shade * 100:.0f}%, transparent)"/>'
        )
        parts.append(
            f'<text x="{x + col_w / 2:.1f}" y="{head_h - 4:.1f}" class="tcon-axis" text-anchor="middle">{esc(s)}</text>'
        )
        parts.append(
            f'<line x1="{x:.1f}" y1="{top_pad:.1f}" x2="{x:.1f}" y2="{top_pad + plot_h:.1f}" class="tcon-gridline"/>'
        )
    parts.append(
        f'<line x1="{col_x(n_cols):.1f}" y1="{top_pad:.1f}" x2="{col_x(n_cols):.1f}" '
        f'y2="{top_pad + plot_h:.1f}" class="tcon-gridline"/>'
    )

    # Bars.
    bar_h = row_h - 6.0
    span_ovr = max(1, hi_ovr - lo_ovr)
    for ridx, (ovr, name, exp, beyond) in enumerate(shown):
        ry = top_pad + ridx * (row_h + row_gap)
        bar_y = ry + 3.0
        # Bar spans from current season to exp (clamped to the window edge).
        end_i = min(n_cols, exp - season + 1)
        end_i = max(1, end_i)
        bx = col_x(0)
        bw = max(col_w * 0.55, col_x(end_i) - bx)  # always show at least a stub
        # Fade lower-OVR players: opacity 0.45..1.0 across the shown OVR range.
        op = 0.45 + (ovr - lo_ovr) / span_ovr * 0.55
        exp_txt = f"→{esc(exp)}" if beyond else esc(exp)
        title = f"{name} · OVR {ovr} · through {exp}" + (" (beyond window)" if beyond else "")
        parts.append(
            f'<g class="tcon-row">'
            f'<title>{esc(title)}</title>'
            f'<rect x="{bx:.1f}" y="{bar_y:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" rx="3" '
            f'class="tcon-bar" style="opacity:{op:.2f}"/>'
        )
        if beyond:
            ax = col_x(n_cols)
            parts.append(
                f'<path d="M{ax - 1:.1f},{bar_y + bar_h / 2 - 4:.1f} l6,4 l-6,4 z" class="tcon-overflow"/>'
            )
        chip_x = bx + bw - 5.0
        parts.append(
            f'<text x="{chip_x:.1f}" y="{bar_y + bar_h / 2 + 3.5:.1f}" class="tcon-expiry" '
            f'text-anchor="end">{exp_txt}</text>'
        )
        parts.append(
            f'<text x="{ML - 10:.1f}" y="{bar_y + bar_h / 2 + 4:.1f}" class="tcon-name" text-anchor="end">'
            f'{esc(name)} <tspan class="tcon-ovr">{ovr}</tspan></text>'
        )
        parts.append('</g>')

    # Footer: under-contract count per season.
    fy = top_pad + plot_h + 4.0
    parts.append(
        f'<text x="{ML - 10:.1f}" y="{fy + foot_h / 2 + 1:.1f}" class="tcon-foot-label" text-anchor="end">{esc(footer_label)}</text>'
    )
    n_footer = min(n_cols, len(footer_counts))
    for i in range(n_footer):
        x = col_x(i) + col_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{fy + foot_h / 2 + 1:.1f}" class="tcon-foot-count" text-anchor="middle">{esc(footer_counts[i])}</text>'
        )

    truncated = (
        f'<p class="muted small-copy tcon-note">+{extra} more {"player" if extra == 1 else "players"} not shown (lowest current overall).</p>'
        if extra > 0 else ""
    )

    return f"""
    <section class="card" id="contract-horizon">
      <div class="section-title-row">
        <h2>Contract Horizon</h2>
        <span class="muted small-copy">Bars run from {esc(season)} to each contract's final season</span>
      </div>
      <div class="chart-wrap tcon-wrap">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="tcon-chart" role="img" aria-label="Contract expiry timeline for the roster, {esc(season)} to {esc(s_max)}">
          {''.join(parts)}
        </svg>
      </div>
      <p class="muted small-copy tcon-caption">Each bar covers the seasons a player is under contract; the footer counts players locked in per season. As bars expire, the guaranteed core thins &mdash; the gap to a re-signed roster is the value of that expiring talent.</p>
      {truncated}
    </section>
    """


def development_chart_html(player: dict[str, Any], season: int, proj: dict[str, Any] | None = None) -> str:
    """Historical overall/potential plus a Monte Carlo overall projection.

    Renders a static SVG fan chart (always visible -- progressive enhancement);
    site.js layers an interactive hover readout on top from the embedded JSON.
    Falls back to the static :func:`ratings_progress_svg` when no projection is
    available. ``proj`` may be passed in (computed once per player by the caller)
    to avoid recomputing the simulation for each projection-backed section.
    """
    if proj is None:
        proj = _player_projection(player, season)
    if proj is None:
        return ratings_progress_svg(player)

    sim = proj["sim"]
    cur_season = proj["cur_season"]

    hist = sorted(
        [r for r in player.get("ratings", [])
         if isinstance(r.get("season"), int) and r["season"] <= cur_season
         and r.get("ovr") is not None],
        key=lambda r: r["season"],
    )
    if not hist:
        return ratings_progress_svg(player)

    hist_seasons = [int(r["season"]) for r in hist]
    hist_ovr = [safe_float(r.get("ovr")) for r in hist]
    # Missing potential falls back to the overall, so a malformed upstream row
    # never renders as a spurious crash-to-zero on the line (pot is >= ovr).
    hist_pot = [safe_float(r.get("pot")) if r.get("pot") is not None
                else safe_float(r.get("ovr")) for r in hist]

    proj_seasons = [int(s) for s in sim["seasons"]]
    p10 = [round(float(v), 1) for v in sim["ovr"]["p10"]]
    p25 = [round(float(v), 1) for v in sim["ovr"]["p25"]]
    p50 = [round(float(v), 1) for v in sim["ovr"]["p50"]]
    p75 = [round(float(v), 1) for v in sim["ovr"]["p75"]]
    p90 = [round(float(v), 1) for v in sim["ovr"]["p90"]]
    pot_peak = int(sim["pot_p75_peak"])

    s_min = min(hist_seasons + proj_seasons)
    s_max = max(hist_seasons + proj_seasons)
    vals = hist_ovr + hist_pot + p10 + p90 + [float(pot_peak)]
    lo = max(0.0, math.floor(min(vals)) - 4)
    hi = min(100.0, math.ceil(max(vals)) + 4)
    if hi <= lo:
        hi = lo + 1

    width, height = 660, 210
    ml, mr, mt, mb = 34, 14, 12, 28
    plot_w, plot_h = width - ml - mr, height - mt - mb
    span = max(1, s_max - s_min)

    def xs(s: float) -> float:
        return ml + (s - s_min) / span * plot_w

    def yv(v: float) -> float:
        return mt + plot_h - (v - lo) / (hi - lo) * plot_h

    grid: list[str] = []
    ystep = 10 if (hi - lo) > 30 else 5
    ytick = math.ceil(lo / ystep) * ystep
    while ytick <= hi:
        gy = yv(ytick)
        grid.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w}" y2="{gy:.1f}" class="chart-grid"/>')
        grid.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{int(ytick)}</text>')
        ytick += ystep
    xstep = max(1, round((s_max - s_min + 1) / 9))
    labeled: set[int] = set()
    s = s_min
    while s <= s_max:
        labeled.add(s)
        s += xstep
    labeled.update({cur_season, s_max})
    for s in sorted(labeled):
        grid.append(f'<text x="{xs(s):.1f}" y="{height - 8}" class="chart-tick" text-anchor="middle">{s}</text>')

    def poly(seasons: list[int], values: list[float], cls: str, titles: list[str] | None = None) -> str:
        pts = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(seasons, values))
        dots = "".join(
            f'<circle cx="{xs(s):.1f}" cy="{yv(v):.1f}" r="3" class="{cls}-dot">'
            f'<title>{titles[i] if titles else f"{s}: {int(round(v))}"}</title></circle>'
            for i, (s, v) in enumerate(zip(seasons, values))
        )
        return f'<polyline points="{pts}" class="{cls}"/>{dots}'

    def poly_hist(seasons: list[int], values: list[float], cls: str) -> str:
        # Like poly(), but breaks the line at gap years (consecutive seasons that
        # differ by more than 1) so missing seasons are not drawn as continuous
        # data. Dots are still placed on every real season.
        segments: list[list[int]] = []
        run: list[int] = []
        for i, s in enumerate(seasons):
            if run and s - seasons[i - 1] != 1:
                segments.append(run)
                run = []
            run.append(i)
        if run:
            segments.append(run)
        lines = "".join(
            f'<polyline points="{" ".join(f"{xs(seasons[i]):.1f},{yv(values[i]):.1f}" for i in seg)}" class="{cls}"/>'
            for seg in segments
        )
        dots = "".join(
            f'<circle cx="{xs(s):.1f}" cy="{yv(v):.1f}" r="3" class="{cls}-dot">'
            f'<title>{s}: {int(round(v))}</title></circle>'
            for s, v in zip(seasons, values)
        )
        return lines + dots

    # Confidence-band polygons (forward along the upper edge, back along the lower).
    def band(upper: list[float], lower: list[float], cls: str) -> str:
        fwd = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(proj_seasons, upper))
        back = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(reversed(proj_seasons), reversed(lower)))
        return f'<polygon points="{fwd} {back}" class="{cls}"/>'

    band80 = band(p90, p10, "proj-band-80")
    band50 = band(p75, p25, "proj-band-50")
    median = poly(
        proj_seasons, p50, "proj-median",
        titles=[f"{s}: {int(round(v))} proj" for s, v in zip(proj_seasons, p50)],
    )
    hist_pot_line = poly_hist(hist_seasons, hist_pot, "line-pot")
    hist_ovr_line = poly_hist(hist_seasons, hist_ovr, "line-ovr")
    divider = (
        f'<line x1="{xs(cur_season):.1f}" y1="{mt}" x2="{xs(cur_season):.1f}" '
        f'y2="{mt + plot_h}" class="proj-divider"/>'
    )

    pid = safe_int(player.get("pid"), 0)
    payload = {
        "cur": cur_season,
        "potPeak": pot_peak,
        "hist": {"s": hist_seasons,
                 "ovr": [round(v, 1) for v in hist_ovr],
                 "pot": [round(v, 1) for v in hist_pot]},
        "proj": {"s": proj_seasons, "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90},
        "g": {"ml": ml, "mt": mt, "pw": plot_w, "ph": plot_h,
              "lo": lo, "hi": hi, "smin": s_min, "smax": s_max, "w": width, "h": height},
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Development &amp; Projection</h2>
        <span class="muted small-copy"><span class="chart-key chart-key-ovr"></span> Overall · <span class="chart-key chart-key-pot"></span> Potential · <span class="chart-key proj-key-band"></span> Projection</span>
      </div>
      <div class="chart-wrap proj-wrap" data-proj-chart>
        <svg viewBox="0 0 {width} {height}" class="proj-chart" role="img" aria-label="Overall rating history and {PROJ_SEASONS_AHEAD}-season projection">
          {''.join(grid)}
          {band80}
          {band50}
          {median}
          {hist_pot_line}
          {hist_ovr_line}
          {divider}
          <line class="proj-hover-line" data-proj-hover-line y1="{mt}" y2="{mt + plot_h}" style="display:none"/>
          <circle class="proj-hover-dot" data-proj-hover-dot r="3.5" style="display:none"/>
        </svg>
        <div class="chart-tooltip" data-proj-tooltip hidden></div>
      </div>
      <p class="muted small-copy">Projected overall for the next {PROJ_SEASONS_AHEAD} seasons from {PROJ_N_SIMS:,} Monte Carlo simulations of the game's aging model — median with shaded 80% (P10–P90) and 50% (P25–P75) confidence bands. Engine potential ceiling ≈ {pot_peak}.</p>
      <script type="application/json" id="proj-data-{pid}">{payload_json}</script>
    </section>
    """


def subrating_grid_html(player, proj):
    """A 3-group grid of 15 compact "fan sparkline" mini-charts -- one per
    subrating. Each cell shows the rating label, the current value, a projected
    delta chip, and an inline SVG with the gap-broken historical line, the
    projected median, and the projected 80% (P10-P90) band, with a divider at
    the current season. Each mini-chart auto-scales its own y-axis. A single
    embedded JSON blob + small JS module syncs hover across all 15 charts.

    Returns "" when proj is None or data is insufficient. Never raises.
    """
    if proj is None:
        return ""
    sim = proj.get("sim") or {}
    subr = sim.get("subratings") or {}
    proj_seasons = [safe_int(s) for s in sim.get("seasons", [])]
    if len(proj_seasons) < 2 or not subr:
        return ""
    cur_season = safe_int(proj.get("cur_season"))

    rows = [r for r in player.get("ratings", [])
            if isinstance(r.get("season"), int) and r.get("season") <= cur_season]
    rows.sort(key=lambda r: r["season"])

    pid = safe_int(player.get("pid"), 0)

    # Geometry of each mini-chart (SVG viewBox units).
    W, H = 150.0, 46.0
    ML, MR, MT, MB = 3.0, 3.0, 4.0, 4.0
    PW, PH = W - ML - MR, H - MT - MB

    all_seasons = sorted(set([int(r["season"]) for r in rows] + proj_seasons))
    if not all_seasons:
        return ""
    s_min, s_max = all_seasons[0], all_seasons[-1]
    s_span = max(1, s_max - s_min)

    def xs(s):
        return ML + (float(s) - s_min) / s_span * PW

    cur_x = xs(cur_season)

    def render_cell(key):
        label = RATING_LABELS[key]
        band = subr.get(key)
        if not band:
            return None
        p10 = [safe_float(v) for v in band.get("p10", [])]
        p25 = [safe_float(v) for v in band.get("p25", [])]
        p50 = [safe_float(v) for v in band.get("p50", [])]
        p75 = [safe_float(v) for v in band.get("p75", [])]
        p90 = [safe_float(v) for v in band.get("p90", [])]
        n = min(len(p10), len(p25), len(p50), len(p75), len(p90), len(proj_seasons))
        if n < 2:
            return None
        p10, p25, p50, p75, p90 = p10[:n], p25[:n], p50[:n], p75[:n], p90[:n]
        pseasons = proj_seasons[:n]

        # Historical series for this rating (real rows so gap-years can break it).
        h_seasons, h_vals = [], []
        for r in rows:
            v = r.get(key)
            if v is None:
                continue
            h_seasons.append(int(r["season"]))
            h_vals.append(safe_float(v))

        # Current absolute value: the projection's index-0 median is the true
        # current rating; end value drives the delta chip.
        cur_val = p50[0]
        end_val = p50[-1]
        delta = int(round(end_val - cur_val))

        # Auto-scale y to this rating's own range over history+projection.
        yvals = list(h_vals) + p10 + p90
        lo = max(0.0, math.floor(min(yvals)) - 2)
        hi = min(100.0, math.ceil(max(yvals)) + 2)
        if hi <= lo:
            hi = lo + 1.0

        def yv(v):
            return MT + PH - (float(v) - lo) / (hi - lo) * PH

        # 80% confidence band polygon (forward upper, back along lower).
        fwd = " ".join("%.1f,%.1f" % (xs(s), yv(v)) for s, v in zip(pseasons, p90))
        back = " ".join("%.1f,%.1f" % (xs(s), yv(v))
                        for s, v in zip(reversed(pseasons), reversed(p10)))
        band_poly = '<polygon points="%s %s" class="subg-band"/>' % (fwd, back)

        # Projected median line.
        med_pts = " ".join("%.1f,%.1f" % (xs(s), yv(v)) for s, v in zip(pseasons, p50))
        median = '<polyline points="%s" class="subg-median"/>' % med_pts

        # Historical line, broken at gap years.
        hist_segs = []
        run = []
        for i, s in enumerate(h_seasons):
            if run and s - h_seasons[i - 1] != 1:
                hist_segs.append(run)
                run = []
            run.append(i)
        if run:
            hist_segs.append(run)
        hist_parts = []
        for seg in hist_segs:
            if len(seg) == 1:
                # A lone historical point (e.g. a rookie's single season) draws
                # nothing as a polyline, so anchor it with a small dot.
                i = seg[0]
                hist_parts.append('<circle cx="%.1f" cy="%.1f" r="1.6" class="subg-hist-dot"/>'
                                  % (xs(h_seasons[i]), yv(h_vals[i])))
            else:
                pts = " ".join("%.1f,%.1f" % (xs(h_seasons[i]), yv(h_vals[i])) for i in seg)
                hist_parts.append('<polyline points="%s" class="subg-hist"/>' % pts)
        hist_lines = "".join(hist_parts)

        divider = ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="subg-divider"/>'
                   % (cur_x, MT, cur_x, MT + PH))

        # Per-chart hover marker (line + dot, hidden until JS shows it).
        hover = ('<line class="subg-hline" y1="%.1f" y2="%.1f" style="display:none"/>'
                 '<circle class="subg-hdot" r="2.4" style="display:none"/>') % (MT, MT + PH)

        delta_cls = "subg-up" if delta > 0 else "subg-down" if delta < 0 else "subg-flat"
        arrow = "▲" if delta > 0 else "▼" if delta < 0 else "▬"
        delta_txt = "%s%d" % (arrow, abs(delta))

        svg = (
            '<svg viewBox="0 0 %g %g" class="subg-svg" preserveAspectRatio="none" '
            'role="img" aria-label="%s trajectory"><title>%s trajectory</title>%s%s%s%s%s</svg>'
            % (W, H, esc(label), esc(label), band_poly, hist_lines, median, divider, hover)
        )

        cell = (
            '<div class="subg-cell" data-subg-key="%s">'
            '<div class="subg-head">'
            '<span class="subg-label">%s</span>'
            '<span class="subg-delta %s" title="Projected change by %d">%s</span>'
            '</div>'
            '<div class="subg-cur"><span class="subg-cur-val" data-subg-val>%d</span>'
            '<span class="subg-cur-cap" data-subg-cap>now</span></div>'
            '%s</div>'
            % (esc(key), esc(label), delta_cls, pseasons[-1], esc(delta_txt),
               int(round(cur_val)), svg)
        )

        return cell, {
            "key": key,
            "hist": {"s": h_seasons, "v": [round(v, 1) for v in h_vals]},
            "proj": {"s": pseasons,
                     "p10": [round(v, 1) for v in p10],
                     "p50": [round(v, 1) for v in p50],
                     "p90": [round(v, 1) for v in p90]},
            "g": {"lo": round(lo, 2), "hi": round(hi, 2)},
        }

    groups_html = []
    payload_charts = {}
    rendered_any = False
    for title, keys in RATING_GROUPS:
        cells = []
        for key in keys:
            res = render_cell(key)
            if res is None:
                # Minimal placeholder keeps the 5-up grid aligned.
                cells.append(
                    '<div class="subg-cell subg-empty">'
                    '<div class="subg-head"><span class="subg-label">%s</span></div>'
                    '<div class="subg-cur"><span class="subg-cur-val">--</span></div>'
                    '</div>' % esc(RATING_LABELS[key]))
                continue
            cell_html, cdata = res
            cells.append(cell_html)
            payload_charts[key] = cdata
            rendered_any = True
        groups_html.append(
            '<div class="subg-group">'
            '<h3 class="subg-group-title">%s</h3>'
            '<div class="subg-row">%s</div></div>'
            % (esc(title), "".join(cells)))

    if not rendered_any:
        return ""

    payload = {
        "cur": cur_season,
        "smin": s_min, "smax": s_max,
        "g": {"ml": ML, "mt": MT, "pw": PW, "ph": PH, "w": W, "h": H},
        "charts": payload_charts,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    return (
        '<section class="card">'
        '<div class="section-title-row">'
        '<h2>Rating Trajectories</h2>'
        '<span class="muted small-copy">'
        '<span class="subg-key subg-key-hist"></span> History · '
        '<span class="subg-key subg-key-med"></span> Projected · '
        '<span class="subg-key subg-key-band"></span> 80%% range'
        '</span></div>'
        '<div class="subg-grid" data-subrating-grid data-subg-pid="%d">'
        '%s'
        '</div>'
        '<script type="application/json" id="subrating-data-%d">%s</script>'
        '</section>'
        % (pid, "".join(groups_html), pid, payload_json)
    )


def projection_table_html(player: dict[str, Any], proj: dict[str, Any] | None) -> str:
    """Numeric table of the Monte Carlo future projection (the next 6 seasons).

    Complements the historical "Ratings" table: rows are the projected future
    seasons (``sim["seasons"][1:]`` with their ages); columns are Year, Age, Ovr,
    then the 15 subratings in ``RATING_LABELS`` order. Each cell shows the median
    (p50) as the primary number with the 80% range (p10-p90) underneath in muted
    italic text, and a faint good/bad tint by delta vs. the current value
    (``p50[0]``). Returns "" when no projection or data is insufficient.
    """
    if proj is None:
        return ""
    sim = proj.get("sim") or {}
    seasons = sim.get("seasons") or []
    ages = sim.get("ages") or []
    ovr = sim.get("ovr") or {}
    subratings = sim.get("subratings") or {}
    # Index 0 is the current season; we need at least one future season.
    if len(seasons) < 2 or len(ages) < 2:
        return ""

    def band(metric: dict, pct: str, idx: int):
        arr = metric.get(pct) or []
        if idx >= len(arr):
            return None
        v = safe_float(arr[idx], float("nan"))
        if not math.isfinite(v):
            return None
        return int(round(v))

    # Column metrics in display order: Ovr, then the 15 subratings.
    col_metrics = [("Ovr", ovr)]
    for key in RATING_LABELS:
        col_metrics.append((RATING_LABELS[key], subratings.get(key) or {}))

    # Header.
    head_cells = '<th class="projtab-sticky">Year</th><th>Age</th>'
    for i, (label, _m) in enumerate(col_metrics):
        cls = ' class="projtab-ovr-col"' if i == 0 else ""
        head_cells += f"<th{cls}>{esc(label)}</th>"

    body_rows = []
    n_future = len(seasons) - 1
    for i in range(1, len(seasons)):
        season_lbl = safe_int(seasons[i], 0)
        age_lbl = safe_int(ages[i], 0) if i < len(ages) else 0
        cells = [
            f'<td class="projtab-sticky projtab-year">{esc(season_lbl)}</td>',
            f'<td class="projtab-age">{esc(age_lbl)}</td>',
        ]
        for ci, (_label, metric) in enumerate(col_metrics):
            p50 = band(metric, "p50", i)
            cur = band(metric, "p50", 0)
            p10 = band(metric, "p10", i)
            p90 = band(metric, "p90", i)
            ovr_cls = " projtab-ovr-col" if ci == 0 else ""
            if p50 is None:
                cells.append(f'<td class="projtab-cell{ovr_cls}">—</td>')
                continue
            # Faint delta tint vs. the current value, opacity scaled by magnitude.
            style = ""
            if cur is not None and p50 != cur:
                delta = p50 - cur
                op = min(0.18, 0.03 + abs(delta) * 0.012)
                var = "--good" if delta > 0 else "--bad"
                style = f' style="background:color-mix(in srgb, var({var}) {op * 100:.0f}%, transparent)"'
            if p10 is not None and p90 is not None:
                rng = f'<span class="projtab-range">{esc(p10)}–{esc(p90)}</span>'
            else:
                rng = ""
            cells.append(
                f'<td class="projtab-cell{ovr_cls}"{style}>'
                f'<span class="projtab-med">{esc(p50)}</span>{rng}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    body_html = "\n".join(body_rows)
    return f"""
    <section class="card stats-section" id="projection-table">
      <div class="section-title-row">
        <h2>Projection <span class="projtab-badge">Projected</span></h2>
        <span class="muted small-copy">next {n_future} seasons</span>
      </div>
      <p class="muted small-copy projtab-caption">Monte&nbsp;Carlo medians with 80% ranges (P10–P90) shown underneath. Cells tint green or red by their projected change vs. the current value.</p>
      <div class="table-wrap projtab-wrap">
        <table class="projtab-table">
          <thead><tr>{head_cells}</tr></thead>
          <tbody>
            {body_html}
          </tbody>
        </table>
      </div>
    </section>
    """


def player_form(log_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    played = [e for e in (log_entries or []) if safe_float((e.get("box") or {}).get("min")) > 0]
    if len(played) < 6:
        return None
    last5 = played[-5:]
    season_games = played

    def averages(entries):
        n = len(entries)
        out = {}
        for key in ("pts", "ast", "min"):
            out[key] = sum(safe_float(e["box"].get(key)) for e in entries) / n
        out["trb"] = sum(safe_float(e["box"].get("orb")) + safe_float(e["box"].get("drb")) for e in entries) / n
        out["gmsc"] = sum(game_score_value(e["box"]) for e in entries) / n
        return out

    return {"recent": averages(last5), "season": averages(season_games), "n": len(last5)}


def form_card_html(player: dict[str, Any], log_entries: list[dict[str, Any]]) -> str:
    form = player_form(log_entries)
    if not form:
        return ""
    rows = []
    for key, label, digits in (("pts", "PTS", 1), ("trb", "TRB", 1), ("ast", "AST", 1), ("min", "MIN", 1), ("gmsc", "GmSc", 1)):
        recent = form["recent"][key]
        season_avg = form["season"][key]
        delta = recent - season_avg
        cls = "delta-up" if delta > 0.05 else "delta-down" if delta < -0.05 else ""
        rows.append(
            f'<div class="vital-tile"><span>{esc(label)}</span>'
            f'<strong>{fmt_number(recent, digits)} <span class="{cls} small-copy">({fmt_signed(delta, 1)})</span></strong></div>'
        )
    trend = form["recent"]["gmsc"] - form["season"]["gmsc"]
    verdict = "🔥 Running hot" if trend > 2 else "🧊 In a cold spell" if trend < -2 else "Steady"
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Form · Last {form["n"]} Games</h2><span class="muted small-copy">{esc(verdict)} · (vs season average)</span></div>
      <div class="vitals-row">{''.join(rows)}</div>
    </section>
    """


def vs_opponent_table(player: dict[str, Any], log_entries: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    played = [e for e in (log_entries or []) if safe_float((e.get("box") or {}).get("min")) > 0]
    if not played:
        return ""
    by_opp: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in played:
        by_opp[safe_int(entry.get("opp_tid"), -1)].append(entry)
    rows = []
    for opp_tid, entries in sorted(by_opp.items(), key=lambda kv: team_abbrev_for_tid(kv[0], teams_by_tid)):
        n = len(entries)
        pts = sum(safe_float(e["box"].get("pts")) for e in entries) / n
        trb = sum(safe_float(e["box"].get("orb")) + safe_float(e["box"].get("drb")) for e in entries) / n
        ast = sum(safe_float(e["box"].get("ast")) for e in entries) / n
        fg = sum(safe_float(e["box"].get("fg")) for e in entries)
        fga = sum(safe_float(e["box"].get("fga")) for e in entries)
        pm = sum(safe_float(e["box"].get("pm")) for e in entries) / n
        wins = sum(1 for e in entries if safe_float(e.get("team_pts")) > safe_float(e.get("opp_pts")))
        rows.append("".join([
            td(team_label(opp_tid, teams_by_tid, root), sort=team_abbrev_for_tid(opp_tid, teams_by_tid), cls="name-cell"),
            td(f"{wins}-{n - wins}", sort=wins),
            td(fmt_number(pts, 1), sort=pts),
            td(fmt_number(trb, 1), sort=trb),
            td(fmt_number(ast, 1), sort=ast),
            td(fmt_pct(made_pct(fg, fga)), sort=made_pct(fg, fga)),
            td(fmt_signed(pm, 1), sort=pm, cls=plus_minus_class(pm)),
        ]))
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Vs Opponents · This Season</h2></div>
      {table_html(["Opp", "W-L", "PTS", "TRB", "AST", "FG%", "+/-"], rows, table_id=f"vsopp-{player.get('pid')}", empty_message="No games played.", wrap_cls="fit-table")}
    </section>
    """


def best_performances_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    logs = build_game_logs(data, season)
    scored = []
    for pid, entries in logs.items():
        for entry in entries:
            box = entry.get("box") or {}
            if safe_float(box.get("min")) <= 0:
                continue
            scored.append((game_score_value(box), pid, entry))
    if not scored:
        return ""
    scored.sort(key=lambda x: -x[0])
    rows = []
    for gmsc, pid, entry in scored[:10]:
        player = ALL_PLAYERS_BY_PID.get(pid)
        box = entry["box"]
        trb = safe_float(box.get("orb")) + safe_float(box.get("drb"))
        line = f"{fmt_number(box.get('pts'), 0)} PTS · {fmt_number(trb, 0)} TRB · {fmt_number(box.get('ast'), 0)} AST"
        name_html = event_player_link(pid, ALL_PLAYERS_BY_PID, root) if player else esc(box.get("name", "—"))
        rows.append("".join([
            td(name_html, sort=player_name(player) if player else "", cls="name-cell"),
            td(f'<a href="{root}games/{esc(game_slug_from_gid(entry.get("gid")))}.html">Day {safe_int(entry.get("day"))} vs {esc(team_abbrev_for_tid(entry.get("opp_tid"), teams_by_tid))}</a>', sort=entry.get("day")),
            td(line, sort=safe_float(box.get("pts"))),
            td(fmt_number(gmsc, 1), sort=gmsc),
        ]))
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Best Performances · Season {season}</h2><span class="muted small-copy">by Game Score</span></div>
      {table_html(["Player", "Game", "Line", "GmSc"], rows, table_id="best-perf", empty_message="No games yet.", wrap_cls="fit-table")}
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


def player_subnav(player: dict[str, Any], active_sub: str, available: set[str]) -> str:
    slug = player_slug(player)
    items = [("overview", "Overview", f"{slug}.html")]
    if "stats" in available:
        items.append(("stats", "Stats", f"{slug}-stats.html"))
    if "log" in available:
        items.append(("log", "Game Log", f"{slug}-log.html"))
    items.append(("ratings", "Ratings", f"{slug}-ratings.html"))
    links = []
    for key, label, href in items:
        active = " active" if key == active_sub else ""
        cur = ' aria-current="page"' if key == active_sub else ""
        links.append(f'<a class="subnav-link{active}" href="{href}"{cur}>{esc(label)}</a>')
    return f'<nav class="team-subnav" aria-label="Player sections">{"".join(links)}</nav>'


def render_player_pages(player: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int, log_entries: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """Build the player's sub-pages. Returns ``{suffix: html}`` (suffix "" is the
    Overview / canonical page). Only sub-pages that have data are generated.

    The Monte Carlo projection is computed once and shared across the projection-backed
    sections (development chart, scouting tags, trajectory grid, projection table)."""
    teams_by_tid = {t["tid"]: t for t in teams}
    regular = regular_stats_since(player, start_season)
    playoffs = playoff_stats_since(player, start_season)
    logs = log_entries or []
    proj = _player_projection(player, season)

    # Gate sub-pages on whether the sections would actually render content: the stat
    # tables skip seasons with no games and the game log / vs-opponent tables skip
    # 0-minute (DNP) appearances, so gating on the raw lists would leave dead tabs.
    available: set[str] = set()
    if any(stat_gp(s) > 0 for s in regular):
        available.add("stats")
    if any(safe_float((e.get("box") or {}).get("min")) > 0 for e in logs):
        available.add("log")
    full_hero = render_player_hero(player, teams_by_tid, season, start_season)
    compact_hero = render_player_hero(player, teams_by_tid, season, start_season, compact=True)

    def page(active: str, title_suffix: str, hero: str, sections: list[str]) -> str:
        body = hero + player_subnav(player, active, available) + "".join(sections)
        return page_html(player_name(player) + title_suffix, body, teams, root="../", active="players")

    pages: dict[str, str] = {}
    pages[""] = page("overview", "", full_hero, [
        player_summary_rows(player, teams_by_tid, season, start_season),
        season_highs_html(player, logs, teams_by_tid, season, "../"),
        form_card_html(player, logs),
        development_chart_html(player, season, proj),
        subrating_grid_html(player, proj),
    ])
    if "stats" in available:
        stats_sections = [
            per_game_table(player, regular, teams_by_tid, "../", "Per Game · Regular Season", f"regular-{player.get('pid')}"),
            shot_table(player, regular, teams_by_tid, "../", "Shot Locations and Feats · Regular Season", f"shots-{player.get('pid')}"),
            advanced_table(player, regular, teams_by_tid, "../", "Advanced · Regular Season", f"advanced-{player.get('pid')}"),
        ]
        if playoffs:
            stats_sections.append(per_game_table(player, playoffs, teams_by_tid, "../", "Per Game · Playoffs", f"playoffs-{player.get('pid')}"))
            stats_sections.append(advanced_table(player, playoffs, teams_by_tid, "../", "Advanced · Playoffs", f"playoff-advanced-{player.get('pid')}"))
        pages["-stats"] = page("stats", " — Stats", compact_hero, stats_sections)
    if "log" in available:
        pages["-log"] = page("log", " — Game Log", compact_hero, [
            game_log_table(player, logs, teams_by_tid, season, "../"),
            vs_opponent_table(player, logs, teams_by_tid, "../"),
        ])
    pages["-ratings"] = page("ratings", " — Ratings", compact_hero, [
        ratings_table(player, start_season),
        '<div class="history-row">' + salary_history_html(player) + injury_history_html(player) + "</div>",
    ])
    return pages


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

    Team strength blends regressed scoring margin with current-roster quality.
    Players who are injured subtract their impact until their expected return,
    so odds dip while stars are out and recover as they heal. Trades are picked
    up automatically because strength comes from the roster as it stands today.

    A season that hasn't been played yet (an offseason projection) starts every team at 0-0
    and runs over a projected round-robin schedule; last season's scoring margin still seeds
    team strength, so the projection reflects both prior form and the current roster.
    """
    fresh = not completed_game_items(data, season, playoffs=False)
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    wins0: dict[int, float] = {}
    mov_strength: dict[int, float] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins0[tid] = 0.0 if fresh else safe_float(team_season.get("won"))
        gp = safe_float(stat.get("gp"))
        mov = team_mov(stat) or 0.0
        mov_strength[tid] = mov * gp / (gp + 10.0)

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
    base_strength = {
        tid: 0.5 * mov_strength.get(tid, 0.0) + 0.5 * (roster_strength.get(tid, 0.0) - mean_roster)
        for tid in tids
    }

    # Remaining schedule in chronological order. An unplayed season has no exported schedule,
    # so project it over a generated round-robin instead.
    remaining: list[tuple[int, int, int, str]] = []
    if fresh:
        items = generated_schedule_items(data, teams, schedule_season=season)
    else:
        items, _ = score_items_for_page(data, teams)
    for item in items:
        if is_completed_game_item(item) or safe_int(item.get("season")) != season:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        if home in wins0 and away in wins0:
            remaining.append((safe_int(item.get("day")), home, away, str(item.get("gid"))))
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
        diff = (base_strength[home] - penalty_at[home][min(k_home, max_left)]) - (
            base_strength[away] - penalty_at[away][min(k_away, max_left)]
        ) + 1.5
        return 1.0 / (1.0 + math.exp(-diff * 0.16))

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

    stakes = []
    for day, home, away, gid in stakes_games:
        counts = stake_counts[gid]

        def rate(key: str) -> float | None:
            total, made = counts[key][0], counts[key][1]
            return made / total if total else None

        home_swing = away_swing = None
        if rate("home_win") is not None and rate("home_loss") is not None:
            home_swing = rate("home_win") - rate("home_loss")
        if rate("away_win") is not None and rate("away_loss") is not None:
            away_swing = rate("away_win") - rate("away_loss")
        stakes.append({"gid": gid, "day": day, "home_tid": home, "away_tid": away, "home_swing": home_swing, "away_swing": away_swing})
    return {"teams": results, "stakes": stakes, "day": first_day, "fresh": fresh}


def league_sim(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[str, Any]:
    """League simulation, cached per season (each season is simulated once per build)."""
    cache = SITE_META.setdefault("sim", {})
    if season not in cache:
        cache[season] = simulate_league(data, teams, active_players(data), season)
    return cache[season]


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


def seed_cell_style(pct: float) -> str:
    """Single-hue intensity: faint for unlikely seeds, strong for likely ones."""
    if pct < 0.5:
        return ""
    alpha = 0.06 + 0.55 * min(1.0, pct / 100.0)
    return f"background-color: rgba(91,157,255,{alpha:.2f})"


def playoff_odds_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    sim = league_sim(data, teams, season)
    odds = sim.get("teams") or {}
    if not odds or all(o["games_left"] == 0 for o in odds.values()):
        return ""
    season_len = regular_season_length(data, season) or 45
    infos = sorted(odds.items(), key=lambda kv: (-kv[1]["po"], -kv[1]["proj_w"]))
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    n_seeds = len(infos)
    rows = []
    for tid, o in infos:
        team = teams_by_tid.get(tid, {})
        proj_w = o["proj_w"]
        proj_l = season_len - proj_w
        po_pct = 100 * o["po"]
        finals_pct = 100 * o["finals"]
        champ_pct = 100 * o["champ"]
        cells = [
            td(f'{team_dot(tid, palette)}{team_anchor(team)}', sort=team_full_name(team), cls="name-cell"),
            td(f"{fmt_number(proj_w, 1)}-{fmt_number(proj_l, 1)}", sort=proj_w),
            td(fmt_number(po_pct, 0) + "%", sort=po_pct, style=heat_style(po_pct, 0, 100, 1)),
            td((fmt_number(finals_pct, 0) if finals_pct >= 0.5 else ("—" if finals_pct == 0 else "<1")) + ("%" if finals_pct >= 0.5 else ""), sort=finals_pct),
            td((fmt_number(champ_pct, 0) if champ_pct >= 0.5 else ("—" if champ_pct == 0 else "<1")) + ("%" if champ_pct >= 0.5 else ""), sort=champ_pct, style=heat_style(champ_pct, 0, max(1.0, max(100 * x[1]["champ"] for x in infos)), 1)),
        ]
        for seed_index in range(n_seeds):
            pct = 100 * o["seeds"][seed_index]
            if pct < 0.5:
                text = "—" if pct == 0 else "<1"
            else:
                text = fmt_number(pct, 0)
            cls = "seed-cut" if seed_index == 4 else ""
            cells.append(td(text, sort=pct, style=seed_cell_style(pct), cls=cls))
        rows.append(f'<tr data-tid="{tid}">{"".join(cells)}</tr>')
    headers = ["Team", "Proj W-L", "PO%", "Finals%", "Title%"] + [str(i) for i in range(1, n_seeds + 1)]
    if sim.get("fresh"):
        title = f"{season} Playoff Odds"
        note = (f"10,000 sims of the {season} season from current rosters over a projected schedule · "
                "last season's scoring margin seeds team strength · playoffs simulated as 1v4 / 2v3 best-of-sevens")
    else:
        title = "Playoff Odds"
        note = ("10,000 sims · injury-aware: sidelined players hurt their team until their expected return · "
                "playoffs simulated as 1v4 / 2v3 best-of-sevens")
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>{title}</h2><span class="muted small-copy">{note}</span></div>
      {table_html(headers, rows, table_id="playoff-odds", empty_message="Season complete.")}
    </section>
    """


def stakes_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    sim = league_sim(data, teams, season)
    stakes = sim.get("stakes") or []
    if not stakes:
        return ""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    palette = team_palette_by_tid(teams)
    items, _ = score_items_for_page(data, teams)
    items_by_gid = {str(item.get("gid")): item for item in items}
    cards = []
    for stake in sorted(stakes, key=lambda s: -max(abs(s.get("home_swing") or 0), abs(s.get("away_swing") or 0))):
        item = items_by_gid.get(str(stake["gid"]))
        link = esc(game_url(item)) if item else "#"
        rows = []
        for side, tid_key, swing_key in (("away", "away_tid", "away_swing"), ("home", "home_tid", "home_swing")):
            tid = stake[tid_key]
            swing = stake.get(swing_key)
            if swing is None:
                swing_html = '<span class="muted">—</span>'
            else:
                pts = 100 * swing
                cls = "delta-up" if pts >= 10 else ""
                swing_html = f'<span class="{cls}">±{fmt_number(pts, 0)}%</span>'
            rows.append(
                f'<span class="score-row"><span>{team_dot(tid, palette)}{esc(team_abbrev_for_tid(tid, teams_by_tid))}</span>'
                f'<strong>{swing_html}</strong></span>'
            )
        cards.append(f'<a class="score-line score-stack" href="{link}">{"".join(rows)}</a>')
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>What's at Stake · Day {sim.get("day")}</h2><span class="muted small-copy">playoff-odds swing between winning and losing today's game</span></div>
      <div class="score-list">{''.join(cards)}</div>
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


def last_result_by_tid(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[int, str]:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    out: dict[int, str] = {}
    for item in completed_game_items(data, season, playoffs=None):
        winner = game_winner_tid(item)
        for tid_key, opp_key in (("home_tid", "away_tid"), ("away_tid", "home_tid")):
            tid = safe_int(item.get(tid_key))
            opp = safe_int(item.get(opp_key))
            own_pts = item_team_points(item, tid)
            opp_pts = item_team_points(item, opp)
            verb = "beat" if winner == tid else "lost to"
            out[tid] = f"{verb} {team_abbrev_for_tid(opp, teams_by_tid)} {fmt_number(own_pts, 0)}-{fmt_number(opp_pts, 0)}"
    return out


def standings_table(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    clinch_marks = playoff_clinch_marks(data, teams, season)
    sos_by_tid = remaining_sos_by_tid(data, teams, season)
    srs = srs_by_tid(data, teams, season)
    last_results = last_result_by_tid(data, teams, season)
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
    headers = ["Team", "W", "L", "%", "GB", "Home", "Road", "PS", "PA", "MOV", "SRS", "Streak", "L10", "SOS"]
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
                last_res = last_results.get(safe_int(team.get("tid")), "")
                last_suffix = f" · last game: {last_res}" if last_res else ""
                if delta > 0:
                    move_html = f'<span class="rank-move delta-up" title="Up {delta} since last update{esc(last_suffix)}">▲{delta}</span>'
                elif delta < 0:
                    move_html = f'<span class="rank-move delta-down" title="Down {-delta} since last update{esc(last_suffix)}">▼{-delta}</span>'
                else:
                    move_html = f'<span class="rank-move rank-flat" title="No movement{esc(last_suffix)}">·</span>'
            mark = clinch_marks.get(safe_int(team.get("tid")))
            if mark == "x":
                mark_html = '<span class="clinch-pre" title="Clinched a playoff spot">x –</span> '
            elif mark == "e":
                mark_html = '<span class="clinch-pre" title="Eliminated from playoff contention">e –</span> '
            else:
                mark_html = ""
            # The computed mark replaces the export's clinchedPlayoffs marker when present.
            clinch_suffix = "" if mark else clinch_html(team_season)
            cells = "".join([
                td(f'<span class="row-rank">{rank}</span>{move_html}{mark_html}{team_dot(team.get("tid"), palette)}{team_anchor(team)}{clinch_suffix}', sort=rank, cls="name-cell"),
                td(fmt_number(row["won"], 0), sort=row["won"]),
                td(fmt_number(row["lost"], 0), sort=row["lost"]),
                td(fmt_win_pct(row["pct"]), sort=row["pct"]),
                td(gb_text, sort=gb if leader else None),
                td(fmt_record(team_season.get("wonHome"), team_season.get("lostHome")), sort=team_season.get("wonHome")),
                td(fmt_record(team_season.get("wonAway"), team_season.get("lostAway")), sort=team_season.get("wonAway")),
                td(fmt_number(team_stat_per_game(stat, "pts"), 1), sort=team_stat_per_game(stat, "pts")),
                td(fmt_number(team_stat_per_game(stat, "oppPts"), 1), sort=team_stat_per_game(stat, "oppPts")),
                td(fmt_signed(mov, 1), sort=mov, cls=plus_minus_class(mov)),
                td(fmt_signed(srs.get(safe_int(team.get("tid"))), 1) if srs.get(safe_int(team.get("tid"))) is not None else "—", sort=srs.get(safe_int(team.get("tid"))), cls=plus_minus_class(srs.get(safe_int(team.get("tid"))))),
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
        section_marks = {clinch_marks.get(safe_int(r["team"].get("tid"))) for r in rows}
        clinch_note = ""
        if section_marks & {"x", "e"}:
            clinch_note = '<p class="muted small-copy">x – clinched a playoff spot · e – eliminated from playoff contention</p>'
        sections.append(f'''
        <section class="card home-section standings-section">
          <div class="section-title-row"><h2>{esc(title)}</h2><span class="muted small-copy">Top 4 make the playoffs · SOS = remaining opponents' win%</span></div>
          {table_html(headers, html_rows, table_id=f"standings-{esc(cid)}", empty_message="No standings data found.")}
          {clinch_note}
        </section>
        ''')
    return "".join(sections)


def srs_by_tid(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[int, float]:
    """Simple Rating System: scoring margin adjusted for opponent strength."""
    margins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for item in completed_game_items(data, season, playoffs=False):
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        diff = safe_float(item.get("home_pts")) - safe_float(item.get("away_pts"))
        margins[home].append((diff, away))
        margins[away].append((-diff, home))
    if not margins:
        return {}
    srs = {tid: sum(m for m, _ in games) / len(games) for tid, games in margins.items()}
    for _ in range(25):
        nxt = {}
        for tid, games in margins.items():
            mov = sum(m for m, _ in games) / len(games)
            sos = sum(srs.get(opp, 0.0) for _, opp in games) / len(games)
            nxt[tid] = mov + sos
        mean = sum(nxt.values()) / len(nxt)
        srs = {tid: value - mean for tid, value in nxt.items()}
    return srs


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


def game_sort_key(item: dict[str, Any]) -> tuple[int, int, int, Any]:
    gid = item.get("gid")
    try:
        gid_key: tuple[int, Any] = (0, int(gid))
    except (TypeError, ValueError):
        gid_key = (1, "" if gid is None else str(gid))
    return (safe_int(item.get("day")), 1 if item.get("playoffs") else 0, gid_key[0], gid_key[1])


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
    items.sort(key=game_sort_key)
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
    items.sort(key=game_sort_key)
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
    """Round-robin schedule for a season with no exported schedule.

    Only the projection model consumes this (see simulate_league) — the schedule page, team
    pages and game pages deliberately never show synthetic matchups.
    """
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

    # No synthetic fallback here on purpose: pages only ever show real games. The projected
    # schedule lives inside simulate_league.
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
    merged.sort(key=game_sort_key)
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
    # Show only the upcoming season's schedule. In the offseason it has no games yet (we don't
    # synthesize one), so the page renders an empty state until a real schedule is exported.
    upcoming = schedule_season if schedule_season is not None else inferred_upcoming_schedule_season(data)
    items, _ = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    items = [item for item in items if safe_int(item.get("season")) == upcoming]
    label = f"Season {upcoming} schedule"
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
        table = f'<p class="empty-state">The {upcoming} schedule hasn\'t been released yet.</p>'

    season_for_h2h = max((safe_int(item.get("season")) for item in items), default=upcoming)
    hero_copy = (f"{esc(label)} · <strong>vs.</strong> home · <strong>@</strong> road · the highlighted row is the next game day"
                 if rows else esc(label))
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Schedule</h1>
        <p class="muted">{hero_copy}</p>
      </div>
    </section>
    {head_to_head_matrix(data, teams, season_for_h2h)}
    <section class="card">
      {table}
    </section>
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
    team_name = team_full_for_tid(tid, teams_by_tid)
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
          <caption class="sr-only">{esc(team_name)} box score</caption>
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
    shots = game_shot_profile(item, teams_by_tid, "../")
    body = f"""
    {box_score_header(item, teams_by_tid, prev_item, next_item)}
    {clutch}
    {preview}
    {box_score_team_table(away_box, teams_by_tid, players_by_pid, root='../')}
    {box_score_team_table(home_box, teams_by_tid, players_by_pid, root='../')}
    {shots}
    {series}
    """
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    title = f"{away_abbrev} at {home_abbrev} Box Score"
    return page_html(title, body, teams, root="../", active="schedule")


def game_recap_text(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    winner_tid = game_winner_tid(item)
    if winner_tid is None:
        return ""
    loser_tid = item.get("away_tid") if winner_tid == item.get("home_tid") else item.get("home_tid")
    margin = abs(safe_float(item.get("home_pts")) - safe_float(item.get("away_pts")))
    win_box = item.get("home_box") if winner_tid == item.get("home_tid") else item.get("away_box")
    star = None
    best = -999.0
    for box in (win_box or {}).get("players") or []:
        if safe_float(box.get("min")) <= 0:
            continue
        gmsc = game_score_value(box)
        if gmsc > best:
            best = gmsc
            star = box
    if star is None:
        return ""
    star_name = str(star.get("name") or "").split(" ")[-1]
    pts = fmt_number(star.get("pts"), 0)
    winner = teams_by_tid.get(safe_int(winner_tid), {}).get("region") or team_abbrev_for_tid(winner_tid, teams_by_tid)
    loser = teams_by_tid.get(safe_int(loser_tid), {}).get("region") or team_abbrev_for_tid(loser_tid, teams_by_tid)
    overtimes = safe_int((item.get("game") or {}).get("overtimes"))
    if overtimes:
        ot = "OT" if overtimes == 1 else f"{overtimes}OT"
        return f"{winner} outlasted {loser} in {ot}; {star_name} had {pts}."
    if margin >= 15:
        return f"{winner} cruised past {loser} behind {star_name}'s {pts}."
    if margin <= 5:
        return f"{winner} edged {loser}; {star_name} led with {pts}."
    return f"{star_name} led {winner} past {loser} with {pts}."


def latest_results_strip(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    completed = completed_game_items(data, season, playoffs=None)
    if not completed:
        return ""
    last_day = max(safe_int(item.get("day")) for item in completed)
    day_items = [item for item in completed if safe_int(item.get("day")) == last_day]
    def result_row(tid: Any, pts: Any, won: bool) -> str:
        team = teams_by_tid.get(safe_int(tid), {})
        team_season = latest_team_season(team, season)
        record = fmt_record(team_season.get("won"), team_season.get("lost"))
        name = esc(team.get("region") or team_abbrev(team))
        cls = "score-row score-won" if won else "score-row"
        return (
            f'<span class="{cls}"><span>{name} <span class="muted">({esc(record)})</span></span>'
            f'<strong>{fmt_number(pts, 0)}</strong></span>'
        )

    lines = []
    for item in day_items:
        winner = game_winner_tid(item)
        ot = game_ot_label(item)
        ot_html = f'<span class="score-status">{esc(ot)}</span>' if ot else ""
        recap = game_recap_text(item, teams_by_tid)
        recap_html = f'<span class="recap muted small-copy">{esc(recap)}</span>' if recap else ""
        lines.append(
            f'<a class="score-line score-stack" href="{esc(game_url(item))}">'
            + result_row(item.get("away_tid"), item.get("away_pts"), winner == item.get("away_tid"))
            + result_row(item.get("home_tid"), item.get("home_pts"), winner == item.get("home_tid"))
            + recap_html
            + ot_html
            + "</a>"
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
                        rnd = "" if safe_int(asset.get("round")) == 1 else " 2nd"
                        got.append(f"{esc(asset.get('season'))}{rnd} ({esc(origin)})")
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


def news_feed_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "", limit: int = 10) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    current_gids = {str(g.get("gid")) for g in data.get("games", []) if g.get("season") == season}
    wanted = set(EVENT_BADGES) - {"retired", "hallOfFame"}  # retirement-class news is excluded from the home feed
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
        games_left = injury.get("gamesRemaining")
        injury_cell = esc(injury.get("type", "—"))
        if safe_int(games_left) > 0:
            injury_cell += f' <span class="muted small-copy">· {fmt_number(games_left, 0)}g</span>'
        rows.append("".join([
            td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
            td(injury_cell, sort=safe_int(games_left)),
        ]))
    if not rows:
        return ""
    headers = ["Player", "Pos", "Ovr", "Injury"]
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
        # Rostered players and free agents who played this season both qualify; FAs are shown
        # under the team they actually played for (from the stat row), not "FA".
        if safe_int(player.get("tid"), -9) < FREE_AGENT_TID:
            continue
        stat = season_regular_stat(player, season)
        if stat_gp(stat) >= min_gp:
            qualified.append((player, stat))
    if not qualified:
        return ""

    def played_for_tid(player: dict[str, Any], stat: dict[str, Any]) -> int:
        tid = safe_int(player.get("tid"), -1)
        return tid if tid >= 0 else safe_int(stat.get("tid"), -1)

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
            disp_tid = played_for_tid(player, stat)
            rows.append(
                "<tr>"
                f'<td class="leader-rank">{rank}</td>'
                f'<td class="leader-player-cell"><span class="leader-player-wrap">{team_dot(disp_tid, palette)}'
                f'<span class="leader-name-block"><a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
                f'<span class="leader-team">{esc(team_abbrev_for_tid(disp_tid, teams_by_tid))}</span></span></span></td>'
                f'<td class="leader-value">{fmt_number(value, fmt_digits)}</td>'
                "</tr>"
            )
        return "".join(rows)

    categories = [
        ("Points", lambda s: per_game(s, "pts")),
        ("Rebounds", lambda s: total_rebounds(s) / stat_gp(s) if stat_gp(s) else None),
        ("Assists", lambda s: per_game(s, "ast")),
        ("Steals", lambda s: per_game(s, "stl")),
        ("Blocks", lambda s: per_game(s, "blk")),
        ("OBPM", lambda s: s.get("obpm")),
        ("DBPM", lambda s: s.get("dbpm")),
        ("BPM", lambda s: safe_float(s.get("obpm")) + safe_float(s.get("dbpm"))),
    ]
    boxes = []
    for title, fn in categories:
        body = leaders(fn)
        if body:
            boxes.append(
                f'<div class="leader-box"><h3>{esc(title)}</h3>'
                f'<table class="leader-mini-table"><caption class="sr-only">{esc(title)} leaders</caption>'
                '<colgroup><col class="leader-col-rank"><col><col class="leader-col-value"></colgroup>'
                '<thead class="sr-only"><tr><th scope="col">Rank</th><th scope="col">Player</th><th scope="col">Value</th></tr></thead>'
                f'<tbody>{body}</tbody></table></div>'
            )
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


def home_finances_table(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
    """League-wide finance snapshot for the home page: one row per team, richest first."""
    fin = compute_league_finances(data, teams, players, season)["teams"]
    palette = team_palette_by_tid(teams)
    rows_data = sorted(
        ((t, fin[safe_int(t.get("tid"), -99)]) for t in teams if safe_int(t.get("tid"), -99) in fin),
        key=lambda tf: -tf[1]["cash_now"],
    )
    if not rows_data:
        return ""
    year = season + 1
    headers = ["Team", "Record", "Cash on Hand", f"{year} Payroll", "Available to Spend"]
    rows = []
    for t, f in rows_data:
        tid = safe_int(t.get("tid"))
        avail = f.get("avail", f["cash_now"] - f.get("payroll_next", 0.0))
        ac = "delta-up" if avail >= 0 else "delta-down"
        rows.append("".join([
            td(f'{team_dot(tid, palette)}<a class="player-link" href="teams/{team_slug(t)}-finances.html">{esc(team_full_name(t))}</a>',
               sort=team_full_name(t), cls="name-cell"),
            td(fmt_record(f["won"], f["lost"]), sort=safe_int(f["won"])),
            td(fmt_money(f["cash_now"]), sort=f["cash_now"]),
            td(fmt_money(f.get("payroll_next", 0.0)), sort=f.get("payroll_next", 0.0)),
            td(f'<span class="{ac}">{fmt_money(avail)}</span>', sort=avail),
        ]))
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Team Finances</h2><span class="muted small-copy">bankroll entering {year} · available = cash on hand − {year} payroll</span></div>

      {table_html(headers, rows, table_id="home-finances")}
    </section>
    """


def render_home_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    chart_teams = active_teams_for_season(teams, season)
    # Once a season is over, the projection worth showing is the upcoming one (simulated from
    # current rosters); mid-season this is just the current season, so the card is unchanged.
    proj_season = inferred_upcoming_schedule_season(data)
    body = f"""
    <h1 class="sr-only">SMP Basketball League</h1>
    {latest_results_strip(data, chart_teams, season)}
    <div class="home-columns">
      <div class="home-main">
        {standings_table(data, chart_teams, season)}
        {playoff_odds_card(data, chart_teams, proj_season)}
        {stakes_card(data, chart_teams, season)}
        {league_leaders_card(data, players, teams, season)}
      </div>
      <div class="home-side">
        {news_feed_card(data, teams, season)}
        {injury_report_card(players, teams, season)}
        {rookie_watch_card(data, players, teams, season)}
      </div>
    </div>
    {team_stats_table(chart_teams, season)}
    {awards_voting_table(data, players, teams, season)}
    {home_finances_table(data, teams, players, season)}
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
    table_rows = []
    max_players = 0
    for key, title in (("allLeague", "All-League"), ("allDefensive", "All-Defensive")):
        groups = award.get(key)
        if not isinstance(groups, list) or not groups:
            continue
        if groups and isinstance(groups[0], dict) and "players" not in groups[0]:
            groups = [{"title": "", "players": groups}]
        if key == "allDefensive":
            groups = groups[:1]  # 1st team only
        for group in groups:
            if not isinstance(group, dict):
                continue
            members = [m for m in group.get("players") or [] if isinstance(m, dict)]
            if not members:
                continue
            group_title = group.get("title") or ""
            label = f"{title} {group_title}".strip()
            cells = [td(esc(label), cls="name-cell honor-label-cell")]
            for member in members:
                name = event_player_link(member.get("pid"), all_players_by_pid, root, label=member.get("name"))
                team = esc(team_abbrev(teams_by_tid.get(safe_int(member.get("tid"), -10))))
                cells.append(td(f'{name} <span class="muted small-copy">{team}</span>', cls="honor-cell"))
            max_players = max(max_players, len(members))
            table_rows.append(cells)
    if not table_rows:
        return ""
    rows = []
    for cells in table_rows:
        while len(cells) < max_players + 1:
            cells.append(td(""))
        rows.append("".join(cells))
    headers = ["Honor"] + [str(i) for i in range(1, max_players + 1)]
    header_html = "".join(th(label) for label in headers)
    body_html = "".join(f"<tr>{row}</tr>" for row in rows)
    return f"""
    <div class="table-wrap honors-table-wrap">
      <table class="honors-table">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    """


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
    # Simulated slot odds apply only to the upcoming draft (this season's finish).
    slot_odds: dict[int, tuple[float, float]] = {}
    if draft_year == season:
        sim = league_sim(data, teams, season)
        n = len(order)
        for tid, o in (sim.get("teams") or {}).items():
            seeds = o.get("seeds") or []
            if len(seeds) == n:
                p1 = seeds[n - 1]
                top3 = sum(seeds[n - 3:])
                slot_odds[tid] = (100 * p1, 100 * top3)
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
            cells = [
                td(pick_no, sort=pick_no),
                td(f'{team_dot(slot_tid, palette)}{team_anchor(slot_team)} <span class="muted small-copy">({esc(record)})</span>', sort=team_full_name(slot_team), cls="name-cell"),
                td(owner_html, sort=team_full_name(owner_team), cls="name-cell"),
            ]
            if slot_odds:
                p1, top3 = slot_odds.get(slot_tid, (0.0, 0.0))
                cells.append(td(fmt_number(p1, 0) + "%" if p1 >= 0.5 else "—", sort=p1, style=seed_cell_style(p1)))
                cells.append(td(fmt_number(top3, 0) + "%" if top3 >= 0.5 else "—", sort=top3, style=seed_cell_style(top3)))
            rows.append(f'<tr data-tid="{owner_tid}">{"".join(cells)}</tr>')
    if not rows:
        return ""
    headers = ["Pick", "Slot (record)", "Owned by"]
    note = "reverse of current standings · green badge = pick changed hands"
    if slot_odds:
        headers += ["#1 slot %", "Top-3 %"]
        note = "reverse of current standings · slot odds from the season simulation · green badge = pick changed hands"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Projected Draft Order</h2><span class="muted small-copy">{note}</span></div>
      {table_html(headers, rows, table_id=f"lottery-{draft_year}", empty_message="No draft picks found.", wrap_cls="fit-table")}
    </section>
    """


def draft_class_panel(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int, class_prospects: list[dict[str, Any]], hidden: bool) -> str:
    sorted_prospects = sorted(
        class_prospects,
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
    table_id = f"prospects-{draft_year}"
    hidden_attr = " hidden" if hidden else ""
    return f"""
    <div id="draft-panel-{draft_year}" role="tabpanel" aria-labelledby="draft-tab-{draft_year}" data-draft-panel="{draft_year}"{hidden_attr}>
      <div class="draft-overview-row">
        {projected_lottery_html(data, teams, season, draft_year)}
        {mock_draft_card(data, teams, season, draft_year, class_prospects)}
      </div>
      <section class="card">
        <div class="section-title-row"><h2>Class of {draft_year}</h2><span class="count-pill">{len(sorted_prospects)} prospects</span></div>
        <div class="toolbar">
          <input class="table-search" data-table-filter="{table_id}" placeholder="Filter prospects…" aria-label="Filter prospects">
        </div>
        {table_html(headers, rows, table_id=table_id, empty_message="No prospects in this class.")}
      </section>
    </div>
    """


def mock_draft_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int, class_prospects: list[dict[str, Any]]) -> str:
    palette = team_palette_by_tid(teams)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    order = list(reversed(standings_order(active_teams_for_season(teams, season), season)))
    picks = [dp for dp in data.get("draftPicks", []) if isinstance(dp, dict) and dp.get("season") == draft_year and safe_int(dp.get("round")) == 1]
    owner_by_slot = {safe_int(dp.get("originalTid"), -10): safe_int(dp.get("tid"), -10) for dp in picks}
    board = sorted(
        class_prospects,
        key=lambda p: (-safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    if not board or not order:
        return ""
    rows = []
    for pick_no, slot_tid in enumerate(order, 1):
        if pick_no > len(board):
            break
        prospect = board[pick_no - 1]
        rating = latest_rating(prospect)
        owner_tid = owner_by_slot.get(slot_tid, slot_tid)
        owner_team = teams_by_tid.get(owner_tid, {})
        via = "" if owner_tid == slot_tid else f' <span class="muted small-copy">via {esc(team_abbrev(teams_by_tid.get(slot_tid)))}</span>'
        rows.append(f'<tr data-tid="{owner_tid}">' + "".join([
            td(pick_no, sort=pick_no),
            td(f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)}{via}', sort=team_full_name(owner_team), cls="name-cell"),
            td(f'<a class="player-link" href="{player_url(prospect)}">{esc(player_name(prospect))}</a>', sort=player_name(prospect), cls="name-cell"),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
            td(esc(rating.get("pot", "—")), sort=rating.get("pot")),
        ]) + "</tr>")
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Mock Draft</h2><span class="muted small-copy">best available by potential at each projected slot</span></div>
      {table_html(["Pick", "Team", "Prospect", "Pos", "Ovr", "Pot"], rows, table_id=f"mock-{draft_year}", empty_message="No prospects.", wrap_cls="fit-table")}
    </section>
    """


def render_draft_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    prospects = draft_prospects(data)
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for p in prospects:
        year = (p.get("draft") or {}).get("year")
        if isinstance(year, int):
            by_year[year].append(p)
    draft_years = sorted(by_year)
    if not draft_years:
        draft_years = [season]
    tabs = "".join(
        f'<button type="button" id="draft-tab-{year}" role="tab" aria-controls="draft-panel-{year}" aria-selected="{"true" if i == 0 else "false"}" class="{"active" if i == 0 else ""}" data-draft-tab="{year}">{year}</button>'
        for i, year in enumerate(draft_years)
    )
    panels = "".join(
        draft_class_panel(data, teams, season, year, by_year.get(year, []), hidden=(i != 0))
        for i, year in enumerate(draft_years)
    )
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Draft</h1>
        <p class="muted">Upcoming classes · sorted by potential · ratings color-scaled within each class · pick slots from current standings</p>
      </div>
      <div class="view-toggle draft-tabs" role="tablist" aria-label="Draft classes" data-draft-tabs>{tabs}</div>
    </section>
    {panels}
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


def trade_machine_payload(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
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
                "label": f"{dp.get('season')}{'' if safe_int(dp.get('round')) == 1 else ' 2nd'}" + (f" (via {via})" if via else ""),
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
    payload = {"teams": out_teams}
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
    lines.push('<p><strong>' + a.team.abbrev + '</strong> payroll after: ' + fmtM(newPayrollA) + '</p>');
    lines.push('<p><strong>' + b.team.abbrev + '</strong> payroll after: ' + fmtM(newPayrollB) + '</p>');
    lines.push('<p class="trade-verdict">' + verdict + '</p>');
    summary.innerHTML = lines.join('');
  }

  renderSide(0);
  renderSide(1);
  renderSummary();
})();
"""


def render_trade_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
    payload = trade_machine_payload(data, teams, players, season)
    machine = f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Trade Machine</h2><span class="muted small-copy">check assets on both sides · BBGM trade values</span></div>
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
        <p class="muted">Build and sanity-check trades, and find contract bargains</p>
      </div>
    </section>
    {machine}
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
    pool = sorted(players + draft_prospects(data), key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
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
            "t": team_abbrev_for_tid(p.get("tid"), teams_by_tid) if safe_int(p.get("tid"), -1) >= 0 else ("Draft" if p.get("tid") == DRAFT_PROSPECT_TID else "FA"),
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


def all_time_leaders_html(data: dict[str, Any], teams: list[dict[str, Any]], root: str = "", start_season: int = 2026) -> str:
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    totals = []
    for player in data.get("players", []):
        rows = [
            s for s in player.get("stats", [])
            if isinstance(s, dict) and not s.get("playoffs") and safe_int(s.get("season")) >= start_season
        ]
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
    ]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>All-Time Leaders</h2><span class="muted small-copy">regular season since {start_season}, including retired players</span></div>
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


def feat_rank(stats: dict[str, Any]) -> int:
    """Sort priority for a single-game feat, so the feats table groups by feat type."""
    pts = safe_int(stats.get("pts"))
    trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
    if safe_int(stats.get("qd")):         return 0   # quadruple-double
    if safe_int(stats.get("td")):         return 1   # triple-double
    if safe_int(stats.get("fxf")):        return 2   # 5x5
    if pts >= 60:                         return 3
    if pts >= 50:                         return 4
    if trb >= 25:                         return 5
    if safe_int(stats.get("ast")) >= 20:  return 6
    if safe_int(stats.get("tp")) >= 10:   return 7
    if safe_int(stats.get("blk")) >= 10:  return 8
    if safe_int(stats.get("stl")) >= 10:  return 9
    return 10


def render_records_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int = 2026) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    current_gids = {str(g.get("gid")) for g in data.get("games", []) if g.get("season") == season}
    feats = [f for f in data.get("playerFeats", []) if isinstance(f, dict)]
    feats.sort(key=lambda f: (feat_rank(f.get("stats") or {}), -safe_int((f.get("stats") or {}).get("pts")), -safe_int(f.get("season"))))
    headers = ["Season", "Player", "Team", "Opp", "Result", "Line", "Feat"]

    def feat_row(feat: dict[str, Any]) -> str:
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
        return "".join([
            td(esc(feat.get("season")), sort=feat.get("season")),
            td(event_player_link(feat.get("pid"), all_players_by_pid, "", label=feat.get("name")), sort=feat.get("name"), cls="name-cell"),
            td(team_label(feat.get("tid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("tid"), teams_by_tid)),
            td(team_label(feat.get("oppTid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("oppTid"), teams_by_tid)),
            td(result_text, sort=feat.get("score")),
            td(line, sort=safe_int(stats.get("pts"))),
            td(badges, sort=feat_rank(stats)),
        ])

    feat_seasons = list(range(start_season, season + 1))
    rows_by_season: dict[int, list[str]] = {yr: [] for yr in feat_seasons}
    for feat in feats:
        yr = safe_int(feat.get("season"))
        if yr in rows_by_season:
            rows_by_season[yr].append(feat_row(feat))
    total_feats = sum(len(r) for r in rows_by_season.values())

    def feat_tab(yr: int, first: bool) -> str:
        return (f'<button type="button" class="{"active" if first else ""}" role="tab" id="tab-feats-{yr}" '
                f'aria-controls="panel-feats-{yr}" aria-selected="{"true" if first else "false"}" '
                f'tabindex="{"0" if first else "-1"}" data-tab-target="panel-feats-{yr}">{yr}</button>')

    feat_tabs = "".join(feat_tab(yr, i == 0) for i, yr in enumerate(feat_seasons))
    feat_panels = "".join(
        f"""
      <div id="panel-feats-{yr}" role="tabpanel" aria-labelledby="tab-feats-{yr}" data-tab-panel{"" if i == 0 else " hidden"}>
        <div class="toolbar">
          <input class="table-search" data-table-filter="feats-{yr}" placeholder="Filter feats…" aria-label="Filter {yr} feats">
        </div>
        {table_html(headers, rows_by_season[yr], table_id=f"feats-{yr}", empty_message=f"No feats recorded in {yr}.")}
      </div>"""
        for i, yr in enumerate(feat_seasons)
    )
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Records &amp; Feats</h1>
        <p class="muted">All-time leaderboards and {total_feats} notable single-game performances</p>
      </div>
    </section>
    {best_performances_card(data, teams, season)}
    {all_time_leaders_html(data, teams, start_season=start_season)}
    <section class="card">
      <div class="section-title-row"><h2>Single-Game Feats</h2></div>
      <div class="tabs" role="tablist" aria-label="Feats by season" data-tabs>
        {feat_tabs}
      </div>
      {feat_panels}
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
  --accent-soft: rgba(91, 157, 255, .14);
  --good: #3fbf72;
  --good-soft: rgba(63, 191, 114, .14);
  --bad: #e2566b;
  --bad-soft: rgba(226, 86, 107, .14);
  --warn: #d9a441;
  --warn-soft: rgba(217, 164, 65, .14);
  --focus: #9bc5ff;
  color-scheme: dark;
}
html[data-theme="light"] {
  --bg: #f2f3f5;
  --panel: #ffffff;
  --panel-2: #edeff2;
  --panel-3: #e2e5ea;
  --line: #d4d9e0;
  --text: #181c22;
  --muted: #5d6671;
  --accent: #2f6fd0;
  --accent-soft: rgba(47, 111, 208, .1);
  --good: #1e9e5a;
  --good-soft: rgba(30, 158, 90, .12);
  --bad: #cd3d55;
  --bad-soft: rgba(205, 61, 85, .12);
  --warn: #a96f00;
  --warn-soft: rgba(169, 111, 0, .12);
  --focus: #174ea6;
  color-scheme: light;
}
html[data-theme="light"] .site-header { background: var(--bg); }
html[data-theme="light"] tbody tr:nth-child(odd) { background: #f7f8fa; }
html[data-theme="light"] .chart-tooltip { background: rgba(242, 243, 245, .96); }
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
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
  }
}

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
  background: var(--bg);
  border-bottom: 1px solid var(--line);
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
  border-radius: .15rem;
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
  border-radius: .15rem;
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
  border-radius: .15rem;
  background: var(--panel);
  box-shadow: 0 10px 30px rgba(0,0,0,.45);
}
.team-menu a {
  display: block;
  white-space: nowrap;
  padding: .35rem .55rem;
  border-radius: .15rem;
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
  border-radius: .15rem;
  background: var(--panel);
}
.page-hero { margin-bottom: .75rem; padding: .8rem 1rem; display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.draft-tabs button { padding: .45rem 1rem; font-size: .9rem; }
[data-draft-panel][hidden] { display: none; }
.draft-overview-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .75rem;
  align-items: start;
}
.draft-overview-row > .card { min-width: 0; }
@media (max-width: 1100px) {
  .draft-overview-row { grid-template-columns: 1fr; }
}
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
  border-radius: .15rem;
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
.table-wrap { overflow-x: auto; border-radius: .15rem; border: 1px solid var(--line); }
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
  cursor: default;
  user-select: none;
  border-bottom: 1px solid var(--line);
}
table[data-sortable] thead th { cursor: pointer; }
table[data-sortable] thead th:hover { color: var(--text); }
table[data-sortable] thead th:focus-visible { color: var(--text); background: var(--panel-3); }
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
.clinch-pre { color: var(--muted); font-weight: 700; margin-right: .2rem; }
tr.playoff-cut > td { border-top: 2px solid var(--accent); }
tr.avg-row > td { border-top: 1px solid var(--line); color: var(--muted); font-style: italic; }

/* ---------- controls ---------- */
.table-search {
  width: min(100%, 20rem);
  padding: .45rem .65rem;
  border-radius: .15rem;
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
  border-radius: .15rem;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--text);
  font: inherit;
  font-size: .85rem;
  text-transform: none;
  letter-spacing: 0;
}
.view-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: .15rem; overflow: hidden; }
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
.tabs {
  display: inline-flex;
  max-width: 100%;
  margin-bottom: .7rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
  overflow: hidden;
}
.tabs button {
  padding: .45rem .75rem;
  border: 0;
  border-left: 1px solid var(--line);
  background: var(--bg);
  color: var(--muted);
  font: inherit;
  font-size: .8rem;
  font-weight: 700;
  cursor: pointer;
}
.tabs button:first-child { border-left: 0; }
.tabs button[aria-selected="true"] { background: var(--panel-3); color: var(--text); }
[data-tab-panel][hidden] { display: none; }
#players-index .col-adv, #players-index .col-p36, #players-index .col-rate { display: none; }
#players-index.show-adv .col-adv { display: table-cell; }
#players-index.show-adv .col-basic, #players-index.show-adv .col-p36, #players-index.show-adv .col-rate { display: none; }
#players-index.show-p36 .col-p36 { display: table-cell; }
#players-index.show-p36 .col-basic, #players-index.show-p36 .col-adv, #players-index.show-p36 .col-rate { display: none; }
#players-index.show-rate .col-rate { display: table-cell; }
#players-index.show-rate .col-basic, #players-index.show-rate .col-adv, #players-index.show-rate .col-p36 { display: none; }
tr.group-hidden { display: none; }
tr.pos-hidden { display: none; }
.pos-filter-bar { margin-bottom: .4rem; }

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
  border-radius: .15rem;
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
.score-stack { flex-direction: column; align-items: stretch; gap: .15rem; }
.score-row { display: flex; justify-content: space-between; gap: .8rem; color: var(--muted); font-size: .85rem; }
.score-row strong { color: var(--muted); font-weight: 500; font-variant-numeric: tabular-nums; }
.score-row.score-won, .score-row.score-won strong { color: var(--text); font-weight: 700; }
.score-stack .score-status { align-self: flex-end; }

/* ---------- schedule grid ---------- */
.schedule-grid th, .schedule-grid td { text-align: center; }
.schedule-grid td:first-child, .schedule-grid th:first-child { text-align: center; }
.schedule-grid td { padding: .18rem .3rem; }
.day-label { color: var(--muted); font-variant-numeric: tabular-nums; }
.off-day { background: rgba(255,255,255,.015); }
.sched-cell { display: block; padding: .12rem .25rem; border-radius: .15rem; color: var(--text); font-size: .76rem; line-height: 1.25; text-decoration: none; }
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
.chart-wrap canvas { display: block; width: 100%; height: 460px; border: 1px solid var(--line); border-radius: .15rem; background: #14181d; cursor: crosshair; }
.chart-tooltip {
  position: absolute;
  z-index: 10;
  pointer-events: none;
  padding: .4rem .55rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
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
  border-radius: .15rem;
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
  border-radius: .15rem;
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
  border-radius: .15rem;
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
  border-radius: .15rem;
  background: var(--panel-2);
}
.big-rating span { color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .07em; font-size: .7rem; }
.big-rating strong { font-size: 1.4rem; font-weight: 700; }
.full-rating-panel { min-width: min(100%, 480px); }
.rating-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; }
.rating-group {
  padding: .55rem .6rem;
  border: 1px solid rgba(255,255,255,.05);
  border-radius: .15rem;
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
  border-radius: .15rem;
  object-fit: cover;
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.candidate-img.placeholder { display: grid; place-items: center; color: var(--muted); font-weight: 700; font-size: .68rem; }

/* ---------- team page ---------- */
.team-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; }
/* ---------- team subnav + hero finance chip ---------- */
.hero-finance {
  display: flex; flex-direction: column; gap: .3rem;
  min-width: min(100%, 14rem);
  padding: .55rem .7rem;
  border: 1px solid var(--line); border-radius: .15rem; background: var(--panel-2);
}
.hero-fin-row { display: flex; justify-content: space-between; gap: .8rem; font-size: .82rem; }
.hero-fin-row span { color: var(--muted); font-weight: 500; }
.team-subnav { display: inline-flex; margin: 0 0 1rem; border: 1px solid var(--line); border-radius: .2rem; overflow: hidden; }
.subnav-link {
  padding: .5rem .95rem; font-size: .82rem; font-weight: 600; text-decoration: none;
  color: var(--muted); background: var(--bg); border-left: 1px solid var(--line);
}
.subnav-link:first-child { border-left: 0; }
.subnav-link:hover { color: var(--text); background: var(--panel-2); }
.subnav-link.active { color: var(--text); background: var(--panel-3); font-weight: 800; box-shadow: inset 0 -2px 0 var(--accent); }

/* ---------- finance ledger ---------- */
.ledger-table { width: 100%; border-collapse: collapse; font-size: .86rem; }
.ledger-table th { text-align: right; color: var(--muted); font-weight: 600; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; padding: .35rem .5rem; border-bottom: 1px solid var(--line); }
.ledger-table th:first-child { text-align: left; }
.ledger-table td { padding: .3rem .5rem; border-bottom: 1px solid rgba(255,255,255,.04); }
.ledger-num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ledger-table tr.ledger-subtotal td { border-top: 1px solid var(--line); font-weight: 600; }
.ledger-table tr.ledger-total td { border-top: 2px solid var(--line); font-size: 1rem; padding-top: .5rem; }
.ledger-table tr.ledger-total .ledger-label { font-weight: 700; }
.fin-rules { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
@media (max-width: 700px) { .fin-rules { grid-template-columns: 1fr; } }
.fin-rules h3 { margin: 0 0 .4rem; font-size: .82rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.fin-list { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: .25rem; font-size: .86rem; }
/* roster role dividers: heavier line after Starters (5) and Bench (10) on the default Stats table */
#roster-stats tbody tr:nth-child(5) > *,
#roster-stats tbody tr:nth-child(10) > * { border-bottom: 2px solid var(--line); }

/* ---------- game pages ---------- */
.click-row { cursor: pointer; }
.button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: .4rem .65rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
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
.mini-score-table.table-wrap { border-radius: .15rem; }
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
  .hero-finance { margin-top: .75rem; }
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
  border-radius: .15rem;
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
.leader-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: .6rem; }
.leader-box { padding: .5rem .6rem; border: 1px solid rgba(255,255,255,.05); border-radius: .15rem; background: var(--bg); }
.leader-box h3 { margin: 0 0 .35rem; font-size: .7rem; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.leader-mini-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.leader-col-rank { width: 1.45rem; }
.leader-col-value { width: 3.4rem; }
.leader-mini-table td {
  padding: .16rem 0;
  border: 0;
  vertical-align: baseline;
  font-size: .8rem;
  line-height: 1.35;
}
.leader-mini-table .leader-rank { padding-right: .35rem; }
.leader-player-cell { width: auto; min-width: 0; text-align: left; }
.leader-player-wrap {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: .4rem;
  align-items: baseline;
  min-width: 0;
}
.leader-name-block { display: block; min-width: 0; text-align: left; }
.leader-name-block .player-link {
  display: block;
  max-width: 100%;
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.25;
}
.leader-mini-table .team-dot { margin-right: 0; }
.leader-mini-table .leader-team { display: block; width: auto; padding-left: 0; white-space: nowrap; margin-top: .05rem; }
.leader-mini-table .leader-value { padding-left: .4rem; }
.leader-mini-table tbody tr, .leader-mini-table tbody tr:nth-child(odd), .leader-mini-table tbody tr:nth-child(even) { background: transparent; }
.leader-list { list-style: none; margin: 0; padding: 0; }
.leader-list li { display: flex; align-items: center; gap: .4rem; padding: .16rem 0; font-size: .8rem; }
.leader-rank { color: var(--muted); min-width: .9rem; text-align: right; font-variant-numeric: tabular-nums; }
.leader-team { color: var(--muted); font-size: .7rem; }
.leader-value { margin-left: auto; text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
.team-dot { display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin-right: .4rem; vertical-align: baseline; }
#injury-report { width: 100%; table-layout: auto; }
#injury-report th, #injury-report td { white-space: normal; word-break: break-word; }
.group-head { text-align: center !important; border-left: 1px solid var(--line); }

/* ---------- finances ---------- */
.fit-table { width: max-content; max-width: 100%; }
.fit-table table { width: auto; }
.expiry-badge {
  display: inline-flex;
  align-items: center;
  margin-left: .28rem;
  padding: .03rem .32rem;
  border: 1px solid color-mix(in srgb, var(--warn) 42%, var(--line));
  border-radius: .15rem;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: .66rem;
  font-weight: 700;
  letter-spacing: .02em;
  vertical-align: middle;
}

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
  border-radius: .15rem;
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
  border-radius: .15rem;
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
.game-log-win > td:first-child { box-shadow: inset 3px 0 0 var(--good); }
.game-log-loss > td:first-child { box-shadow: inset 3px 0 0 var(--bad); }
.game-log-next > td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
.game-note {
  max-width: 30rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.table-link {
  padding: .18rem .45rem;
  font-size: .72rem;
}
.depth-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .6rem; }
@media (max-width: 900px) { .depth-grid { grid-template-columns: repeat(2, 1fr); } }
.depth-col { padding: .5rem .6rem; border: 1px solid rgba(255,255,255,.05); border-radius: .15rem; background: var(--panel-2); }
.depth-col h3 { margin: 0 0 .35rem; font-size: .7rem; font-weight: 700; letter-spacing: .07em; color: var(--muted); }
.pick-row { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .4rem; }
.pick-chip {
  display: inline-flex;
  align-items: center;
  gap: .3rem;
  padding: .26rem .55rem;
  border-radius: .15rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  font-size: .78rem;
  font-weight: 600;
}

/* ---------- game pages ---------- */
.series-row { display: flex; flex-wrap: wrap; gap: .45rem; }
.series-chip {
  padding: .35rem .6rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
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
/* projection (fan) chart */
.proj-wrap { max-width: 700px; }
.proj-chart { width: 100%; max-width: 700px; height: auto; display: block; cursor: crosshair; }
.proj-band-80 { fill: var(--accent); opacity: .12; stroke: none; }
.proj-band-50 { fill: var(--accent); opacity: .20; stroke: none; }
.proj-median { fill: none; stroke: var(--accent); stroke-width: 2; stroke-dasharray: 5 3; }
.proj-median-dot { fill: var(--accent); }
.proj-divider { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; opacity: .55; }
.proj-hover-line { stroke: var(--muted); stroke-width: 1; pointer-events: none; }
.proj-hover-dot { fill: var(--accent); stroke: var(--bg, #0f1318); stroke-width: 1.5; pointer-events: none; }
.proj-key-band { background: var(--accent); opacity: .35; height: 8px; border-radius: 1px; }
.proj-wrap .chart-tooltip { min-width: 9.5rem; max-width: 13rem; white-space: normal; }
.proj-wrap .chart-tooltip span { display: block; }

/* ---------- rating trajectories (subrating fan-sparkline grid) ---------- */
.subg-grid { display: flex; flex-direction: column; gap: 1rem; }
.subg-group-title {
  margin: 0 0 .4rem; font-size: .68rem; font-weight: 700;
  letter-spacing: .07em; text-transform: uppercase; color: var(--muted);
}
.subg-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: .5rem; }
.subg-cell {
  border: 1px solid var(--line); border-radius: .25rem;
  background: var(--panel-2, var(--bg)); padding: .4rem .45rem .3rem;
  display: flex; flex-direction: column; gap: .15rem;
  transition: border-color .12s ease, background .12s ease;
}
.subg-cell.subg-active { border-color: var(--accent); }
.subg-head { display: flex; align-items: baseline; justify-content: space-between; gap: .35rem; }
.subg-label {
  font-size: .66rem; font-weight: 600; letter-spacing: .02em;
  color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.subg-delta {
  font-size: .6rem; font-weight: 700; line-height: 1; flex: none;
  padding: .12rem .3rem; border-radius: .6rem; border: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.subg-up { color: var(--good); border-color: var(--good); }
.subg-down { color: var(--bad); border-color: var(--bad); }
.subg-flat { color: var(--muted); }
.subg-cur { display: flex; align-items: baseline; gap: .25rem; }
.subg-cur-val { font-size: 1.15rem; font-weight: 700; line-height: 1; color: var(--text); font-variant-numeric: tabular-nums; }
.subg-cur-cap { font-size: .58rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.subg-svg { width: 100%; height: 42px; display: block; margin-top: .1rem; overflow: visible; }
.subg-band { fill: var(--accent); opacity: .14; stroke: none; }
.subg-hist { fill: none; stroke: var(--text); stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.subg-hist-dot { fill: var(--text); }
.subg-median { fill: none; stroke: var(--accent); stroke-width: 1.4; stroke-dasharray: 3 2; vector-effect: non-scaling-stroke; }
.subg-divider { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 2; opacity: .5; vector-effect: non-scaling-stroke; }
.subg-hline { stroke: var(--accent); stroke-width: 1; opacity: .6; vector-effect: non-scaling-stroke; pointer-events: none; }
.subg-hdot { fill: var(--accent); stroke: var(--bg); stroke-width: 1; pointer-events: none; }
.subg-empty { opacity: .55; }
.subg-empty .subg-cur-val { font-size: .95rem; color: var(--muted); }
.subg-key { display: inline-block; width: .8rem; vertical-align: middle; margin-right: .25rem; }
.subg-key-hist { height: 2px; background: var(--text); }
.subg-key-med { height: 0; border-top: 2px dashed var(--accent); }
.subg-key-band { height: 8px; border-radius: 1px; background: var(--accent); opacity: .35; }
@media (max-width: 760px) { .subg-row { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 420px) { .subg-row { grid-template-columns: 1fr; } }
/* --- Projection table (#projection-table) ------------------------------- */
.projtab-badge {
  display: inline-block;
  vertical-align: middle;
  margin-left: 0.4em;
  padding: 0.1em 0.55em;
  font-size: 0.62em;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 38%, transparent);
  border-radius: 999px;
}
.projtab-caption { margin: 0.15rem 0 0.6rem; }
.projtab-table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.projtab-table th,
.projtab-table td {
  padding: 0.35rem 0.5rem;
  text-align: center;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.projtab-table th {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}
/* Sticky Year column so the row stays anchored while scrolling horizontally. */
.projtab-table .projtab-sticky {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--bg);
  text-align: left;
}
.projtab-table thead .projtab-sticky { z-index: 2; }
.projtab-year { font-weight: 600; color: var(--text); }
.projtab-age { color: var(--muted); }
/* Slight emphasis on the Ovr column to anchor the eye. */
.projtab-ovr-col {
  border-left: 1px solid var(--line);
  border-right: 1px solid var(--line);
}
.projtab-table td.projtab-ovr-col .projtab-med { font-weight: 700; }
.projtab-cell { line-height: 1.15; }
.projtab-med {
  display: block;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text);
}
/* Muted, italic, smaller range text marks the projected/uncertain nature. */
.projtab-range {
  display: block;
  margin-top: 0.05rem;
  font-size: 0.68rem;
  font-style: italic;
  color: var(--muted);
}
@media (max-width: 720px) {
  .projtab-table th,
  .projtab-table td { padding: 0.3rem 0.4rem; }
  .projtab-range { font-size: 0.62rem; }
}
/* ---------- tone tags (projected-standings legend) ---------- */
.scout-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .3rem;
}
.scout-tag {
  display: inline-flex;
  align-items: center;
  border-radius: .15rem;
  border: 1px solid var(--line);
  background: var(--panel-3);
  color: var(--text);
  font-weight: 500;
  font-size: .75rem;
  padding: .1rem .5rem;
  cursor: default;
  position: relative;
}
.scout-tag::before {
  content: "";
  width: .42rem;
  height: .42rem;
  border-radius: 50%;
  margin-right: .4rem;
  background: var(--muted);
  flex: none;
}
.scout-tag--good { border-color: color-mix(in srgb, var(--good) 45%, var(--line)); }
.scout-tag--good::before { background: var(--good); }
.scout-tag--bad { border-color: color-mix(in srgb, var(--bad) 45%, var(--line)); }
.scout-tag--bad::before { background: var(--bad); }
.scout-tag--neutral { color: var(--muted); }
.scout-tag--neutral::before { background: var(--muted); }
/* ---------- team trajectory (projected team strength fan chart) ---------- */
/* Uses --team-primary as the on-brand band/line accent, falling back to --accent. */
.ttraj-wrap { max-width: 700px; --ttraj-accent: var(--team-primary, var(--accent)); }
.ttraj-chart { width: 100%; max-width: 700px; height: auto; display: block; cursor: crosshair; }
.ttraj-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 1rem;
  margin: .15rem 0 .55rem;
}
.ttraj-toggle {
  display: inline-flex; border: 1px solid var(--line); border-radius: .2rem;
  overflow: hidden; background: var(--panel-2);
}
.ttraj-btn {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  color: var(--muted); font: inherit; font-size: .76rem; font-weight: 600;
  padding: .32rem .7rem; border-right: 1px solid var(--line);
  letter-spacing: .02em; transition: background .12s, color .12s;
}
.ttraj-btn:last-child { border-right: 0; }
.ttraj-btn:hover { color: var(--text); }
.ttraj-btn.active {
  color: var(--text);
  background: color-mix(in srgb, var(--team-primary, var(--accent)) 22%, var(--panel-2));
  box-shadow: inset 0 -2px 0 var(--team-primary, var(--accent));
}
.ttraj-rank {
  font-size: .78rem; font-weight: 700; letter-spacing: .03em;
  color: var(--text); padding: .12rem .5rem; border-radius: .15rem;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--team-primary, var(--accent)) 14%, transparent);
}
.ttraj-key { display: inline-flex; align-items: center; gap: .35rem; }
.ttraj-k { display: inline-block; width: .9rem; vertical-align: middle; }
.ttraj-k-band {
  height: 8px; border-radius: 1px;
  background: var(--team-primary, var(--accent));  /* solid fallback for no color-mix */
  background: color-mix(in srgb, var(--team-primary, var(--accent)) 38%, transparent);
}
.ttraj-k-median { height: 2px; background: var(--team-primary, var(--accent)); }
.ttraj-window {
  display: inline-block; margin-left: .15rem;
  color: var(--muted);
}
.ttraj-window strong { color: var(--text); font-variant-numeric: tabular-nums; }

/* fan bands + median in the team's color */
.ttraj-band-80 { fill: var(--team-primary, var(--accent)); opacity: .12; stroke: none; }
.ttraj-band-50 { fill: var(--team-primary, var(--accent)); opacity: .22; stroke: none; }
.ttraj-median { fill: none; stroke: var(--team-primary, var(--accent)); stroke-width: 2.2; }
.ttraj-cur {
  fill: var(--team-primary, var(--accent));
  stroke: var(--bg, #0f1318); stroke-width: 1.6;
}
/* reference lines */
.ttraj-ref { stroke-width: 1; stroke-dasharray: 4 4; fill: none; }
.ttraj-ref-avg { stroke: var(--muted); opacity: .7; }
.ttraj-ref-cont { stroke: var(--good); opacity: .75; }
.ttraj-ref-label {
  fill: var(--muted); font-size: 9.5px; font-weight: 600;
  letter-spacing: .02em; opacity: .85;
}
/* hover scrubber */
.ttraj-hover-line { stroke: var(--muted); stroke-width: 1; pointer-events: none; }
.ttraj-hover-dot {
  fill: var(--team-primary, var(--accent));
  stroke: var(--bg, #0f1318); stroke-width: 1.5; pointer-events: none;
}
.ttraj-wrap .chart-tooltip { min-width: 9.5rem; max-width: 13rem; white-space: normal; }
.ttraj-wrap .chart-tooltip span { display: block; }

@media (max-width: 600px) {
  .ttraj-controls { gap: .45rem .7rem; }
  .ttraj-btn { padding: .3rem .55rem; font-size: .72rem; }
}

/* ---------- projected power-ranking bump chart ---------- */
.bump-card .bump-sub { margin: .1rem 0 .7rem; }

.bump-legend { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .65rem; }
.bump-chip {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .24rem .46rem; border: 1px solid var(--line); border-radius: .15rem;
  background: var(--panel-2); color: var(--text); font: inherit; font-size: .74rem;
  font-weight: 600; line-height: 1; cursor: pointer;
  transition: opacity .12s ease, border-color .12s ease, box-shadow .12s ease;
}
.bump-chip-dot { width: .6rem; height: .6rem; border-radius: 50%; background: var(--bump-color, var(--muted)); flex: none; }
.bump-chip-ab { letter-spacing: 0; }
.bump-chip.is-active { border-color: var(--bump-color, var(--accent)); box-shadow: 0 0 0 1px var(--bump-color, var(--accent)) inset; }
.bump-chip.is-dim { opacity: .38; }

.bump-wrap { overflow-x: auto; }
.bump-chart { display: block; width: 100%; min-width: 540px; height: auto; font-family: inherit; }

.bump-rowline { stroke: var(--line); stroke-width: 1; opacity: .5; }
.bump-collline { stroke: var(--line); stroke-width: 1; opacity: .35; }
.bump-rankaxis { fill: var(--muted); font-size: 11px; text-anchor: middle; font-weight: 600; }
.bump-seasontick { fill: var(--text); font-size: 11px; text-anchor: middle; font-weight: 700; }
.bump-seasonyr { fill: var(--muted); font-size: 10px; text-anchor: middle; }
.bump-axislabel { fill: var(--muted); font-size: 9px; text-anchor: middle; text-transform: uppercase; letter-spacing: .08em; opacity: .8; }

/* The halo carries a real base fill (--bg) so it never falls back to opaque
   black; the colored line carries team identity. */
.bump-halo { fill: none; stroke: var(--bg); stroke-width: 5.5; stroke-linejoin: round; stroke-linecap: round; opacity: .85; }
.bump-line { fill: none; stroke: var(--bump-color, var(--muted)); stroke-width: 2.6; stroke-linejoin: round; stroke-linecap: round; transition: opacity .12s ease, stroke-width .12s ease; }
.bump-node { fill: var(--bump-color, var(--muted)); stroke: var(--bg); stroke-width: 1.4; transition: opacity .12s ease; }
.bump-hit { fill: none; stroke: transparent; stroke-width: 16; stroke-linejoin: round; stroke-linecap: round; cursor: pointer; }
.bump-link { cursor: pointer; }

/* End/start abbrev labels: team-colored, with a --bg halo (paint-order:stroke)
   so they stay legible where lines cross behind them. */
.bump-endlabel { fill: var(--bump-color, var(--text)); font-size: 11px; font-weight: 800; paint-order: stroke; stroke: var(--bg); stroke-width: 2.6px; stroke-linejoin: round; transition: opacity .12s ease; }
.bump-endlabel--start { text-anchor: end; }
.bump-endlabel--end { text-anchor: start; }
.bump-leader { stroke: var(--line); stroke-width: 1; opacity: .6; }

/* Highlight: dim everything except the active team. */
.bump-has-active .bump-team.is-dim .bump-line { opacity: .14; }
.bump-has-active .bump-team.is-dim .bump-node { opacity: .14; }
.bump-has-active .bump-team.is-dim .bump-halo { opacity: .2; }
.bump-has-active .bump-team.is-active .bump-line { stroke-width: 3.4; }
.bump-has-active .bump-endlabel.is-dim { opacity: .2; }

.bump-tooltip { min-width: 8.5rem; max-width: 12rem; white-space: normal; }
.bump-tooltip strong { display: block; font-size: .82rem; }
.bump-tooltip span { display: block; color: var(--muted); }
.bump-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: .4rem;
  margin-top: .65rem;
}
.bump-summary-row {
  display: grid;
  grid-template-columns: auto minmax(2.8rem, auto) repeat(4, minmax(0, 1fr));
  gap: .25rem .45rem;
  align-items: center;
  padding: .42rem .5rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
  font-size: .74rem;
  min-width: 0;
}
.bump-summary-row:hover { border-color: var(--bump-color, var(--accent)); text-decoration: none; }
.bump-summary-row strong { color: var(--text); }
.bump-summary-row span:not(.bump-chip-dot) { color: var(--muted); }

@media (max-width: 560px) {
  .bump-chart { min-width: 480px; }
}
/* Projected Standings (league projections page) -- .pstand- namespace */
.pstand .pstand-caption { margin: 2px 0 12px; max-width: 70ch; }

.pstand-wrap { -webkit-overflow-scrolling: touch; }

.pstand-table {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  font-variant-numeric: tabular-nums;
}

.pstand-table th,
.pstand-table td {
  padding: 7px 9px;
  text-align: center;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

/* Year header */
.pstand-yr {
  font-weight: 600;
  color: var(--muted);
  vertical-align: bottom;
}
.pstand-yr-num { display: block; color: var(--text); font-size: 0.95em; }
.pstand-yr-tag {
  display: inline-block;
  margin-top: 2px;
  font-size: 0.62rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: 700;
  opacity: 0.75;
}
.pstand-yr-tag--now { color: var(--accent); }
.pstand-yr-tag--proj { color: var(--muted); }

/* Sticky first column (team) */
.pstand-team-h,
.pstand-team {
  position: sticky;
  left: 0;
  z-index: 2;
  text-align: left;
  background: var(--panel);
  min-width: 140px;
}
.pstand-team-h { z-index: 3; color: var(--muted); font-weight: 600; }
/* soft edge so scrolled cells don't bleed into the sticky column */
.pstand-team::after,
.pstand-team-h::after {
  content: "";
  position: absolute;
  top: 0; right: -10px; bottom: 0;
  width: 10px;
  pointer-events: none;
  background: linear-gradient(to right, var(--line), transparent);
  opacity: 0.5;
}

.pstand-name {
  display: flex;
  align-items: center;
  gap: 7px;
  text-decoration: none;
  color: var(--text);
  font-weight: 600;
}
.pstand-name:hover .pstand-name-txt { color: var(--accent); }
.pstand-dot {
  flex: 0 0 auto;
  width: 11px; height: 11px;
  border-radius: 50%;
  box-shadow: 0 0 0 1.5px rgba(0,0,0,0.35), 0 0 0 2.5px rgba(255,255,255,0.12);
}
.pstand-name-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
}
.pstand-abbr {
  display: none;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
}

/* Data cell */
.pstand-cell { line-height: 1.25; }
.pstand-val {
  display: block;
  font-weight: 700;
  font-size: 1.02rem;
  color: var(--text);
}
.pstand-rank {
  display: inline-block;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 0.66rem;
  font-weight: 700;
  color: var(--muted);
  background: var(--panel-3);
  background: color-mix(in srgb, var(--text) 9%, transparent);
}
.pstand-rank--hi { color: var(--text); }
.pstand-rec {
  display: block;
  margin-top: 1px;
  font-size: 0.7rem;
  color: var(--muted);
}

/* Current-season anchor for the continuity scenario (structural gray, not a colored bar). */
.pstand-now { border-left: 2px solid var(--line); }
thead .pstand-now { border-left: 2px solid var(--line); }

.pstand-table tbody tr:hover .pstand-cell {
  box-shadow: inset 0 0 0 999px rgba(255,255,255,0.03);  /* dark-theme fallback */
  box-shadow: inset 0 0 0 999px color-mix(in srgb, var(--text) 5%, transparent);  /* theme-aware */
}

.pstand-legend { margin-top: 12px; }
.pstand-mobile { display: none; }
.pstand-mobile-card {
  display: grid;
  gap: .45rem;
  padding: .55rem .65rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
  background: var(--panel-2);
}
.pstand-mobile-seasons {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(4.8rem, 1fr));
  gap: .35rem;
}
.pstand-mobile-season {
  display: grid;
  gap: .05rem;
  padding: .35rem .4rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
  background: var(--panel);
  text-align: center;
}
.pstand-mobile-season em {
  color: var(--muted);
  font-size: .66rem;
  font-style: normal;
  font-weight: 700;
}
.pstand-mobile-season strong { font-size: .95rem; }
.pstand-mobile-season small { color: var(--muted); font-size: .68rem; }

@media (max-width: 560px) {
  .pstand-wrap { display: none; }
  .pstand-mobile { display: grid; gap: .5rem; }
}
/* ---------- contract horizon (team page) ---------- */
.tcon-wrap { margin-top: .35rem; }
.tcon-chart { display: block; width: 100%; height: auto; }
.tcon-col { fill: transparent; stroke: none; }  /* transparent base: without color-mix, never opaque black */
.tcon-gridline { stroke: var(--line); stroke-width: 1; opacity: .5; }
.tcon-axis {
  fill: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.tcon-bar {
  fill: var(--team-primary, var(--accent));
  stroke: color-mix(in srgb, var(--team-primary, var(--accent)) 70%, var(--line));
  stroke-width: 1;
}
.tcon-overflow { fill: var(--team-primary, var(--accent)); }
.tcon-name {
  fill: var(--text);
  font-size: 12px;
}
.tcon-ovr {
  fill: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.tcon-expiry {
  fill: var(--bg);
  font-size: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  paint-order: stroke;
  stroke: #000;  /* legible halo fallback where color-mix is unsupported */
  stroke: color-mix(in srgb, var(--team-primary, var(--accent)) 55%, #000);
  stroke-width: 2.4px;
  pointer-events: none;
}
.tcon-foot-label {
  fill: var(--muted);
  font-size: 11px;
}
.tcon-foot-count {
  fill: var(--text);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.tcon-row:hover .tcon-bar { stroke-width: 1.5; }
.tcon-caption { margin-top: .5rem; }
.tcon-note { margin-top: .25rem; }
@media (max-width: 520px) {
  .tcon-name { font-size: 11px; }
  .tcon-axis, .tcon-ovr { font-size: 10px; }
}
.rotation-map td.rot-cell { text-align: center; min-width: 2.1rem; font-variant-numeric: tabular-nums; }
.rotation-map th.rot-w { color: var(--good); }
.rotation-map th.rot-l { color: var(--bad); }
.rotation-map th { text-align: center; }
.milestone-list li { gap: .5rem; }
.milestone-list .small-copy { margin-left: auto; text-align: right; }

/* ---------- history ---------- */
.bracket { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; margin-bottom: .6rem; }
.bracket-round h4 { margin: 0 0 .3rem; font-size: .68rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.bracket-series {
  min-width: 11rem;
  margin-bottom: .45rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
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
  border-radius: .15rem;
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
  border-radius: .15rem;
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


/* ---------- round 3 ---------- */
.rank-move { display: inline-block; min-width: 1.6rem; font-size: .68rem; font-variant-numeric: tabular-nums; }
.rank-flat { color: var(--muted); opacity: .5; }
.l10-dots { display: inline-flex; gap: 2px; align-items: center; }
.l10-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.l10-w { background: var(--good); }
#playoff-odds td.seed-cut, #playoff-odds th:nth-child(10) { border-left: 1px solid var(--line); }
#playoff-odds th:nth-child(6) { border-left: 1px solid var(--line); }
#playoff-odds td:nth-child(6) { border-left: 1px solid var(--line); }
.l10-l { background: var(--bad); opacity: .7; }
.high-row { display: flex; flex-wrap: wrap; gap: .45rem; }
.high-chip {
  display: inline-flex;
  align-items: baseline;
  gap: .4rem;
  padding: .3rem .6rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
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
.honors-table-wrap { margin-top: .6rem; }
.honors-table th, .honors-table td { text-align: left; }
.honor-label-cell { color: var(--muted); font-size: .72rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.honor-cell { min-width: 9rem; }
.tx-season { border: 1px solid var(--line); border-radius: .15rem; background: var(--panel-2); padding: .45rem .7rem; margin-bottom: .5rem; }
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
  border-radius: .15rem;
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
  border-radius: .15rem;
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
.cmp-bar { display: inline-block; width: 4.5rem; height: .4rem; margin-right: .5rem; border-radius: .15rem; background: rgba(255,255,255,.07); overflow: hidden; vertical-align: middle; }
.cmp-bar i { display: block; height: 100%; background: var(--accent); }
.cmp-best .cmp-bar i { background: var(--good); }

.table-wrap { position: relative; }
.copy-table {
  position: absolute;
  top: .3rem;
  right: .3rem;
  z-index: 5;
  padding: .1rem .4rem;
  border: 1px solid var(--line);
  border-radius: .15rem;
  background: var(--panel-2);
  color: var(--muted);
  font-size: .72rem;
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s;
}
.table-wrap:hover .copy-table,
.table-wrap:focus-within .copy-table,
.copy-table:focus-visible { opacity: 1; }
.copy-table:hover { color: var(--text); border-color: var(--accent); }
.nav-burger { display: none; }
.score-stack .recap { width: 100%; line-height: 1.35; }

@media (max-width: 900px) {
  .nav-search { flex: none; width: 100%; }
  .home-columns { grid-template-columns: 1fr; }
  .nav-burger {
    display: inline-flex;
    padding: .35rem .7rem;
    border: 1px solid var(--line);
    border-radius: .15rem;
    background: var(--panel-2);
    color: var(--text);
    font: inherit;
    font-size: .85rem;
    cursor: pointer;
  }
  .primary-nav { display: none; width: 100%; }
  .primary-nav.open { display: flex; }
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

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const caption = table.querySelector('caption');
    if (caption) table.setAttribute('aria-label', caption.textContent.trim());
    function activateSort(header, index) {
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const rows = Array.from(tbody.rows);
      const descending = header.classList.contains("sort-asc");
      headers.forEach((h) => {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      header.classList.add(descending ? "sort-desc" : "sort-asc");
      header.setAttribute("aria-sort", descending ? "descending" : "ascending");
      rows.sort((ra, rb) => {
        const result = compareValues(cellValue(ra, index), cellValue(rb, index));
        return descending ? -result : result;
      });
      rows.forEach((row) => tbody.appendChild(row));
    }
    headers.forEach((header, index) => {
      header.tabIndex = 0;
      header.setAttribute("aria-sort", "none");
      header.addEventListener("click", () => activateSort(header, index));
      header.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        activateSort(header, index);
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

  document.querySelectorAll('[data-pos-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.posFilter);
    if (!table || table.dataset.posCol === undefined) return;
    const col = Number(table.dataset.posCol);
    const apply = () => {
      const f = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const cell = row.cells[col];
        const pos = cell ? cell.textContent.trim() : '';
        // single-letter groups (G/F/C) match by substring; two-letter picks match exactly
        const match = f === 'all' || (f.length === 1 ? pos.indexOf(f) !== -1 : pos === f);
        row.classList.toggle('pos-hidden', !match);
      });
    };
    select.addEventListener('change', apply);
    apply();
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
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        wrap.querySelectorAll('button').forEach((b) => {
          b.classList.remove('active');
          b.setAttribute('aria-pressed', 'false');
        });
        button.classList.add('active');
        button.setAttribute('aria-pressed', 'true');
        table.classList.remove('show-adv', 'show-p36', 'show-rate');
        if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      });
    });
  });

  document.querySelectorAll('[data-group-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.groupToggle);
    if (!table) return;
    const apply = () => {
      const active = new Set(
        Array.from(wrap.querySelectorAll('button.active')).map((b) => b.dataset.group)
      );
      Array.from(table.tBodies[0].rows).forEach((row) => {
        if (!row.dataset.group) return;
        row.classList.toggle('group-hidden', !active.has(row.dataset.group));
      });
    };
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        button.classList.toggle('active');
        button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
        apply();
      });
    });
    apply();
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
    const minGpInput = document.querySelector('[data-chart-mingp]');
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
    if (minGpInput && hashParams.get('mingp')) minGpInput.value = hashParams.get('mingp');
    if (labelsInput && hashParams.get('labels') === '1') labelsInput.checked = true;

    function syncHash() {
      const params = new URLSearchParams();
      params.set('x', xKey);
      params.set('y', yKey);
      if (selPos && selPos.value !== 'all') params.set('pos', selPos.value);
      if (minMinInput && Number(minMinInput.value) > 0) params.set('min', minMinInput.value);
      if (minGpInput && Number(minGpInput.value) > 0) params.set('mingp', minGpInput.value);
      if (labelsInput && labelsInput.checked) params.set('labels', '1');
      history.replaceState(null, '', '#' + params.toString());
    }

    data.teams.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.setProperty('--dot', t.color);
      btn.setAttribute('aria-label', 'Toggle ' + t.abbrev + ' players');
      btn.setAttribute('aria-pressed', 'true');
      btn.innerHTML = '<span class=\"dot\"></span>' + t.abbrev;
      btn.addEventListener('click', () => {
        if (hidden.has(t.abbrev)) hidden.delete(t.abbrev); else hidden.add(t.abbrev);
        btn.classList.toggle('off', hidden.has(t.abbrev));
        btn.setAttribute('aria-pressed', hidden.has(t.abbrev) ? 'false' : 'true');
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
      const minGp = minGpInput ? Number(minGpInput.value) || 0 : 0;
      const pts = data.players.filter((p) =>
        !hidden.has(p.team)
        && Number.isFinite(p.v[xKey]) && Number.isFinite(p.v[yKey])
        && (posFilter === 'all' || (p.pos || '').includes(posFilter))
        && (!minMin || (Number.isFinite(p.v.min) && p.v.min >= minMin))
        && (!minGp || (Number.isFinite(p.v.gp) && p.v.gp >= minGp)));
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

      // label every visible point (overlap allowed)
      if (labelsInput && labelsInput.checked && pts.length) {
        ctx.fillStyle = '#c6cdd5';
        ctx.textAlign = 'left';
        pts.forEach((p) => {
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
    if (minGpInput) minGpInput.addEventListener('input', () => { syncHash(); draw(); });
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

    function close() {
      searchResults.hidden = true;
      selected = -1;
      searchInput.setAttribute('aria-expanded', 'false');
      searchInput.setAttribute('aria-activedescendant', '');
    }

    function syncSelected(links) {
      links.forEach((l, i) => {
        const on = i === selected;
        l.classList.toggle('selected', on);
        l.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      searchInput.setAttribute('aria-activedescendant', selected >= 0 && links[selected] ? links[selected].id : '');
    }

    function renderResults(matches) {
      if (!matches.length) {
        searchResults.innerHTML = '<div class="search-empty" role="option" aria-disabled="true">No matches.</div>';
        searchResults.hidden = false;
        searchInput.setAttribute('aria-expanded', 'true');
        searchInput.setAttribute('aria-activedescendant', '');
        return;
      }
      searchResults.innerHTML = matches.map((m, i) =>
        '<a id="search-option-' + i + '" role="option" aria-selected="false" href="' + root + escapeHtml(m.u) + '"><span>' + escapeHtml(m.n) + '</span><span class="muted">' + escapeHtml(m.t) + '</span></a>').join('');
      searchResults.hidden = false;
      searchInput.setAttribute('aria-expanded', 'true');
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
      syncSelected(links);
    });
    document.addEventListener('click', (event) => {
      if (!searchInput.contains(event.target) && !searchResults.contains(event.target)) close();
    });
  }

  // ---------- copy table as TSV ----------
  document.querySelectorAll('.table-wrap').forEach((wrap) => {
    const table = wrap.querySelector('table');
    if (!table || !navigator.clipboard) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-table';
    btn.title = 'Copy table for spreadsheets';
    btn.setAttribute('aria-label', 'Copy table for spreadsheets');
    btn.textContent = '⧉';
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      const lines = Array.from(table.querySelectorAll('tr')).map((tr) =>
        Array.from(tr.cells).map((cell) => cell.textContent.trim().replace(/\s+/g, ' ')).join('\t'));
      navigator.clipboard.writeText(lines.join('\n')).then(() => {
        btn.textContent = '✓';
        btn.setAttribute('aria-label', 'Copied table');
        setTimeout(() => {
          btn.textContent = '⧉';
          btn.setAttribute('aria-label', 'Copy table for spreadsheets');
        }, 1200);
      });
    });
    wrap.appendChild(btn);
  });

  // ---------- mobile nav toggle ----------
  const burger = document.querySelector('[data-nav-burger]');
  if (burger) {
    const nav = document.getElementById(burger.getAttribute('aria-controls')) || document.querySelector('.primary-nav');
    burger.addEventListener('click', () => {
      if (!nav) return;
      const open = !nav.classList.contains('open');
      nav.classList.toggle('open', open);
      burger.classList.toggle('open');
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || !nav || !nav.classList.contains('open')) return;
      nav.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    });
  }

  // ---------- generic tabs ----------
  document.querySelectorAll('[data-tabs]').forEach((tablist) => {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"][data-tab-target]'));
    if (!tabs.length) return;
    function activate(tab, focus) {
      tabs.forEach((btn) => {
        const on = btn === tab;
        const panel = document.getElementById(btn.dataset.tabTarget || '');
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', () => activate(tab, false));
      tab.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
        if (event.key === 'Home') next = tabs[0];
        if (event.key === 'End') next = tabs[tabs.length - 1];
        if (!next) return;
        event.preventDefault();
        activate(next, true);
      });
    });
    activate(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0], false);
  });

  // ---------- draft year tabs ----------
  const draftTabs = document.querySelector('[data-draft-tabs]');
  if (draftTabs) {
    const buttons = Array.from(draftTabs.querySelectorAll('button[data-draft-tab]'));
    function activateDraft(button, focus) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      });
      document.querySelectorAll('[data-draft-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.draftPanel !== button.dataset.draftTab;
      });
      if (focus) button.focus();
    }
    buttons.forEach((button, index) => {
      button.tabIndex = button.classList.contains('active') ? 0 : -1;
      button.addEventListener('click', () => {
        activateDraft(button, false);
      });
      button.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = buttons[(index + 1) % buttons.length];
        if (event.key === 'ArrowLeft') next = buttons[(index - 1 + buttons.length) % buttons.length];
        if (event.key === 'Home') next = buttons[0];
        if (event.key === 'End') next = buttons[buttons.length - 1];
        if (!next) return;
        event.preventDefault();
        activateDraft(next, true);
      });
    });
    if (buttons.length) activateDraft(buttons.find((b) => b.classList.contains('active')) || buttons[0], false);
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

  // ---------- player development projection charts (interactive hover) ----------
  document.querySelectorAll('[data-proj-chart]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.proj-chart');
    const tip = wrap.querySelector('[data-proj-tooltip]');
    const hLine = wrap.querySelector('[data-proj-hover-line]');
    const hDot = wrap.querySelector('[data-proj-hover-dot]');
    const dataEl = wrap.parentElement &&
      wrap.parentElement.querySelector('script[type="application/json"][id^="proj-data-"]');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (v - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(v);

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() {
      tip.hidden = true;
      hLine.style.display = 'none';
      hDot.style.display = 'none';
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const hi = d.hist.s.indexOf(season);
      const pi = d.proj.s.indexOf(season);
      let markY = null;
      let html = '';
      if (season <= d.cur && hi >= 0) {
        markY = d.hist.ovr[hi];
        html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
               '<span>Overall ' + fmt(d.hist.ovr[hi]) + ' · Potential ' + fmt(d.hist.pot[hi]) + '</span>';
        if (season === d.cur && pi >= 0) html += '<span>Projection starts here</span>';
      } else if (pi >= 0) {
        markY = d.proj.p50[pi];
        html = '<strong>' + season + ' · projected</strong>' +
               '<span>Median ' + fmt(d.proj.p50[pi]) + ' · 80% ' +
               fmt(d.proj.p10[pi]) + '–' + fmt(d.proj.p90[pi]) + '</span>' +
               '<span>50% ' + fmt(d.proj.p25[pi]) + '–' + fmt(d.proj.p75[pi]) + '</span>';
      } else {
        hide();
        return;
      }
      const cx = xs(season);
      hLine.setAttribute('x1', cx);
      hLine.setAttribute('x2', cx);
      hLine.style.display = '';
      hDot.setAttribute('cx', cx);
      hDot.setAttribute('cy', yv(markY));
      hDot.style.display = '';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;  // flip left
      if (left + tw > rect.width) left = rect.width - tw - 4;                // still over: pin right
      if (left < 0) left = 4;                                               // never off the left
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // subrating grid hover-sync: one scrubber drives all 15 mini-charts.
  document.querySelectorAll('[data-subrating-grid]').forEach((grid) => {
    const pid = grid.getAttribute('data-subg-pid');
    const dataEl = grid.parentElement &&
      grid.parentElement.querySelector('script[id="subrating-data-' + pid + '"]');
    if (!dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const sSpan = Math.max(1, d.smax - d.smin);
    const xs = (s) => g.ml + (s - d.smin) / sSpan * g.pw;

    const cells = [];
    grid.querySelectorAll('.subg-cell[data-subg-key]').forEach((cell) => {
      const key = cell.getAttribute('data-subg-key');
      const chart = d.charts[key];
      if (!chart) return;
      cells.push({
        cell: cell,
        chart: chart,
        svg: cell.querySelector('svg.subg-svg'),
        hline: cell.querySelector('.subg-hline'),
        hdot: cell.querySelector('.subg-hdot'),
        valEl: cell.querySelector('[data-subg-val]'),
        capEl: cell.querySelector('[data-subg-cap]'),
        curVal: cell.querySelector('[data-subg-val]')
          ? cell.querySelector('[data-subg-val]').textContent : ''
      });
    });
    if (!cells.length) return;

    function yv(v, lo, hi) {
      return g.mt + g.ph - (v - lo) / Math.max(1e-9, hi - lo) * g.ph;
    }

    function seasonFromEvent(svg, evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const loc = pt.matrixTransform(ctm.inverse());
      let season = Math.round(d.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < d.smin) season = d.smin;
      if (season > d.smax) season = d.smax;
      return season;
    }

    function clear() {
      cells.forEach((c) => {
        c.cell.classList.remove('subg-active');
        if (c.hline) c.hline.style.display = 'none';
        if (c.hdot) c.hdot.style.display = 'none';
        if (c.valEl) c.valEl.textContent = c.curVal;
        if (c.capEl) c.capEl.textContent = 'now';
      });
    }

    function sync(season) {
      const cx = xs(season);
      const future = season > d.cur;
      cells.forEach((c) => {
        const ch = c.chart;
        let v = null;
        if (season <= d.cur) {
          const hi = ch.hist.s.indexOf(season);
          if (hi >= 0) v = ch.hist.v[hi];
        } else {
          const pi = ch.proj.s.indexOf(season);
          if (pi >= 0) v = ch.proj.p50[pi];
        }
        if (v === null) {
          c.cell.classList.remove('subg-active');
          if (c.hline) c.hline.style.display = 'none';
          if (c.hdot) c.hdot.style.display = 'none';
          if (c.valEl) c.valEl.textContent = c.curVal;
          if (c.capEl) c.capEl.textContent = 'now';
          return;
        }
        c.cell.classList.add('subg-active');
        const cy = yv(v, ch.g.lo, ch.g.hi);
        if (c.hline) {
          c.hline.setAttribute('x1', cx);
          c.hline.setAttribute('x2', cx);
          c.hline.style.display = '';
        }
        if (c.hdot) {
          c.hdot.setAttribute('cx', cx);
          c.hdot.setAttribute('cy', cy);
          c.hdot.style.display = '';
        }
        if (c.valEl) c.valEl.textContent = Math.round(v);
        if (c.capEl) c.capEl.textContent = season + (future ? ' · proj' : (season === d.cur ? ' · now' : ''));
      });
    }

    cells.forEach((c) => {
      if (!c.svg) return;
      c.svg.addEventListener('mousemove', (evt) => {
        const s = seasonFromEvent(c.svg, evt);
        if (s !== null) sync(s);
      });
    });
    grid.addEventListener('mouseleave', clear);
  });

  // ---------- team trajectory (projected team strength fan chart) ----------
  document.querySelectorAll('[data-team-traj]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.ttraj-chart');
    const tip = wrap.querySelector('[data-ttraj-tooltip]');
    const hLine = wrap.querySelector('[data-ttraj-hover-line]');
    const hDot = wrap.querySelector('[data-ttraj-hover-dot]');
    const bandsG = wrap.querySelector('[data-ttraj-bands]');
    const lineG = wrap.querySelector('[data-ttraj-line]');
    const tid = wrap.getAttribute('data-ttraj-tid');
    const root = wrap.closest('section') || wrap.parentElement;
    const dataEl = document.getElementById('team-traj-' + tid);
    if (!svg || !tip || !dataEl || !bandsG || !lineG || !root) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const SVGNS = 'http://www.w3.org/2000/svg';
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (Math.max(0, v) - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(Math.max(0, v));
    let active = 'proj';

    function bandPts(upper, lower) {
      const fwd = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(upper[i]).toFixed(1));
      const back = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(lower[i]).toFixed(1)).reverse();
      return fwd.concat(back).join(' ');
    }
    function linePts(p50) {
      return d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(p50[i]).toFixed(1)).join(' ');
    }

    function draw(scn) {
      const b = d.scn[scn];
      if (!b) return;
      active = scn;
      bandsG.innerHTML = '';
      const p80 = document.createElementNS(SVGNS, 'polygon');
      p80.setAttribute('points', bandPts(b.p90, b.p10));
      p80.setAttribute('class', 'ttraj-band-80');
      const p50b = document.createElementNS(SVGNS, 'polygon');
      p50b.setAttribute('points', bandPts(b.p75, b.p25));
      p50b.setAttribute('class', 'ttraj-band-50');
      bandsG.appendChild(p80); bandsG.appendChild(p50b);
      lineG.innerHTML = '';
      const ml = document.createElementNS(SVGNS, 'polyline');
      ml.setAttribute('points', linePts(b.p50));
      ml.setAttribute('class', 'ttraj-median');
      lineG.appendChild(ml);
    }

    function updateWindow(scn) {
      const out = root.querySelector('[data-ttraj-window] strong');
      if (!out || d.contender == null) return;
      const p50 = d.scn[scn].p50;
      const hit = [];
      d.seasons.forEach((s, i) => { if (p50[i] >= d.contender) hit.push(s); });
      let txt = 'none in window';
      if (hit.length) {
        const run = [hit[0]];
        for (let i = 1; i < hit.length; i++) {
          if (hit[i] === run[run.length - 1] + 1) run.push(hit[i]); else break;
        }
        txt = run[0] === run[run.length - 1] ? '' + run[0] : run[0] + '–' + run[run.length - 1];
      }
      out.textContent = txt;
    }

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() { tip.hidden = true; hLine.style.display = 'none'; hDot.style.display = 'none'; }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const i = d.seasons.indexOf(season);
      if (i < 0) { hide(); return; }
      const b = d.scn[active];
      const med = b.p50[i];
      const cx = xs(season);
      hLine.setAttribute('x1', cx); hLine.setAttribute('x2', cx); hLine.style.display = '';
      hDot.setAttribute('cx', cx); hDot.setAttribute('cy', yv(med)); hDot.style.display = '';
      const cnt = (d.counts && d.counts[i] != null) ? d.counts[i] : null;
      let html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
        '<span>' + (d.labels[active] || active) + '</span>' +
        '<span>Median ' + fmt(med) + ' · 80% ' + fmt(b.p10[i]) + '–' + fmt(b.p90[i]) + '</span>';
      if (cnt != null) html += '<span>' + cnt + ' under contract</span>';
      tip.innerHTML = html; tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    root.querySelectorAll('.ttraj-btn[data-ttraj-scn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const scn = btn.getAttribute('data-ttraj-scn');
        if (!d.scn[scn]) return;
        root.querySelectorAll('.ttraj-btn').forEach((b2) => {
          const on = b2 === btn;
          b2.classList.toggle('active', on);
          b2.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        draw(scn);
        updateWindow(scn);
        hide();
      });
    });

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // power ranking bump: hover/highlight a team line + tooltip, dim the rest.
  document.querySelectorAll('[data-bump]').forEach((wrap) => {
    const card = wrap.closest('.bump-card') || wrap;
    const svg = wrap.querySelector('svg.bump-chart');
    const tip = wrap.querySelector('[data-bump-tooltip]');
    const dataEl = document.getElementById('bump-data');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const n = (d.seasons || []).length;
    const byId = {};
    (d.teams || []).forEach((t) => { byId[String(t.tid)] = t; });

    const groups = Array.from(card.querySelectorAll('.bump-team[data-tid]'));
    const labels = Array.from(card.querySelectorAll('.bump-endlabel[data-tid]'));
    const chips = Array.from(card.querySelectorAll('.bump-chip[data-tid]'));
    if (!groups.length) return;

    function setActive(tid) {
      tid = String(tid);
      card.classList.add('bump-has-active');
      const apply = (el) => {
        const on = String(el.getAttribute('data-tid')) === tid;
        el.classList.toggle('is-active', on);
        el.classList.toggle('is-dim', !on);
        if (el.matches && el.matches('.bump-chip')) el.setAttribute('aria-pressed', on ? 'true' : 'false');
      };
      groups.forEach(apply); labels.forEach(apply); chips.forEach(apply);
    }
    function clear() {
      card.classList.remove('bump-has-active');
      [].concat(groups, labels, chips).forEach((el) => el.classList.remove('is-active', 'is-dim'));
      chips.forEach((el) => el.setAttribute('aria-pressed', 'false'));
      tip.hidden = true;
    }

    function seasonIndex(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm || n < 2) return 0;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const loc = pt.matrixTransform(ctm.inverse());
      let i = Math.round((loc.x - g.ml) / (g.pw / (n - 1)));
      return Math.max(0, Math.min(n - 1, i));
    }

    function showTip(tid, i, evt) {
      const t = byId[String(tid)];
      if (!t) return;
      // abbrev comes from league data; escape it before innerHTML (defense-in-depth).
      const escHtml = (s) => String(s).replace(/[&<>"]/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      const games = (t.games && t.games[i] != null) ? t.games[i] : 0;
      const wins = (t.rec && t.rec[i] != null) ? t.rec[i] : 0;
      let html = '<strong>' + escHtml(t.abbrev || '') + ' · ' + d.seasons[i] +
        (i === 0 ? ' · now' : '') + '</strong>' +
        '<span>Rank #' + t.ranks[i] + ' of ' + d.rows + '</span>' +
        '<span>Strength ' + Math.round(t.p50[i]) + '</span>';
      if (games > 0) html += '<span>Est. ' + wins + '–' + Math.max(0, games - wins) + '</span>';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    groups.forEach((grp) => {
      const tid = grp.getAttribute('data-tid');
      grp.addEventListener('mouseenter', () => setActive(tid));
      grp.addEventListener('mousemove', (e) => { setActive(tid); showTip(tid, seasonIndex(e), e); });
    });
    labels.forEach((l) => l.addEventListener('mouseenter', () => setActive(l.getAttribute('data-tid'))));
    chips.forEach((c) => {
      const tid = c.getAttribute('data-tid');
      c.addEventListener('mouseenter', () => setActive(tid));
      c.addEventListener('focus', () => setActive(tid));
      c.addEventListener('click', () => setActive(tid));
    });
    card.addEventListener('mouseleave', clear);
  });

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
    apply_roster_moves(data)
    season = current_season(data)
    teams = sorted(data.get("teams", []), key=team_sort_key)
    players = active_players(data)
    fa_players = free_agents(data)
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
    fa_market_year = season + 1 if phase_value(data) >= 8 else season
    write_text(out_dir / "free-agency.html", render_free_agency_page(fa_players, teams, season, start_season, all_players=players, market_year=fa_market_year))
    write_text(out_dir / "players" / "index.html", render_players_index(players, teams, season, start_season, data=data))
    write_text(out_dir / "history.html", render_history_page(data, teams))
    write_text(out_dir / "records.html", render_records_page(data, teams, season, start_season=start_season))
    write_text(out_dir / "draft.html", render_draft_page(data, teams, season))
    write_text(out_dir / "trade.html", render_trade_page(data, teams, players, season))
    write_text(out_dir / "compare.html", render_compare_page(data, teams, players, season, start_season))

    game_logs = build_game_logs(data, season)
    league_fin = compute_league_finances(data, teams, players, season, (league_sim(data, teams, season) or {}).get("teams"))
    for team in teams:
        roster = [player for player in players if player.get("tid") == team.get("tid")]
        slug = team_slug(team)
        tfin = league_fin["teams"].get(safe_int(team.get("tid"), -99))
        write_text(out_dir / "teams" / f"{slug}.html", render_team_roster_page(team, roster, teams, season, start_season, data=data, game_items=game_items, game_logs=game_logs, tfin=tfin))
        write_text(out_dir / "teams" / f"{slug}-games.html", render_team_games_page(team, roster, teams, season, start_season, data=data, game_items=game_items, game_logs=game_logs, tfin=tfin))
        write_text(out_dir / "teams" / f"{slug}-finances.html", render_team_finances_page(team, roster, teams, season, start_season, data=data, tfin=tfin, league_fin=league_fin))

    def write_player_pages(p: dict[str, Any], log_entries: list[dict[str, Any]] | None) -> None:
        slug = player_slug(p)
        for suffix, html in render_player_pages(p, teams, season, start_season, log_entries=log_entries).items():
            write_text(out_dir / "players" / f"{slug}{suffix}.html", html)

    prospects = draft_prospects(data)
    for prospect in prospects:
        write_player_pages(prospect, None)

    for player in players:
        write_player_pages(player, game_logs.get(safe_int(player.get("pid"), -1)))

    # Write a page for every game linked from the site: the schedule/team slate (game_items)
    # plus the current season's completed games incl. playoffs (home "Latest Results", the
    # playoff bracket, and records feats all link to these gids).
    page_items = {str(item.get("gid")): item for item in game_items if item.get("gid") is not None}
    for item in completed_game_items(data, season, playoffs=None):
        page_items.setdefault(str(item.get("gid")), item)
    all_game_pages = list(page_items.values())
    for item in all_game_pages:
        write_text(out_dir / "games" / f"{game_slug_from_gid(item.get('gid'))}.html", render_game_page(item, all_game_pages, teams, players, safe_int(item.get("season"), season)))

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
