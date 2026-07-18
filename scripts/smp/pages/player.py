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
    FREE_AGENT_TID,
    RATING_GROUPS,
    RATING_LABELS,
    RETIRED_TID,
    age,
    combine_stat_rows,
    efg_pct,
    esc,
    fmt_contract,
    fmt_height,
    fmt_minutes,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_ratio,
    fmt_signed,
    game_score_value,
    game_slug_from_gid,
    initials,
    injury_html,
    latest_rating,
    made_attempted,
    made_pct,
    mood_html,
    page_html,
    per_game,
    player_name,
    player_slug,
    player_url,
    playoff_stats_since,
    plus_minus_class,
    rating_delta_html,
    ratio,
    regular_stats_since,
    safe_float,
    safe_int,
    stat_gp,
    table_html,
    td,
    team_abbrev_for_tid,
    team_label,
    th,
    total_2p,
    total_2pa,
    ts_pct,
    turnover_pct,
)

from ..simmodel import _player_projection

from ..charts import development_chart_html, subrating_grid_html


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
