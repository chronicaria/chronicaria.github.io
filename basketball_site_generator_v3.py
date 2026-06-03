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
    if amount >= 1000:
        millions = amount / 1000
        if abs(millions - round(millions)) < 1e-9:
            return f"${int(round(millions))}M"
        return f"${millions:.2f}M".rstrip("0").rstrip(".")
    return f"${int(round(amount))}K"


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
    return f"{fmt_money(amount)} thru {esc(exp)}"


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
    status = "over" if cap > 0 and payroll > cap else "under"
    return f"""
    <div class="salary-summary {status}">
      <div class="salary-copy"><span>Total salary</span><strong>{fmt_money(payroll)} / {fmt_money(cap)}</strong></div>
      <div class="salary-bar" aria-hidden="true"><span style="width: {pct:.1f}%"></span></div>
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


def td(content: Any, sort: Any = None, cls: str = "", html_content: bool = True) -> str:
    sort_attr = f' data-sort="{sort_value(sort)}"' if sort is not None else ""
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    body = str(content) if html_content else esc(content)
    return f"<td{cls_attr}{sort_attr}>{body}</td>"


def th(label: str, cls: str = "") -> str:
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    return f"<th{cls_attr}>{esc(label)}</th>"


def table_html(headers: list[str], rows: list[str], table_id: str | None = None, empty_message: str = "No players found.") -> str:
    table_id_attr = f' id="{esc(table_id)}"' if table_id else ""
    if not rows:
        return f'<p class="empty-state">{esc(empty_message)}</p>'
    header_html = "".join(th(label) for label in headers)
    body_html = "\n".join(f"<tr>{row}</tr>" for row in rows)
    return f"""
    <div class="table-wrap">
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


def player_link(player: dict[str, Any], root: str = "") -> str:
    number = player.get("jerseyNumber")
    number_html = f'<span class="muted number">{esc(number)}</span> ' if number not in (None, "") else ""
    skills = latest_rating(player).get("skills") or []
    skill_html = "".join(f'<span class="mini-skill">{esc(skill)}</span>' for skill in skills)
    return f'{number_html}<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a> {skill_html}'


def mood_html(player: dict[str, Any]) -> str:
    mood = player.get("moodTraits") or []
    if not mood:
        return "—"
    return " ".join(f'<span class="mood-chip">{esc(m)}</span>' for m in mood)


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
        link("Scores", f"{root}scores.html", "scores"),
        link("Schedule", f"{root}schedule.html", "schedule"),
        link("Players", f"{root}players/index.html", "players"),
        link("Free Agency", f"{root}free-agency.html", "free-agency"),
    ]
    team_links = []
    for team in sorted(teams, key=team_sort_key):
        key = f"team-{team.get('tid')}"
        label = team_full_name(team)
        team_links.append(link(label, team_url(team, root), key))

    dropdown_class = "team-dropdown active" if active.startswith("team-") else "team-dropdown"
    return f"""
    <header class="site-header">
      <div class="brand"><a href="{root}index.html">League Browser</a></div>
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="{root}assets/styles.css">
  <script defer src="{root}assets/site.js"></script>
</head>
<body>
  {nav_html(teams, root, active)}
  <main class="page-shell">
    {body}
  </main>
</body>
</html>
"""


def roster_row(player: dict[str, Any], season: int, start_season: int, root: str) -> str:
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
        td(stat.get("yearsWithTeam", "—"), sort=stat.get("yearsWithTeam")),
        td(fmt_number(gp, 0), sort=gp),
        td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
        td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts")),
        td(fmt_number((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0, 1), sort=((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0)),
        td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast")),
        td(fmt_number(stat.get("per"), 1), sort=stat.get("per")),
        td(mood_html(player), sort=" ".join(player.get("moodTraits") or [])),
    ])


def roster_table(title: str, players: list[dict[str, Any]], season: int, start_season: int, root: str, table_id: str) -> str:
    headers = ["Name", "Pos", "Age", "Ovr", "Pot", "Contract", "YWT", "G", "MP", "PTS", "TRB", "AST", "PER", "Mood"]
    rows = [roster_row(p, season, start_season, root) for p in players]
    return f"""
    <section class="card roster-section">
      <div class="section-title-row">
        <h2>{esc(title)}</h2>
        <span class="count-pill">{len(players)}</span>
      </div>
      {table_html(headers, rows, table_id=table_id, empty_message="No players in this group.")}
    </section>
    """


def render_team_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, cap: float) -> str:
    sorted_roster = sorted(roster, key=lambda p: (p.get("rosterOrder", 10**9), -latest_rating(p, season).get("ovr", 0), player_name(p)))
    starters = sorted_roster[:5]
    bench = sorted_roster[5:10]
    reserves = sorted_roster[10:]
    team_full = team_full_name(team)
    colors = team.get("colors") or ["#6f7cff"]
    primary = colors[0] if colors else "#6f7cff"
    secondary = colors[1] if len(colors) > 1 else primary
    payroll = team_payroll(sorted_roster, season)
    body = f"""
    <section class="page-hero team-hero" style="--team-primary:{esc(primary)};--team-secondary:{esc(secondary)}">
      <div>
        <p class="eyebrow">Team roster</p>
        <h1>{esc(team_full)}</h1>
        <p class="muted">{esc(team.get('abbrev', ''))} · {len(sorted_roster)} players</p>
      </div>
      {salary_cap_html(payroll, cap)}
    </section>
    {roster_table("Starters", starters, season, start_season, "../", f"team-{team.get('tid')}-starters")}
    {roster_table("Bench", bench, season, start_season, "../", f"team-{team.get('tid')}-bench")}
    {roster_table("Reserve", reserves, season, start_season, "../", f"team-{team.get('tid')}-reserve")}
    """
    return page_html(team_full, body, teams, root="../", active=f"team-{team.get('tid')}")


def free_agent_row(player: dict[str, Any], season: int, start_season: int, root: str) -> str:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    contract = player.get("contract") or {}
    return "".join([
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - (player.get("born") or {}).get("year", season) if isinstance((player.get("born") or {}).get("year"), int) else None)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
        td(fmt_money(contract.get("amount")), sort=contract.get("amount")),
        td(esc(contract.get("exp", "—")), sort=contract.get("exp")),
        td(fmt_number(gp, 0), sort=gp),
        td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
        td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts")),
        td(fmt_number((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0, 1), sort=((float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0)),
        td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast")),
        td(fmt_number(stat.get("per"), 1), sort=stat.get("per")),
        td(mood_html(player), sort=" ".join(player.get("moodTraits") or [])),
    ])


def render_free_agency_page(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int) -> str:
    sorted_players = sorted(players, key=lambda p: (-latest_rating(p, season).get("ovr", 0), -latest_rating(p, season).get("pot", 0), player_name(p)))
    headers = ["Name", "Pos", "Age", "Ovr", "Pot", "Asking For", "Exp", "G", "MP", "PTS", "TRB", "AST", "PER", "Mood"]
    rows = [free_agent_row(p, season, start_season, "") for p in sorted_players]
    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">League</p>
        <h1>Free Agency</h1>
        <p class="muted">{len(sorted_players)} available players</p>
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
    sorted_players = sorted(players, key=lambda p: (p.get("tid", 999), p.get("rosterOrder", 9999), player_name(p)))
    headers = ["Name", "Team", "Pos", "Age", "Ovr", "Pot", "Contract", "G", "MP", "PTS", "TRB", "AST", "PER"]
    rows = []
    for p in sorted_players:
        rating = latest_rating(p, season)
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
        rows.append("".join([
            td(player_link(p, "../"), sort=player_name(p), cls="name-cell"),
            td(team_label(p.get("tid"), teams_by_tid, "../"), sort=team_label(p.get("tid"), teams_by_tid, as_link=False)),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(age(p, season), sort=(season - (p.get("born") or {}).get("year", season) if isinstance((p.get("born") or {}).get("year"), int) else None)),
            td(rating_delta_html(p, "ovr", rating), sort=rating.get("ovr")),
            td(rating_delta_html(p, "pot", rating), sort=rating.get("pot")),
            td(fmt_contract(p), sort=(p.get("contract") or {}).get("amount")),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts")),
            td(fmt_number(trb_pg, 1), sort=trb_pg),
            td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast")),
            td(fmt_number(stat.get("per"), 1), sort=stat.get("per")),
        ]))

    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">League</p>
        <h1>Players</h1>
        <p class="muted">{len(sorted_players)} non-retired roster and free-agent players</p>
      </div>
    </section>
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="players-index" placeholder="Filter players…" aria-label="Filter players">
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


def render_player_page(player: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    regular = regular_stats_since(player, start_season)
    playoffs = playoff_stats_since(player, start_season)
    body = "".join([
        render_player_hero(player, teams_by_tid, season, start_season),
        player_summary_rows(player, teams_by_tid, season, start_season),
        per_game_table(player, regular, teams_by_tid, "../", "Per Game · Regular Season", f"regular-{player.get('pid')}"),
        shot_table(player, regular, teams_by_tid, "../", "Shot Locations and Feats · Regular Season", f"shots-{player.get('pid')}"),
        advanced_table(player, regular, teams_by_tid, "../", "Advanced · Regular Season", f"advanced-{player.get('pid')}"),
        ratings_table(player, start_season),
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


def standings_table(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
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
    headers = ["Team", "W", "L", "%", "GB", "Home", "Road", "Div", "Conf", "PS", "PA", "MOV", "Streak", "L10", "Tiebreaker"]
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
            html_rows.append("".join([
                td(f'<span class="row-rank">{rank}</span>{team_anchor(team)}{clinch_html(team_season)}', sort=rank, cls="name-cell"),
                td(fmt_number(row["won"], 0), sort=row["won"]),
                td(fmt_number(row["lost"], 0), sort=row["lost"]),
                td(fmt_win_pct(row["pct"]), sort=row["pct"]),
                td(gb_text, sort=gb if leader else None),
                td(fmt_record(team_season.get("wonHome"), team_season.get("lostHome")), sort=team_season.get("wonHome")),
                td(fmt_record(team_season.get("wonAway"), team_season.get("lostAway")), sort=team_season.get("wonAway")),
                td(fmt_record(team_season.get("wonDiv"), team_season.get("lostDiv")), sort=team_season.get("wonDiv")),
                td(fmt_record(team_season.get("wonConf"), team_season.get("lostConf")), sort=team_season.get("wonConf")),
                td(fmt_number(team_stat_per_game(stat, "pts"), 1), sort=team_stat_per_game(stat, "pts")),
                td(fmt_number(team_stat_per_game(stat, "oppPts"), 1), sort=team_stat_per_game(stat, "oppPts")),
                td(fmt_signed(mov, 1), sort=mov, cls=plus_minus_class(mov)),
                td(streak_text(team_season.get("streak")), sort=team_season.get("streak")),
                td(last_ten_text(team_season.get("lastTen")), sort=last_ten_text(team_season.get("lastTen"))),
                td(esc(team_season.get("tiebreaker", "—")), sort=team_season.get("tiebreaker", "")),
            ]))
        title = confs_by_cid.get(cid, f"Conference {cid}" if cid is not None else "Independent")
        sections.append(f'''
        <section class="card home-section standings-section">
          <div class="section-title-row"><h2>{esc(title)}</h2></div>
          {table_html(headers, html_rows, table_id=f"standings-{esc(cid)}", empty_message="No standings data found.")}
        </section>
        ''')
    return "".join(sections)


def weighted_roster_value(roster: list[dict[str, Any]], season: int, key: str, healthy_only: bool = False) -> float | None:
    ordered = sorted(roster, key=lambda p: (p.get("rosterOrder", 10**9), -latest_rating(p, season).get("ovr", 0), player_name(p)))
    if healthy_only:
        ordered = [p for p in ordered if (p.get("injury") or {}).get("type", "Healthy") in ("Healthy", "")]
    ordered = ordered[:10]
    if not ordered:
        return None
    weights = [5, 4.5, 4, 3.5, 3, 2.5, 2, 1.5, 1.25, 1]
    total = 0.0
    weight_sum = 0.0
    for player, weight in zip(ordered, weights):
        rating = latest_rating(player, season)
        if key not in rating:
            continue
        total += safe_float(rating.get(key), 0.0) * weight
        weight_sum += weight
    return total / weight_sum if weight_sum else None


def fallback_team_rating(roster: list[dict[str, Any]], season: int, healthy_only: bool = False) -> float | None:
    value = weighted_roster_value(roster, season, "ovr", healthy_only=healthy_only)
    if value is None:
        return None
    return value * 1.65


def rank_desc(values: dict[int, float | None]) -> dict[int, int | None]:
    ordered = sorted([(tid, value) for tid, value in values.items() if value is not None and math.isfinite(value)], key=lambda item: (-item[1], item[0]))
    ranks: dict[int, int | None] = {tid: None for tid in values}
    last_value = None
    last_rank = 0
    for index, (tid, value) in enumerate(ordered, 1):
        if last_value is None or abs(value - last_value) > 1e-9:
            last_rank = index
            last_value = value
        ranks[tid] = last_rank
    return ranks


def power_rankings_table(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
    ga = data.get("gameAttributes") or {}
    confs_by_cid = {conf.get("cid"): conf.get("name", f"Conference {conf.get('cid')}") for conf in ga.get("confs", []) if isinstance(conf, dict)}
    divs_by_did = {div.get("did"): div.get("name", f"Division {div.get('did')}") for div in ga.get("divs", []) if isinstance(div, dict)}
    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        if isinstance(player.get("tid"), int) and player.get("tid") >= 0:
            roster_by_tid[player["tid"]].append(player)

    metric_values: dict[str, dict[int, float | None]] = {key: {} for key, _ in TEAM_RATING_RANK_KEYS}
    team_infos = []
    for team in teams:
        tid = int(team.get("tid"))
        roster = roster_by_tid.get(tid, [])
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        current = team_season.get("ovrEnd", team_season.get("ovrStart"))
        current = safe_float(current, float("nan"))
        if not math.isfinite(current) or current <= 0:
            current = fallback_team_rating(roster, season, healthy_only=False) or 0.0
        healthy = fallback_team_rating(roster, season, healthy_only=True)
        healthy = current if healthy is None else max(current, healthy)
        pct = win_pct(team_season.get("won"), team_season.get("lost"))
        mov = team_mov(stat) or 0.0
        avg_age = team_season.get("avgAge")
        if avg_age is None and roster:
            ages = [safe_float(age(p, season), 0.0) for p in roster if age(p, season) != "—"]
            avg_age = sum(ages) / len(ages) if ages else None
        score = current + 12 * (pct or 0.0) + mov
        for key, _ in TEAM_RATING_RANK_KEYS:
            metric_values[key][tid] = weighted_roster_value(roster, season, key)
        team_infos.append({
            "team": team,
            "tid": tid,
            "season": team_season,
            "stat": stat,
            "current": current,
            "healthy": healthy,
            "pct": pct,
            "mov": mov,
            "avgAge": avg_age,
            "score": score,
        })

    ranks_by_key = {key: rank_desc(values) for key, values in metric_values.items()}
    team_infos.sort(key=lambda info: (-info["score"], team_full_name(info["team"])))

    headers = ["#", "Team", "Conference", "Division", "Current", "Healthy", "W", "L", "L10", "MOV", "Age"] + [label for _, label in TEAM_RATING_RANK_KEYS]
    rows = []
    for rank, info in enumerate(team_infos, 1):
        team = info["team"]
        team_season = info["season"]
        cells = [
            td(rank, sort=rank),
            td(team_anchor(team), sort=team_full_name(team), cls="name-cell"),
            td(esc(team_conference_name(team_season or team, confs_by_cid)), sort=team_conference_name(team_season or team, confs_by_cid)),
            td(esc(team_division_name(team_season or team, divs_by_did)), sort=team_division_name(team_season or team, divs_by_did)),
            td(fmt_number(info["current"], 0), sort=info["current"]),
            td(fmt_number(info["healthy"], 0), sort=info["healthy"]),
            td(fmt_number(team_season.get("won"), 0), sort=team_season.get("won")),
            td(fmt_number(team_season.get("lost"), 0), sort=team_season.get("lost")),
            td(last_ten_text(team_season.get("lastTen")), sort=last_ten_text(team_season.get("lastTen"))),
            td(fmt_signed(info["mov"], 1), sort=info["mov"], cls=plus_minus_class(info["mov"])),
            td(fmt_number(info["avgAge"], 1), sort=info["avgAge"]),
        ]
        for key, _ in TEAM_RATING_RANK_KEYS:
            rank_value = ranks_by_key[key].get(info["tid"])
            cells.append(td(fmt_number(rank_value, 0), sort=rank_value))
        rows.append("".join(cells))

    return f'''
    <section class="card home-section">
      <div class="section-title-row"><h2>Power Rankings</h2><span class="muted">Team rating plus rating-category ranks</span></div>
      {table_html(headers, rows, table_id="power-rankings", empty_message="No power rankings available.")}
    </section>
    '''


def team_stats_table(teams: list[dict[str, Any]], season: int) -> str:
    infos = []
    for team in teams:
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        pct = win_pct(team_season.get("won"), team_season.get("lost"))
        infos.append({"team": team, "season": team_season, "stat": stat, "pct": pct, "mov": team_mov(stat)})
    infos.sort(key=lambda info: (-(info["pct"] if info["pct"] is not None else -1), -safe_float((info["season"] or {}).get("won")), team_full_name(info["team"])))

    headers = ["#", "Team", "G", "W", "L", "%", "Age", "FG", "FGA", "FG%", "3P", "3PA", "3P%", "2P", "2PA", "2P%", "FT", "FTA", "FT%", "ORB", "DRB", "TRB", "AST", "TOV", "STL", "BLK", "PF", "PTS", "MOV"]
    rows = []
    stat_totals: dict[str, float] = defaultdict(float)
    total_gp = 0.0
    ages = []
    for rank, info in enumerate(infos, 1):
        team = info["team"]
        team_season = info["season"]
        stat = info["stat"]
        gp = safe_float(stat.get("gp"), 0.0)
        total_gp += gp
        if stat:
            for key in ["fg", "fga", "tp", "tpa", "ft", "fta", "orb", "drb", "ast", "tov", "stl", "blk", "pf", "pts", "oppPts"]:
                stat_totals[key] += safe_float(stat.get(key), 0.0)
        if team_season.get("avgAge") is not None:
            ages.append(safe_float(team_season.get("avgAge"), 0.0))
        two = safe_float(stat.get("fg"), 0.0) - safe_float(stat.get("tp"), 0.0)
        two_a = safe_float(stat.get("fga"), 0.0) - safe_float(stat.get("tpa"), 0.0)
        trb_pg = (safe_float(stat.get("orb"), 0.0) + safe_float(stat.get("drb"), 0.0)) / gp if gp else None
        cells = [
            td(rank, sort=rank),
            td(team_anchor(team), sort=team_full_name(team), cls="name-cell"),
            td(fmt_number(gp if gp else None, 0), sort=gp),
            td(fmt_number(team_season.get("won"), 0), sort=team_season.get("won")),
            td(fmt_number(team_season.get("lost"), 0), sort=team_season.get("lost")),
            td(fmt_win_pct(info["pct"]), sort=info["pct"]),
            td(fmt_number(team_season.get("avgAge"), 1), sort=team_season.get("avgAge")),
            td(fmt_number(team_stat_per_game(stat, "fg"), 1), sort=team_stat_per_game(stat, "fg")),
            td(fmt_number(team_stat_per_game(stat, "fga"), 1), sort=team_stat_per_game(stat, "fga")),
            td(fmt_pct(made_pct(stat.get("fg"), stat.get("fga"))), sort=made_pct(stat.get("fg"), stat.get("fga"))),
            td(fmt_number(team_stat_per_game(stat, "tp"), 1), sort=team_stat_per_game(stat, "tp")),
            td(fmt_number(team_stat_per_game(stat, "tpa"), 1), sort=team_stat_per_game(stat, "tpa")),
            td(fmt_pct(made_pct(stat.get("tp"), stat.get("tpa"))), sort=made_pct(stat.get("tp"), stat.get("tpa"))),
            td(fmt_number(two / gp if gp else None, 1), sort=(two / gp if gp else None)),
            td(fmt_number(two_a / gp if gp else None, 1), sort=(two_a / gp if gp else None)),
            td(fmt_pct(made_pct(two, two_a)), sort=made_pct(two, two_a)),
            td(fmt_number(team_stat_per_game(stat, "ft"), 1), sort=team_stat_per_game(stat, "ft")),
            td(fmt_number(team_stat_per_game(stat, "fta"), 1), sort=team_stat_per_game(stat, "fta")),
            td(fmt_pct(made_pct(stat.get("ft"), stat.get("fta"))), sort=made_pct(stat.get("ft"), stat.get("fta"))),
            td(fmt_number(team_stat_per_game(stat, "orb"), 1), sort=team_stat_per_game(stat, "orb")),
            td(fmt_number(team_stat_per_game(stat, "drb"), 1), sort=team_stat_per_game(stat, "drb")),
            td(fmt_number(trb_pg, 1), sort=trb_pg),
            td(fmt_number(team_stat_per_game(stat, "ast"), 1), sort=team_stat_per_game(stat, "ast")),
            td(fmt_number(team_stat_per_game(stat, "tov"), 1), sort=team_stat_per_game(stat, "tov")),
            td(fmt_number(team_stat_per_game(stat, "stl"), 1), sort=team_stat_per_game(stat, "stl")),
            td(fmt_number(team_stat_per_game(stat, "blk"), 1), sort=team_stat_per_game(stat, "blk")),
            td(fmt_number(team_stat_per_game(stat, "pf"), 1), sort=team_stat_per_game(stat, "pf")),
            td(fmt_number(team_stat_per_game(stat, "pts"), 1), sort=team_stat_per_game(stat, "pts")),
            td(fmt_signed(info["mov"], 1), sort=info["mov"], cls=plus_minus_class(info["mov"])),
        ]
        rows.append("".join(cells))

    if total_gp > 0:
        two = stat_totals["fg"] - stat_totals["tp"]
        two_a = stat_totals["fga"] - stat_totals["tpa"]
        trb_pg = (stat_totals["orb"] + stat_totals["drb"]) / total_gp
        avg_mov = (stat_totals["pts"] - stat_totals["oppPts"]) / total_gp
        rows.append("".join([
            td("Avg", sort=999),
            td("League average", sort="zzzz", cls="name-cell"),
            td(fmt_number(total_gp / max(1, len([i for i in infos if i["stat"]])), 0), sort=total_gp),
            td("—"), td("—"), td("—"),
            td(fmt_number(sum(ages) / len(ages) if ages else None, 1), sort=(sum(ages) / len(ages) if ages else None)),
            td(fmt_number(stat_totals["fg"] / total_gp, 1), sort=stat_totals["fg"] / total_gp),
            td(fmt_number(stat_totals["fga"] / total_gp, 1), sort=stat_totals["fga"] / total_gp),
            td(fmt_pct(made_pct(stat_totals["fg"], stat_totals["fga"])), sort=made_pct(stat_totals["fg"], stat_totals["fga"])),
            td(fmt_number(stat_totals["tp"] / total_gp, 1), sort=stat_totals["tp"] / total_gp),
            td(fmt_number(stat_totals["tpa"] / total_gp, 1), sort=stat_totals["tpa"] / total_gp),
            td(fmt_pct(made_pct(stat_totals["tp"], stat_totals["tpa"])), sort=made_pct(stat_totals["tp"], stat_totals["tpa"])),
            td(fmt_number(two / total_gp, 1), sort=two / total_gp),
            td(fmt_number(two_a / total_gp, 1), sort=two_a / total_gp),
            td(fmt_pct(made_pct(two, two_a)), sort=made_pct(two, two_a)),
            td(fmt_number(stat_totals["ft"] / total_gp, 1), sort=stat_totals["ft"] / total_gp),
            td(fmt_number(stat_totals["fta"] / total_gp, 1), sort=stat_totals["fta"] / total_gp),
            td(fmt_pct(made_pct(stat_totals["ft"], stat_totals["fta"])), sort=made_pct(stat_totals["ft"], stat_totals["fta"])),
            td(fmt_number(stat_totals["orb"] / total_gp, 1), sort=stat_totals["orb"] / total_gp),
            td(fmt_number(stat_totals["drb"] / total_gp, 1), sort=stat_totals["drb"] / total_gp),
            td(fmt_number(trb_pg, 1), sort=trb_pg),
            td(fmt_number(stat_totals["ast"] / total_gp, 1), sort=stat_totals["ast"] / total_gp),
            td(fmt_number(stat_totals["tov"] / total_gp, 1), sort=stat_totals["tov"] / total_gp),
            td(fmt_number(stat_totals["stl"] / total_gp, 1), sort=stat_totals["stl"] / total_gp),
            td(fmt_number(stat_totals["blk"] / total_gp, 1), sort=stat_totals["blk"] / total_gp),
            td(fmt_number(stat_totals["pf"] / total_gp, 1), sort=stat_totals["pf"] / total_gp),
            td(fmt_number(stat_totals["pts"] / total_gp, 1), sort=stat_totals["pts"] / total_gp),
            td(fmt_signed(avg_mov, 1), sort=avg_mov, cls=plus_minus_class(avg_mov)),
        ]))

    return f'''
    <section class="card home-section">
      <div class="section-title-row"><h2>Team Stats</h2><span class="muted">Regular season per-game team totals</span></div>
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


def render_schedule_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    items, label = schedule_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    options = ['<option value="all">All teams</option>']
    for team in sorted(teams, key=team_sort_key):
        options.append(f'<option value="{esc(team.get("tid"))}">{esc(team_full_name(team))}</option>')

    rows: list[str] = []
    for item in items:
        for tid in [item.get("home_tid"), item.get("away_tid")]:
            if tid not in teams_by_tid:
                continue
            opponent_tid = item.get("away_tid") if tid == item.get("home_tid") else item.get("home_tid")
            site = "Home" if tid == item.get("home_tid") else "Away"
            row = "".join([
                td(fmt_number(item.get("day"), 0), sort=item.get("day")),
                td(team_label(tid, teams_by_tid), sort=team_full_for_tid(tid, teams_by_tid), cls="name-cell"),
                td(schedule_matchup_label(item, int(tid), teams_by_tid), sort=team_abbrev_for_tid(opponent_tid, teams_by_tid)),
                td(team_label(opponent_tid, teams_by_tid), sort=team_full_for_tid(opponent_tid, teams_by_tid)),
                td(site, sort=site),
                td(team_schedule_result(item, int(tid)), sort=item_team_points(item, tid) if is_completed_game_item(item) else ""),
                td(f'<a href="{esc(game_url(item))}">Game page</a>', sort=1),
            ])
            rows.append(f'<tr class="click-row" data-schedule-team="{esc(tid)}" data-href="{esc(game_url(item))}">{row}</tr>')

    header_html = "".join(th(label) for label in ["Day", "Team", "Game", "Opponent", "Site", "Result", "Box"])
    body_html = "\n".join(rows)
    table = f"""
    <div class="table-wrap">
      <table id="schedule-table" data-sortable>
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    """ if rows else '<p class="empty-state">No schedule data was found in this export.</p>'

    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">League schedule</p>
        <h1>Schedule</h1>
        <p class="muted">{esc(label)} · {len(items)} games</p>
      </div>
    </section>
    <section class="card">
      <div class="toolbar">
        <div>
          <h2>Team schedule</h2>
          <p class="muted small-copy">Pick a team to see home games as <strong>vs.</strong> and road games as <strong>@</strong>. Every row opens that game page.</p>
        </div>
        <label class="select-label">Team
          <select data-schedule-filter="schedule-table">{''.join(options)}</select>
        </label>
      </div>
      {table}
    </section>
    """
    return page_html("Schedule", body, teams, root="", active="schedule")


def render_scores_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    items, label = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    if items:
        min_day = min(safe_int(item.get("day"), 1) for item in items)
        max_day = max(safe_int(item.get("day"), 1) for item in items)
        days = list(range(min_day, max_day + 1))
    else:
        days = []
    options = "".join(f'<option value="{day}">Day {day}</option>' for day in days)
    panels: list[str] = []
    for i, day in enumerate(days):
        day_items = [item for item in items if safe_int(item.get("day")) == day]
        rows = []
        for item in day_items:
            completed = is_completed_game_item(item)
            winner = game_winner_tid(item)
            status = "Final" if completed else "Scheduled"
            winner_text = team_label(winner, teams_by_tid) if winner is not None else "—"
            row = "".join([
                td(full_matchup_label(item, teams_by_tid), sort=team_full_for_tid(item.get("away_tid"), teams_by_tid), cls="name-cell"),
                td(team_label(item.get("away_tid"), teams_by_tid), sort=team_full_for_tid(item.get("away_tid"), teams_by_tid)),
                td(team_label(item.get("home_tid"), teams_by_tid), sort=team_full_for_tid(item.get("home_tid"), teams_by_tid)),
                td(compact_score_label(item, teams_by_tid), sort=item.get("home_pts") if completed else ""),
                td(status, sort=1 if completed else 0),
                td(winner_text, sort=team_full_for_tid(winner, teams_by_tid) if winner is not None else ""),
                td(f'<a href="{esc(game_url(item))}">Box score</a>' if completed else f'<a href="{esc(game_url(item))}">Preview</a>', sort=1 if completed else 0),
            ])
            rows.append(f'<tr class="click-row" data-href="{esc(game_url(item))}">{row}</tr>')
        if rows:
            header_html = "".join(th(label) for label in ["Game", "Away", "Home", "Score", "Status", "Winner", "Box"])
            table = f"""
            <div class="table-wrap">
              <table id="scores-day-{day}" data-sortable>
                <thead><tr>{header_html}</tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </div>
            """
        else:
            table = '<p class="empty-state">No games on this day.</p>'
        hidden = "" if i == 0 else " hidden"
        panels.append(f'<section class="day-panel" data-day-panel="{day}"{hidden}><div class="section-title-row"><h2>Day {day}</h2><span class="count-pill">{len(day_items)}</span></div>{table}</section>')

    panels_html = "\n".join(panels) if panels else '<p class="empty-state">No game or score data was found in this export.</p>'
    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">League scores</p>
        <h1>Scores</h1>
        <p class="muted">{esc(label)} · {len(items)} games</p>
      </div>
    </section>
    <section class="card">
      <div class="toolbar">
        <div>
          <h2>Daily scoreboard</h2>
          <p class="muted small-copy">Select a day, then click any game row to open its box score or scheduled-game preview.</p>
        </div>
        <label class="select-label">Day
          <select data-day-select>{options}</select>
        </label>
      </div>
      {panels_html}
    </section>
    """
    return page_html("Scores", body, teams, root="", active="scores")


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
        {game_series_note(item, teams_by_tid)}
      </div>
      <div class="game-pager">{next_link}</div>
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
    body = f"""
    {box_score_header(item, teams_by_tid, prev_item, next_item)}
    {box_score_team_table(away_box, teams_by_tid, players_by_pid, root='../')}
    {box_score_team_table(home_box, teams_by_tid, players_by_pid, root='../')}
    """
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    title = f"{away_abbrev} at {home_abbrev} Box Score"
    return page_html(title, body, teams, root="../", active="scores")


def render_home_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    chart_teams = active_teams_for_season(teams, season)
    chart_note = f"{len(chart_teams)} teams in current-season charts"
    if len(chart_teams) != len(teams):
        chart_note += f" · {len(teams)} team pages"
    body = f'''
    <section class="page-hero home-hero">
      <div>
        <p class="eyebrow">League Home</p>
        <h1>{esc((data.get('meta') or {}).get('name') or 'Basketball League')}</h1>
        <p class="muted">Season {season} · {chart_note} · {len(players)} active players</p>
      </div>
    </section>
    {standings_table(data, chart_teams, season)}
    {power_rankings_table(data, chart_teams, players, season)}
    {team_stats_table(chart_teams, season)}
    {awards_voting_table(data, players, teams, season)}
    '''
    return page_html("Home", body, teams, root="", active="home")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def stylesheet() -> str:
    return r"""
:root {
  --bg: #11161b;
  --panel: #1c2229;
  --panel-2: #242b33;
  --panel-3: #303841;
  --line: #3b4652;
  --text: #f2f5f8;
  --muted: #aeb8c2;
  --accent: #ff8a34;
  --accent-2: #8cb6ff;
  --good: #2bd86d;
  --bad: #ff6174;
  --shadow: 0 20px 55px rgba(0,0,0,.22);
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: radial-gradient(circle at top left, rgba(255,138,52,.08), transparent 30rem), var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.site-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: .65rem 1rem;
  align-items: center;
  padding: .85rem clamp(1rem, 3vw, 2rem);
  background: rgba(17, 22, 27, .94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}
.brand a {
  color: var(--text);
  font-weight: 800;
  letter-spacing: .01em;
  text-decoration: none;
}
.primary-nav, .team-nav {
  display: flex;
  gap: .35rem;
  align-items: center;
  overflow-x: auto;
  scrollbar-width: thin;
}
.primary-nav { justify-content: flex-end; }
.team-nav { grid-column: 1 / -1; }
.primary-nav a, .team-nav a {
  white-space: nowrap;
  padding: .42rem .65rem;
  border: 1px solid transparent;
  border-radius: .55rem;
  color: var(--muted);
  font-size: .9rem;
  font-weight: 650;
  text-decoration: none;
}
.primary-nav a:hover, .team-nav a:hover, .primary-nav a.active, .team-nav a.active {
  color: var(--text);
  background: var(--panel-2);
  border-color: var(--line);
}
.page-shell {
  width: min(100%, 1760px);
  margin: 0 auto;
  padding: 1.2rem clamp(.75rem, 2vw, 2rem) 3rem;
}
.page-hero, .card {
  border: 1px solid var(--line);
  border-radius: 1rem;
  background: linear-gradient(180deg, rgba(255,255,255,.035), transparent), var(--panel);
  box-shadow: var(--shadow);
}
.page-hero {
  position: relative;
  overflow: hidden;
  margin-bottom: 1rem;
  padding: clamp(1rem, 3vw, 1.6rem);
}
.page-hero::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: .45rem;
  background: linear-gradient(180deg, var(--team-primary, var(--accent)), var(--team-secondary, var(--accent-2)));
}
.eyebrow {
  margin: 0 0 .25rem;
  color: var(--accent-2);
  font-size: .78rem;
  font-weight: 800;
  letter-spacing: .1em;
  text-transform: uppercase;
}
h1, h2 { margin: 0; line-height: 1.1; }
h1 { font-size: clamp(1.75rem, 3vw, 2.85rem); }
h2 { font-size: clamp(1.05rem, 1.6vw, 1.45rem); }
.muted { color: var(--muted); }
.number { display: inline-block; min-width: 1.4rem; text-align: right; margin-right: .2rem; }
.card { margin-bottom: 1rem; padding: .9rem; }
.compact-card { padding: .65rem; }
.section-title-row, .toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-bottom: .65rem;
}
.count-pill, .mini-skill, .mood-chip, .award-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-3);
  color: var(--text);
  font-weight: 750;
}
.count-pill { padding: .15rem .55rem; color: var(--muted); }
.mini-skill { padding: .05rem .28rem; margin-left: .18rem; font-size: .72rem; color: #dce5ee; }
.mood-chip { padding: .05rem .36rem; margin-right: .15rem; color: var(--good); }
.award-chip { padding: .22rem .55rem; margin: .15rem .2rem .15rem 0; background: #c3cbd4; color: #1d252d; border-color: transparent; }
.table-wrap { overflow-x: auto; border-radius: .75rem; border: 1px solid var(--line); }
table { width: 100%; border-collapse: collapse; min-width: 980px; background: #181e24; }
th, td { padding: .55rem .62rem; border-bottom: 1px solid rgba(255,255,255,.045); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; position: sticky; left: 0; z-index: 2; }
td:first-child { background: inherit; }
th:first-child { z-index: 4; }
thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: #20272e;
  color: #f6f7f9;
  font-size: .82rem;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--line);
}
thead th::after { content: "↕"; color: rgba(255,255,255,.35); margin-left: .35rem; font-size: .78rem; }
thead th.sort-asc::after { content: "↑"; color: var(--accent-2); }
thead th.sort-desc::after { content: "↓"; color: var(--accent-2); }
tbody tr:nth-child(odd) { background: #252b31; }
tbody tr:nth-child(even) { background: #1c2228; }
tbody tr:hover { background: #303842; }
.name-cell { min-width: 16rem; }
.player-link { color: var(--accent); font-weight: 800; }
.delta-up { color: var(--good); font-weight: 800; }
.delta-down { color: var(--bad); font-weight: 800; }
.healthy { color: var(--good); }
.injured { color: var(--bad); }
.table-search {
  width: min(100%, 24rem);
  padding: .72rem .85rem;
  border-radius: .65rem;
  border: 1px solid var(--line);
  background: #121820;
  color: var(--text);
  outline: none;
}
.table-search:focus { border-color: var(--accent-2); box-shadow: 0 0 0 3px rgba(140,182,255,.16); }
.empty-state { margin: .75rem 0 0; color: var(--muted); }
.home-blank { min-height: 60vh; }
.player-hero {
  display: grid;
  grid-template-columns: 150px minmax(280px, 1fr) minmax(380px, 640px);
  gap: 1.25rem;
  align-items: start;
}
.portrait-wrap { display: flex; justify-content: center; align-items: flex-start; }
.portrait {
  width: 150px;
  height: 150px;
  border-radius: 1rem;
  object-fit: cover;
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.portrait.placeholder {
  display: grid;
  place-items: center;
  font-size: 2.5rem;
  font-weight: 900;
  color: var(--muted);
}
.details-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .45rem .8rem;
  margin-top: 1rem;
}
.detail-item {
  display: flex;
  justify-content: space-between;
  gap: .75rem;
  padding: .45rem .55rem;
  background: rgba(255,255,255,.035);
  border: 1px solid rgba(255,255,255,.045);
  border-radius: .55rem;
}
.detail-item span { color: var(--muted); }
.detail-item strong { text-align: right; }
.rating-panel {
  display: grid;
  gap: .75rem;
}
.big-rating {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: .8rem .9rem;
  border: 1px solid var(--line);
  border-radius: .85rem;
  background: #111820;
}
.big-rating span { color: var(--muted); font-weight: 800; text-transform: uppercase; letter-spacing: .08em; font-size: .78rem; }
.big-rating strong { font-size: 2rem; }
.micro-ratings { display: grid; grid-template-columns: repeat(2, 1fr); gap: .45rem; }
.micro-ratings div { display: flex; justify-content: space-between; padding: .45rem .55rem; background: rgba(255,255,255,.035); border-radius: .5rem; }
.micro-ratings span { color: var(--muted); }
.awards-strip { display: flex; flex-wrap: wrap; }
.summary-wrap table { min-width: 760px; }
@media (max-width: 900px) {
  .site-header { grid-template-columns: 1fr; }
  .primary-nav { justify-content: flex-start; }
  .player-hero { grid-template-columns: 1fr; }
  .portrait-wrap { justify-content: flex-start; }
  .details-grid, .micro-ratings { grid-template-columns: 1fr; }
  th, td { padding: .48rem .52rem; }
}

.team-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 1rem;
}
.salary-summary {
  width: min(100%, 24rem);
  padding: .75rem .9rem;
  border: 1px solid var(--line);
  border-radius: .85rem;
  background: rgba(12, 18, 25, .72);
}
.salary-copy { display: flex; justify-content: space-between; gap: .75rem; margin-bottom: .45rem; }
.salary-copy span { color: var(--muted); font-weight: 750; }
.salary-copy strong { color: var(--text); }
.salary-bar { height: .62rem; border-radius: 999px; overflow: hidden; background: #10161d; border: 1px solid rgba(255,255,255,.08); }
.salary-bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent-2), var(--accent)); }
.salary-summary.over .salary-copy strong { color: var(--bad); }
.rating-topline { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
.full-rating-panel { min-width: min(100%, 520px); }
.rating-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .8rem; }
.rating-group {
  padding: .75rem;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: .8rem;
  background: rgba(255,255,255,.03);
}
.rating-group h3 {
  margin: 0 0 .35rem;
  padding-bottom: .35rem;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-size: .95rem;
}
.rating-row { display: flex; justify-content: space-between; gap: .8rem; padding: .18rem 0; }
.rating-row span { color: var(--muted); }
.rating-row strong { text-align: right; }
.home-hero { margin-bottom: 1rem; }
.home-section { margin-bottom: 1.15rem; }
.row-rank { display: inline-block; min-width: 1.7rem; color: var(--muted); }
.clinch { color: #d9e0e8; font-weight: 900; margin-left: .25rem; }
.award-name strong { display: block; font-size: 1.05rem; color: var(--text); }
.award-name span { display: block; color: var(--muted); font-size: .82rem; }
.candidate-cell { min-width: 14rem; text-align: left; }
.candidate-card { display: flex; align-items: center; gap: .6rem; min-width: 13rem; text-align: left; }
.candidate-card > div:last-child { display: grid; gap: .1rem; }
.candidate-card span { color: var(--muted); font-size: .78rem; }
.candidate-img {
  flex: 0 0 auto;
  width: 42px;
  height: 42px;
  border-radius: .65rem;
  object-fit: cover;
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.candidate-img.placeholder {
  display: grid;
  place-items: center;
  color: var(--muted);
  font-weight: 900;
  font-size: .8rem;
}
@media (max-width: 1100px) {
  .team-hero { display: block; }
  .salary-summary { margin-top: 1rem; }
  .rating-groups { grid-template-columns: 1fr; }
  .rating-topline { grid-template-columns: 1fr; }
}
.team-dropdown { position: relative; flex: 0 0 auto; }
.team-dropdown summary {
  list-style: none;
  cursor: pointer;
  white-space: nowrap;
  padding: .42rem .65rem;
  border: 1px solid transparent;
  border-radius: .55rem;
  color: var(--muted);
  font-size: .9rem;
  font-weight: 650;
}
.team-dropdown summary::-webkit-details-marker { display: none; }
.team-dropdown summary::after { content: "▾"; margin-left: .35rem; color: rgba(255,255,255,.48); }
.team-dropdown[open] summary, .team-dropdown.active summary, .team-dropdown summary:hover {
  color: var(--text);
  background: var(--panel-2);
  border-color: var(--line);
}
.team-menu {
  position: absolute;
  top: calc(100% + .45rem);
  right: 0;
  z-index: 40;
  display: grid;
  grid-template-columns: minmax(13rem, 1fr);
  gap: .22rem;
  width: max-content;
  min-width: 16rem;
  max-height: min(70vh, 30rem);
  overflow-y: auto;
  padding: .45rem;
  border: 1px solid var(--line);
  border-radius: .75rem;
  background: rgba(17, 22, 27, .98);
  box-shadow: var(--shadow);
}
.team-menu a {
  display: block;
  white-space: nowrap;
  padding: .48rem .6rem;
  border: 1px solid transparent;
  border-radius: .5rem;
  color: var(--muted);
  font-size: .88rem;
  font-weight: 700;
  text-decoration: none;
}
.team-menu a:hover, .team-menu a.active { color: var(--text); background: var(--panel-2); border-color: var(--line); }
.small-copy { margin: .25rem 0 0; font-size: .9rem; }
.select-label { display: grid; gap: .25rem; color: var(--muted); font-size: .8rem; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
.select-label select {
  min-width: 12rem;
  padding: .65rem .75rem;
  border-radius: .65rem;
  border: 1px solid var(--line);
  background: #121820;
  color: var(--text);
  font: inherit;
  text-transform: none;
  letter-spacing: 0;
}
.click-row { cursor: pointer; }
.click-row td:last-child { color: var(--accent); font-weight: 800; }
.day-panel[hidden] { display: none; }
.button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: .55rem .75rem;
  border: 1px solid var(--line);
  border-radius: .55rem;
  background: var(--panel-2);
  color: var(--text);
  text-decoration: none;
  font-weight: 800;
}
.button-link:hover { text-decoration: none; border-color: var(--accent-2); }
.button-link.disabled { opacity: .45; pointer-events: none; }
.box-score-hero {
  display: grid;
  grid-template-columns: auto minmax(0, 52rem) auto;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-bottom: 1rem;
}
.scoreboard-core { text-align: center; }
.scoreboard-core h1 {
  font-size: clamp(1.1rem, 2vw, 1.45rem);
  display: flex;
  justify-content: center;
  align-items: baseline;
  gap: .45rem;
  flex-wrap: wrap;
}
.scoreboard-core h1 span { color: var(--text); font-weight: 950; }
.scoreboard-core h1 em { color: var(--muted); font-style: normal; font-size: .9rem; }
.scoreboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .75rem;
  margin-top: .65rem;
}
.mini-score-table.table-wrap { border-radius: .55rem; }
.mini-score-table table { min-width: 0; width: 100%; }
.mini-score-table th, .mini-score-table td { padding: .34rem .45rem; font-size: .82rem; }
.mini-score-table thead th { cursor: default; }
.mini-score-table thead th::after { content: ""; margin: 0; }
.score-team { color: var(--accent); font-weight: 900; }
.final-score { font-weight: 950; }
.series-note { margin: .45rem 0 0; color: var(--accent); font-weight: 900; }
.scheduled-note { color: var(--muted); margin: .65rem 0 0; font-weight: 750; }
.box-team-section { margin-bottom: 1.1rem; }
.box-team-section h2 { margin: 0 0 .45rem; }
.box-score-table { min-width: 1180px; }
.bench-start td { border-top: 2px solid rgba(255,255,255,.35); }
.total-row td, .pct-row td { font-weight: 900; background: #20272e; }
.total-label { color: var(--text); }
.pct-row td { border-bottom: 0; }
@media (max-width: 900px) {
  .team-dropdown { width: 100%; }
  .team-menu { position: static; width: 100%; max-height: 16rem; margin-top: .35rem; }
  .box-score-hero { grid-template-columns: 1fr; text-align: left; }
  .scoreboard-core { text-align: left; }
  .scoreboard-core h1 { justify-content: flex-start; }
  .scoreboard-grid { grid-template-columns: 1fr; }
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

})();
""".strip() + "\n"


def generate_site(
    json_path: Path,
    out_dir: Path,
    start_season: int = 2026,
    clean: bool = False,
    schedule_season: int | None = None,
    schedule_days: int | None = None,
) -> dict[str, int | str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    season = current_season(data)
    teams = sorted(data.get("teams", []), key=team_sort_key)
    players = active_players(data)
    fa_players = free_agents(data)
    cap = get_salary_cap(data)
    game_items, score_label = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    schedule_items, schedule_label = schedule_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)

    if clean and out_dir.exists():
        if out_dir.resolve() in {Path("/").resolve(), Path.cwd().resolve()}:
            raise RuntimeError(f"Refusing to clean unsafe output directory: {out_dir}")
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(out_dir / "assets" / "styles.css", stylesheet())
    write_text(out_dir / "assets" / "site.js", javascript())

    write_text(out_dir / "index.html", render_home_page(data, teams, players, season, start_season))
    write_text(out_dir / "scores.html", render_scores_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days))
    write_text(out_dir / "schedule.html", render_schedule_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days))
    write_text(out_dir / "free-agency.html", render_free_agency_page(fa_players, teams, season, start_season))
    write_text(out_dir / "players" / "index.html", render_players_index(players, teams, season, start_season))

    for team in teams:
        roster = [player for player in players if player.get("tid") == team.get("tid")]
        write_text(out_dir / "teams" / f"{team_slug(team)}.html", render_team_page(team, roster, teams, season, start_season, cap))

    for player in players:
        write_text(out_dir / "players" / f"{player_slug(player)}.html", render_player_page(player, teams, season, start_season))

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
    parser.add_argument("json_file", type=Path, help="Path to the Basketball GM-style JSON file")
    parser.add_argument("--out", type=Path, default=Path("site"), help="Output directory for the generated website")
    parser.add_argument("--start-season", type=int, default=2026, help="First season to show on player stat pages")
    parser.add_argument("--schedule-season", type=int, default=None, help="Season to use for Schedule/Scores pages. Defaults to an exported schedule, or the upcoming season during offseason exports.")
    parser.add_argument("--schedule-days", type=int, default=None, help="Optional target number of calendar days for a generated schedule, such as 46.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before generating")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = generate_site(
        args.json_file,
        args.out,
        start_season=args.start_season,
        clean=args.clean,
        schedule_season=args.schedule_season,
        schedule_days=args.schedule_days,
    )
    print(f"Generated site in {args.out.resolve()}")
    print(f"Season: {summary['season']}")
    print(f"Schedule/Scores: {summary['schedule_label']} / {summary['score_label']}")
    print(f"Teams: {summary['teams']}; team pages: {summary['team_pages']}")
    print(f"Players: {summary['players']}; player pages: {summary['player_pages']}; free agents: {summary['free_agents']}")
    print(f"Schedule games: {summary['schedule_games']}; score rows: {summary['score_games']}; completed scores: {summary['completed_scores']}; game pages: {summary['game_pages']}")


if __name__ == "__main__":
    main()
