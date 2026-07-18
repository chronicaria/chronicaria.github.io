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
    RATING_GROUP_STARTS,
    TEAM_RATING_RANK_KEYS,
    active_teams_for_season,
    age,
    canonical_pos,
    completed_game_items,
    esc,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_record,
    fmt_signed,
    game_ot_label,
    game_recap_text,
    game_sort_key,
    game_url,
    game_winner_tid,
    heat_style,
    is_completed_game_item,
    item_team_points,
    latest_rating,
    latest_regular_stat,
    latest_team_season,
    made_pct,
    page_html,
    per_game,
    player_link,
    player_name,
    player_url,
    rating_delta_html,
    roster_row,
    safe_float,
    safe_int,
    standings_order,
    stat_gp,
    streak_text,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_full_name,
    team_label,
    team_palette_by_tid,
    team_schedule_result,
    team_slug,
)

from ..finance import (
    FIN_BASE,
    FIN_CHAMP,
    FIN_FINALS,
    FIN_PER_WIN,
    FIN_PLAYOFF,
    FIN_SOFT_CAP,
    FIN_START,
    fmt_money_pm,
    team_finances_table,
)


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
        return canonical_pos(player, latest_rating(player, season))

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
    return sorted(roster, key=lambda p: (-latest_rating(p, season).get("ovr", 0), player_name(p)))


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
