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

from ..core import (
    ALL_PLAYERS_BY_PID,
    EVENT_BADGES,
    FREE_AGENT_TID,
    RATING_GROUP_STARTS,
    SCATTER_METRICS,
    TEAM_PALETTE,
    TEAM_RATING_RANK_KEYS,
    active_teams_for_season,
    age,
    build_game_logs,
    combine_stat_rows,
    completed_game_items,
    compose_event_html,
    draft_prospects,
    efg_pct,
    esc,
    event_player_link,
    fmt_contract,
    fmt_height,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_record,
    game_ot_label,
    game_score_value,
    game_slug_from_gid,
    game_url,
    game_winner_tid,
    heat_style,
    inferred_upcoming_schedule_season,
    is_completed_game_item,
    latest_rating,
    latest_regular_stat,
    latest_team_season,
    made_pct,
    page_html,
    per36,
    per36_trb,
    per_game,
    player_link,
    player_name,
    player_url,
    rating_delta_html,
    safe_float,
    safe_int,
    schedule_matchup_label,
    score_items_for_page,
    season_regular_stat,
    seed_cell_style,
    standings_order,
    stat_gp,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_anchor,
    team_dot,
    team_full_name,
    team_label,
    team_palette_by_tid,
    team_schedule_result,
    team_url,
    th,
    total_rebounds,
    ts_pct,
)

from ..simmodel import fa_salary_by_length, league_sim


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
    sorted_players = sorted(rostered, key=lambda p: (p.get("tid", 999), -safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
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
