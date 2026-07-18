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
    AWARD_ROWS,
    EVENT_BADGES,
    FREE_AGENT_TID,
    SITE_META,
    active_teams_for_season,
    clinch_html,
    completed_game_items,
    compose_event_html,
    esc,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_record,
    fmt_signed,
    fmt_win_pct,
    free_agents,
    game_ot_label,
    game_recap_text,
    game_url,
    game_winner_tid,
    heat_style,
    inferred_upcoming_schedule_season,
    initials,
    is_completed_game_item,
    item_team_points,
    last_ten_dots,
    last_ten_text,
    latest_rating,
    latest_team_season,
    latest_team_stat,
    made_pct,
    page_html,
    phase_value,
    per_game,
    player_link,
    player_name,
    player_url,
    plus_minus_class,
    previous_rating,
    previous_regular_stat,
    regular_season_length,
    safe_float,
    safe_int,
    score_items_for_page,
    season_regular_stat,
    seed_cell_style,
    stat_gp,
    streak_text,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_anchor,
    team_dot,
    team_full_name,
    team_label,
    team_mov,
    team_palette_by_tid,
    team_slug,
    team_sort_key,
    team_stat_per_game,
    team_url,
    total_rebounds,
    win_pct,
)

from ..derived import fantasy_pts, four_factors

from ..finance import compute_league_finances

from ..identity import team_chart_color

from ..ledger import load_odds_history

from ..simmodel import league_sim, playoff_clinch_marks

from .league import playoff_bracket_html


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
    detail = ("Team strength is rated from each current roster (injury-aware), "
              "blending in this season's results as games accumulate. "
              "Playoffs are simulated as 1v4 / 2v3 best-of-sevens.")
    if sim.get("fresh"):
        title = f"{season} Playoff Odds"
        note = "10,000 sims · roster-based strength · projected schedule"
    else:
        title = "Playoff Odds"
        note = "10,000 sims · roster-based strength, injury-aware"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>{title}</h2><span class="muted small-copy" title="{esc(detail)}">{esc(note)}</span></div>
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
        # Projected (simulated) games have no game page — link each team to its
        # team page instead of emitting a dead "#" link.
        item = items_by_gid.get(str(stake["gid"]))
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
            team = teams_by_tid.get(safe_int(tid))
            label = f'{team_dot(tid, palette)}{esc(team_abbrev_for_tid(tid, teams_by_tid))}'
            if item is None and team:
                label = f'<a class="hm-stake-team" href="{esc(team_url(team))}">{label}</a>'
            rows.append(
                f'<span class="score-row"><span>{label}</span>'
                f'<strong>{swing_html}</strong></span>'
            )
        if item is not None:
            cards.append(f'<a class="score-line score-stack" href="{esc(game_url(item))}">{"".join(rows)}</a>')
        else:
            cards.append(f'<div class="score-line score-stack hm-stake-static">{"".join(rows)}</div>')
    if sim.get("fresh"):
        title = "What's at Stake · Opening Day"
        note = "playoff-odds swing on the projected opener"
    else:
        title = f'What\'s at Stake · Day {sim.get("day")}'
        note = "playoff-odds swing on today's game"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>{title}</h2><span class="muted small-copy">{note}</span></div>
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
          <div class="section-title-row"><h2>{esc(title)}</h2><span class="muted small-copy" title="SOS = average current win% of remaining opponents">Top 4 make the playoffs</span></div>
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
      <div class="section-title-row"><h2>Team Stats</h2><span class="muted small-copy" title="Cells tinted green (good) to red (bad) within each column">Per game</span></div>
      {table_html(headers, rows, table_id="team-stats", empty_message="No team stats available.")}
    </section>
    '''


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
      <div class="section-title-row"><h2>Award Voting Sentiment</h2><span class="muted small-copy" title="Ranked by current-season production and award signals">top five candidates</span></div>
      {table_html(headers, rows, table_id="award-sentiment", empty_message="No award candidates available.")}
    </section>
    '''


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
      <div class="section-title-row"><h2>Team Finances</h2><span class="muted small-copy" title="Available to spend = cash on hand − {year} payroll">bankroll entering {year}</span></div>

      {table_html(headers, rows, table_id="home-finances")}
    </section>
    """


# ---------------------------------------------------------------------------
# Phase-aware composition (PLAN D32) + new home cards (B11/B14/B16a)
# ---------------------------------------------------------------------------

def home_phase_kind(data: dict[str, Any], season: int) -> str:
    """Which home-page composition to show: preseason/regular/playoffs/offseason.

    Basketball GM phases: 0 preseason, 1 regular season, 2 after trade deadline,
    3 playoffs, >=4 offseason (draft lottery through free agency). A "regular
    season" export with zero completed games is still preseason in spirit —
    every standings/stat card would be a wall of dashes — so it composes as
    preseason until real games land.
    """
    phase = phase_value(data)
    if phase >= 4:
        return "offseason"
    if phase == 3:
        return "playoffs"
    if phase <= 0 or not completed_game_items(data, season, playoffs=False):
        return "preseason"
    return "regular"


def last_completed_season(data: dict[str, Any], season: int) -> int:
    """Newest season with completed regular-season games in the export."""
    for candidate in range(season, season - 4, -1):
        if completed_game_items(data, candidate, playoffs=False):
            return candidate
    return season - 1


def _season_label(chart_season: int, page_season: int) -> str:
    """Card sub-label when a chart falls back to the last completed season."""
    if chart_season == page_season:
        return ""
    return f"{chart_season} · last completed season"


def preseason_banner(data: dict[str, Any], season: int) -> str:
    """One-card season lead-in for the games-not-yet-played state. Its single
    explanation line replaces the zero-data standings / team-stats /
    award-sentiment cards (no dash walls). A regular-season export with zero
    completed games is labeled Opening Day rather than Preseason."""
    season_len = regular_season_length(data, season) or 45
    pill = "Opening Day" if phase_value(data) >= 1 else "Preseason"
    return f"""
    <section class="card home-section hm-banner">
      <div class="hm-banner-row">
        <span class="hm-phase-pill">{esc(pill)}</span>
        <h2 class="hm-banner-title">The {esc(season)} season hasn't tipped off yet</h2>
        <span class="muted small-copy">{esc(season_len)} games ahead</span>
      </div>
      <p class="hm-banner-note muted small-copy">Standings and stats go live with the first results — everything below is projected from current rosters.</p>
    </section>
    """


def playoff_bracket_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    """Current playoff bracket as the playoffs-phase lead card."""
    ps = next((p for p in data.get("playoffSeries", []) or [] if isinstance(p, dict) and safe_int(p.get("season")) == season), None)
    if not ps:
        return ""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    inner = playoff_bracket_html(ps, teams_by_tid, "")
    if not inner:
        return ""
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>{esc(season)} Playoffs</h2><a class="muted small-copy" href="schedule.html">Full schedule →</a></div>
      {inner}
    </section>
    """


# Offseason-transaction event types, in digest display order. "draft" has no
# entry in EVENT_BADGES (the in-season feed never sees one), so it is added here.
_DIGEST_BADGES = dict(EVENT_BADGES)
_DIGEST_BADGES["draft"] = ("DRAFT", "badge-accent")

_DIGEST_COUNT_LABELS = [
    ("trade", "trade", "trades"),
    ("sign", "signing", "signings"),
    ("draft", "draft pick", "draft picks"),
    ("release", "player waived", "players waived"),
]


def offseason_events(data: dict[str, Any], completed_season: int) -> list[dict[str, Any]]:
    """Transaction events from the offseason after ``completed_season``.

    BBGM logs offseason moves (draft, signings, trades) under the season that
    just ended, after its playoff events. The boundary is the last
    playoffs-type eid of that season; draft events only ever happen in the
    offseason, and events carrying an explicit phase >= 4 count regardless of
    eid. In-season trades and signings stay out of the digest, and
    retirement / Hall of Fame news is excluded by design.
    """
    wanted = {"trade", "freeAgent", "reSigned", "release", "draft"}
    events = [e for e in data.get("events", []) or []
              if isinstance(e, dict) and safe_int(e.get("season"), -1) == completed_season and e.get("type") in wanted]
    po_eids = [safe_int(e.get("eid")) for e in data.get("events", []) or []
               if isinstance(e, dict) and safe_int(e.get("season"), -1) == completed_season
               and e.get("type") in ("playoffs", "award")]
    boundary = max(po_eids) if po_eids else -1
    out = []
    for event in events:
        etype = event.get("type")
        if etype == "draft":
            out.append(event)
        elif safe_int(event.get("eid"), -1) > boundary or safe_int(event.get("phase"), -1) >= 4:
            out.append(event)
    out.sort(key=lambda e: safe_int(e.get("eid")))
    return out


def offseason_digest_card(data: dict[str, Any], teams: list[dict[str, Any]], completed_season: int, root: str = "") -> str:
    """Digest of the offseason's moves: count summary + the notable transactions."""
    events = offseason_events(data, completed_season)
    if not events:
        return ""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        key = "sign" if event.get("type") in ("freeAgent", "reSigned") else event.get("type")
        by_type[key].append(event)

    counts = []
    for key, singular, plural in _DIGEST_COUNT_LABELS:
        n = len(by_type.get(key, []))
        if n:
            counts.append(f"{n} {singular if n == 1 else plural}")
    summary = " · ".join(counts)

    def event_sort_amount(event: dict[str, Any]) -> float:
        return safe_float((event.get("contract") or {}).get("amount"))

    # Notable slice, chronological by story arc: draft -> trades -> signings.
    notable: list[dict[str, Any]] = []
    notable += sorted(by_type.get("draft", []), key=lambda e: safe_int(e.get("eid")))[:3]
    notable += sorted(by_type.get("trade", []), key=lambda e: safe_int(e.get("eid")))[:3]
    notable += sorted(by_type.get("sign", []), key=event_sort_amount, reverse=True)[:4]

    items = []
    for event in notable:
        html_text = compose_event_html(event, all_players_by_pid, teams_by_tid, completed_season, set(), root)
        if not html_text:
            continue
        label, badge_cls = _DIGEST_BADGES.get(event.get("type"), ("NEWS", "badge-muted"))
        items.append(f'<li><span class="badge {badge_cls}">{esc(label)}</span><span>{html_text}</span></li>')
    if not items:
        return ""
    return f"""
    <section class="card home-section news-card hm-digest">
      <div class="section-title-row"><h2>Offseason Digest</h2><span class="count-pill">{len(events)} {'move' if len(events) == 1 else 'moves'}</span></div>
      <p class="muted small-copy hm-digest-summary">{esc(summary)}</p>
      <ul class="news-list">{''.join(items)}</ul>
    </section>
    """


def preseason_rookie_watch_card(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    """Rookie watch before any games exist: the incoming class by current rating."""
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    rookies = []
    for player in players:
        if safe_int(player.get("tid"), -9) < 0:
            continue
        draft = player.get("draft") or {}
        if draft.get("year") != season - 1:
            continue
        rating = latest_rating(player, season)
        rookies.append((safe_int(rating.get("ovr")), safe_int(rating.get("pot")), player, rating, draft))
    if not rookies:
        return ""
    rookies.sort(key=lambda x: (-x[0], -x[1], player_name(x[2])))
    rows = []
    for rank, (ovr, pot, player, rating, draft) in enumerate(rookies[:6], 1):
        pick = safe_int(draft.get("pick"))
        pick_html = f'<span class="hm-pick muted">#{pick} pick</span>' if pick > 0 else ""
        rows.append(
            f'<li><span class="leader-rank">{rank}</span>'
            f'{team_dot(player.get("tid"), palette)}'
            f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
            f'<span class="leader-team">{esc(team_abbrev_for_tid(player.get("tid"), teams_by_tid))}</span>'
            f'{pick_html}'
            f'<span class="leader-value">{esc(rating.get("pos", ""))} · {ovr} <span class="muted">/ {pot}</span></span></li>'
        )
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Rookie Watch</h2><span class="muted small-copy">the incoming class · Ovr / Pot</span></div>
      <ol class="leader-list rookie-list">{''.join(rows)}</ol>
    </section>
    """


def season_awards_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    """The completed season's award winners (offseason lead card)."""
    from ..identity import crest_svg

    row = next((a for a in data.get("awards", []) or [] if isinstance(a, dict) and safe_int(a.get("season")) == season), None)
    if not row:
        return ""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    entries = [
        ("finalsMvp", "finals_mvp", "Finals MVP"),
        ("mvp", "mvp", "MVP"),
        ("dpoy", "dpoy", "DPOY"),
        ("smoy", "smoy", "Sixth Man"),
        ("roy", "roy", "Rookie of the Year"),
        ("mip", "mip", "Most Improved"),
    ]
    cells = []
    for key, crest_kind, label in entries:
        winner = row.get(key) or {}
        if not isinstance(winner, dict) or winner.get("pid") is None:
            continue
        player = all_players_by_pid.get(safe_int(winner.get("pid")))
        if player is not None and player.get("retiredYear") is None and safe_int(player.get("tid"), -9) >= FREE_AGENT_TID:
            name_html = f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
        else:
            name_html = esc(winner.get("name") or player_name(player or {}) or "—")
        team_ab = team_abbrev_for_tid(winner.get("tid"), teams_by_tid)
        cells.append(
            f'<div class="hm-award"><span class="hm-award-crest crest--gold">{crest_svg(crest_kind)}</span>'
            f'<div class="hm-award-body"><span class="hm-award-label">{esc(label)}</span>'
            f'{name_html}<span class="leader-team">{esc(team_ab)}</span></div></div>'
        )
    if not cells:
        return ""
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>{esc(season)} Awards</h2><a class="muted small-copy" href="history.html">Full history →</a></div>
      <div class="hm-award-grid">{''.join(cells)}</div>
    </section>
    """


def fa_watch_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    """Top available free agents (offseason lead card)."""
    fas = free_agents(data)
    if not fas:
        return ""
    scored = []
    for player in fas:
        rating = latest_rating(player, season)
        scored.append((safe_int(rating.get("ovr")), safe_int(rating.get("pot")), player, rating))
    scored.sort(key=lambda x: (-x[0], -x[1], player_name(x[2])))
    rows = []
    for rank, (ovr, pot, player, rating) in enumerate(scored[:8], 1):
        rows.append(
            f'<li><span class="leader-rank">{rank}</span>'
            f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
            f'<span class="leader-team">{esc(rating.get("pos", ""))}</span>'
            f'<span class="leader-value">{ovr} <span class="muted">/ {pot}</span></span></li>'
        )
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Free Agent Market</h2><a class="muted small-copy" href="{root}free-agency.html">Full market →</a></div>
      <ol class="leader-list">{''.join(rows)}</ol>
    </section>
    """


def _exact_team_stat(team: dict[str, Any], season: int) -> dict[str, Any]:
    """Regular-season team stat row for exactly ``season`` (no fallback)."""
    for row in team.get("stats", []) or []:
        if isinstance(row, dict) and not row.get("playoffs") and safe_int(row.get("season")) == season:
            return row
    return {}


def _team_rating_proxies(stat: dict[str, Any]) -> tuple[float, float] | None:
    """(offensive, defensive) points per 100 possessions, Dean Oliver possessions."""
    if safe_float(stat.get("gp")) <= 0:
        return None
    poss = safe_float(stat.get("fga")) - safe_float(stat.get("orb")) + safe_float(stat.get("tov")) + 0.44 * safe_float(stat.get("fta"))
    opp_poss = safe_float(stat.get("oppFga")) - safe_float(stat.get("oppOrb")) + safe_float(stat.get("oppTov")) + 0.44 * safe_float(stat.get("oppFta"))
    if poss <= 0 or opp_poss <= 0:
        return None
    return (100.0 * safe_float(stat.get("pts")) / poss, 100.0 * safe_float(stat.get("oppPts")) / opp_poss)


def four_factors_scatter_card(data: dict[str, Any], teams: list[dict[str, Any]], chart_season: int, page_season: int) -> str:
    """Quadrant scatter of team offense vs defense (B16a).

    x = offensive rating proxy (points per 100 possessions), y = defensive
    rating proxy with better defense UP. Dots are --team-chart colored with
    abbrev labels; dashed league-average crosshair splits the four quadrants.
    Tooltips carry the Dean Oliver four factors from smp.derived.
    """
    points = []
    for team in active_teams_for_season(teams, chart_season):
        stat = _exact_team_stat(team, chart_season)
        proxies = _team_rating_proxies(stat)
        if proxies is None:
            continue
        points.append((team, stat, proxies[0], proxies[1]))
    if len(points) < 2:
        return ""

    xs_vals = [p[2] for p in points]
    ys_vals = [p[3] for p in points]
    avg_x = sum(xs_vals) / len(xs_vals)
    avg_y = sum(ys_vals) / len(ys_vals)
    pad = 1.2
    lo_x, hi_x = min(xs_vals) - pad, max(xs_vals) + pad
    lo_y, hi_y = min(ys_vals) - pad, max(ys_vals) + pad

    width, height = 640.0, 420.0
    ml, mr, mt, mb = 46.0, 18.0, 26.0, 44.0
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def sx(v: float) -> float:
        return ml + (v - lo_x) / max(1e-9, hi_x - lo_x) * plot_w

    def sy(v: float) -> float:
        # Lower defensive rating (fewer points allowed) is better -> up.
        return mt + (v - lo_y) / max(1e-9, hi_y - lo_y) * plot_h

    parts: list[str] = []
    step = 2 if (hi_x - lo_x) <= 14 else 4
    tick = math.ceil(lo_x / step) * step
    while tick <= hi_x:
        gx = sx(tick)
        parts.append(f'<line x1="{gx:.1f}" y1="{mt}" x2="{gx:.1f}" y2="{mt + plot_h:.1f}" class="chart-grid"/>')
        parts.append(f'<text x="{gx:.1f}" y="{mt + plot_h + 14:.1f}" class="chart-tick" text-anchor="middle">{int(tick)}</text>')
        tick += step
    step_y = 2 if (hi_y - lo_y) <= 14 else 4
    tick = math.ceil(lo_y / step_y) * step_y
    while tick <= hi_y:
        gy = sy(tick)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w:.1f}" y2="{gy:.1f}" class="chart-grid"/>')
        parts.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{int(tick)}</text>')
        tick += step_y

    # League-average crosshair + quadrant captions.
    parts.append(f'<line x1="{sx(avg_x):.1f}" y1="{mt}" x2="{sx(avg_x):.1f}" y2="{mt + plot_h:.1f}" class="ff4-avg"/>')
    parts.append(f'<line x1="{ml}" y1="{sy(avg_y):.1f}" x2="{ml + plot_w:.1f}" y2="{sy(avg_y):.1f}" class="ff4-avg"/>')
    captions = [
        (ml + 8, mt + 12, "start", "− offense · + defense"),
        (ml + plot_w - 8, mt + 12, "end", "+ offense · + defense"),
        (ml + 8, mt + plot_h - 6, "start", "− offense · − defense"),
        (ml + plot_w - 8, mt + plot_h - 6, "end", "+ offense · − defense"),
    ]
    for cx, cy, anchor, text in captions:
        parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" class="ff4-quad" text-anchor="{anchor}">{esc(text)}</text>')

    # Label placement with a light de-overlap pass: labels keep their dot's x
    # side but get nudged vertically when two nearby teams would collide.
    placed: list[tuple[float, float]] = []  # (label x, label y) already used

    def _label_y(px: float, py: float) -> float:
        ly = py + 3.5
        for ox_, oy_ in sorted(placed, key=lambda q: q[1]):
            if abs(px - ox_) < 52 and abs(ly - oy_) < 11:
                ly = oy_ + 11.0
        placed.append((px, ly))
        return ly

    for team, stat, ox, dy in sorted(points, key=lambda p: (sy(p[3]), safe_int(p[0].get("tid")))):
        tid = safe_int(team.get("tid"))
        color = team_chart_color(tid)
        ff = four_factors(stat)
        px, py = sx(ox), sy(dy)
        anchor = "end" if px > ml + plot_w - 42 else "start"
        lx = px - 9 if anchor == "end" else px + 9
        ly = _label_y(lx, py)
        title = (
            f"{team_full_name(team)} — Off {fmt_number(ox, 1)} / Def {fmt_number(dy, 1)} pts per 100 poss. "
            f"eFG% {fmt_number(ff.get('efg'), 1)} · TOV% {fmt_number(ff.get('tov_pct'), 1)} · "
            f"ORB% {fmt_number(ff.get('orb_pct'), 1)} · FT/FGA {fmt_number(ff.get('ft_rate'), 2)}"
        )
        parts.append(
            f'<a href="teams/{team_slug(team)}.html" class="ff4-link" aria-label="{esc(team_full_name(team))}">'
            f'<g class="ff4-pt" style="--ff4-c:{esc(color)}">'
            f'<title>{esc(title)}</title>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5.5" class="ff4-dot"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" class="ff4-label" text-anchor="{anchor}">{esc(team_abbrev(team))}</text>'
            f"</g></a>"
        )

    parts.append(f'<text x="{ml + plot_w / 2:.1f}" y="{height - 6:.1f}" class="ff4-axis" text-anchor="middle">offense — points scored per 100 possessions →</text>')
    parts.append(f'<text x="12" y="{mt + plot_h / 2:.1f}" class="ff4-axis" text-anchor="middle" transform="rotate(-90 12 {mt + plot_h / 2:.1f})">defense — fewer points allowed ↑</text>')

    sub = _season_label(chart_season, page_season)
    sub_html = f'<span class="count-pill">{esc(sub)}</span>' if sub else '<span class="muted small-copy" title="Dashed lines mark the league average; top-right is the winning quadrant">points per 100 possessions</span>'
    caption = f"{chart_season} four factors · hover a dot for detail"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Offense vs Defense</h2>{sub_html}</div>
      <div class="chart-wrap ff4-wrap">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="ff4-chart" role="img" aria-label="Team offensive vs defensive rating scatter, {esc(chart_season)} season">
          {''.join(parts)}
        </svg>
      </div>
      <p class="muted small-copy">{esc(caption)}</p>
    </section>
    """


# Short x-tick names per BBGM phase for odds-river snapshots.
_RIVER_PHASE_TICKS = {0: "Pre", 1: "RS", 2: "RS", 3: "PO", 4: "Off", 5: "Draft", 6: "Off", 7: "Re-sign", 8: "FA"}
_RIVER_PHASE_NAMES = {0: "Preseason", 1: "Regular season", 2: "Regular season", 3: "Playoffs", 4: "Offseason",
                      5: "Draft", 6: "Offseason", 7: "Re-signing", 8: "Free agency"}


def _river_snapshot_labels(snaps: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(short tick labels, long tooltip labels) for the ledger snapshots.

    Repeated phases get a running number ("RS 1", "RS 2", …) so every snapshot
    has a distinct, honest label even though the ledger doesn't store days.
    """
    shorts = [_RIVER_PHASE_TICKS.get(safe_int(s.get("phase"), -1), "?") for s in snaps]
    longs = [_RIVER_PHASE_NAMES.get(safe_int(s.get("phase"), -1), "Snapshot") for s in snaps]
    counts: dict[str, int] = defaultdict(int)
    for short in shorts:
        counts[short] += 1
    seen: dict[str, int] = defaultdict(int)
    out_short, out_long = [], []
    for short, long_label in zip(shorts, longs):
        seen[short] += 1
        if counts[short] > 1:
            out_short.append(f"{short} {seen[short]}")
            out_long.append(f"{long_label} · update {seen[short]}")
        else:
            out_short.append(short)
            out_long.append(long_label)
    return out_short, out_long


def odds_river_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int,
                    history: list[dict[str, Any]] | None = None) -> str:
    """Playoff-odds river (B14): every team's PO% across the ledger snapshots.

    Reads league-data/odds_history.json (one snapshot per CI build). With a
    single snapshot it renders a graceful dot-only state; from two snapshots on
    it draws the ten team-colored lines with a JS hover crosshair.
    """
    if history is None:
        history = load_odds_history()
    snaps = [s for s in history if safe_int(s.get("season"), -1) == season]
    if not snaps:
        return ""
    n = len(snaps)
    teams_sorted = sorted(active_teams_for_season(teams, season), key=team_sort_key)
    ticks, tick_names = _river_snapshot_labels(snaps)

    width, height = 680.0, 260.0
    ml, mr, mt, mb = 40.0, 64.0, 12.0, 30.0
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def sx(i: int) -> float:
        return ml + (plot_w * i / (n - 1) if n > 1 else 0.0)

    def sy(pct: float) -> float:
        return mt + plot_h - max(0.0, min(100.0, pct)) / 100.0 * plot_h

    parts: list[str] = []
    for pct in (0, 25, 50, 75, 100):
        gy = sy(pct)
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w:.1f}" y2="{gy:.1f}" class="chart-grid"/>')
        parts.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{pct}</text>')
    for i, tick in enumerate(ticks):
        parts.append(f'<text x="{sx(i):.1f}" y="{height - 8:.1f}" class="chart-tick" text-anchor="middle">{esc(tick)}</text>')

    payload_teams = []
    end_labels = []
    for team in teams_sorted:
        tid = safe_int(team.get("tid"))
        color = team_chart_color(tid)
        series: list[float | None] = []
        for snap in snaps:
            entry = (snap.get("teams") or {}).get(str(tid))
            series.append(round(100.0 * safe_float(entry.get("po")), 1) if isinstance(entry, dict) else None)
        if all(v is None for v in series):
            continue
        # Split at missing snapshots so gaps are never drawn as data.
        segments: list[list[int]] = []
        run: list[int] = []
        for i, value in enumerate(series):
            if value is None:
                if run:
                    segments.append(run)
                run = []
            else:
                run.append(i)
        if run:
            segments.append(run)
        team_parts = [f'<g class="oddsr-team" data-tid="{tid}" style="--oddsr-c:{esc(color)}">']
        for seg in segments:
            if len(seg) > 1:
                pts = " ".join(f"{sx(i):.1f},{sy(series[i]):.1f}" for i in seg)
                team_parts.append(f'<polyline points="{pts}" class="oddsr-line"/>')
        for i in ([seg[0] for seg in segments if len(seg) == 1] if n > 1 else [i for i, v in enumerate(series) if v is not None]):
            team_parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(series[i]):.1f}" r="3.4" class="oddsr-dot"/>')
        team_parts.append("</g>")
        parts.append("".join(team_parts))
        last_i = max(i for i, v in enumerate(series) if v is not None)
        end_labels.append((sy(series[last_i]), tid, color, team_abbrev(team)))
        payload_teams.append({"tid": tid, "ab": team_abbrev(team), "name": team_full_name(team),
                              "color": color, "po": series})
    if not payload_teams:
        return ""

    # De-overlap the team labels (same clamp as the bump chart). With a single
    # snapshot the dots sit at the left edge, so the labels follow them there.
    gap = 12.0
    prev_y = -1e9
    label_x = ml + plot_w + 8 if n > 1 else ml + 12
    for anchor_y, tid, color, abbrev in sorted(end_labels):
        ny = max(anchor_y, prev_y + gap)
        prev_y = ny
        parts.append(
            f'<text x="{label_x:.1f}" y="{ny + 3.5:.1f}" class="oddsr-endlabel" '
            f'data-tid="{tid}" style="--oddsr-c:{esc(color)}">{esc(abbrev)}</text>'
        )
        if abs(ny - anchor_y) > 1.0:
            parts.append(f'<line x1="{label_x - 6:.1f}" y1="{anchor_y:.1f}" x2="{label_x - 2:.1f}" y2="{ny:.1f}" class="oddsr-leader"/>')

    if n > 1:
        hover = (f'<line class="oddsr-hline" data-oddsr-hline y1="{mt}" y2="{mt + plot_h:.1f}" style="display:none"/>')
        note = f"{n} snapshots · hover for detail"
        payload = {
            "labels": ticks, "names": tick_names,
            "teams": payload_teams,
            "g": {"ml": ml, "mt": mt, "pw": plot_w, "ph": plot_h, "w": width, "h": height, "n": n},
        }
        payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
        payload_html = f'<script type="application/json" id="oddsr-data">{payload_json}</script>'
        tooltip_html = '<div class="chart-tooltip oddsr-tooltip" data-oddsr-tooltip hidden></div>'
        wrap_attr = " data-oddsr"
    else:
        hover = ""
        note = "one snapshot so far · history accumulates each update"
        payload_html = ""
        tooltip_html = ""
        wrap_attr = ""
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Playoff Odds Over Time</h2><span class="muted small-copy">{esc(note)}</span></div>
      <div class="chart-wrap oddsr-wrap"{wrap_attr}>
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="oddsr-chart" role="img" aria-label="Playoff odds by team across {n} season {'snapshot' if n == 1 else 'snapshots'}">
          {''.join(parts)}
          {hover}
        </svg>
        {tooltip_html}
      </div>
      {payload_html}
    </section>
    """


def fantasy_leaders_card(data: dict[str, Any], players: list[dict[str, Any]], teams: list[dict[str, Any]],
                         fantasy_season: int, page_season: int, root: str = "") -> str:
    """Top 8 by fantasy points per game (B11), scored via smp.derived.fantasy_pts."""
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    max_team_gp = max((safe_float(_exact_team_stat(t, fantasy_season).get("gp")) for t in teams), default=0.0)
    if max_team_gp <= 0:
        return ""
    min_gp = max(1.0, 0.7 * max_team_gp)
    scored = []
    for player in players:
        if safe_int(player.get("tid"), -9) < FREE_AGENT_TID:
            continue
        stat = season_regular_stat(player, fantasy_season)
        gp = stat_gp(stat)
        if gp < min_gp:
            continue
        fpts = fantasy_pts(stat)
        if fpts is None:
            continue
        scored.append((fpts / gp, gp, player, stat))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], player_name(x[2])))
    top = scored[:8]
    best = top[0][0] or 1.0
    rows = []
    for rank, (fppg, gp, player, stat) in enumerate(top, 1):
        # Attribute production to the team the player actually played for that
        # season (the stat row), not wherever they signed since.
        disp_tid = safe_int(stat.get("tid"), -1)
        if disp_tid < 0:
            disp_tid = safe_int(player.get("tid"), -1)
        bar_w = max(4.0, 100.0 * fppg / best)
        fppg_int = int(round(fppg))
        rows.append(
            f'<li title="{esc(player_name(player))}: {fppg_int} fantasy points per game over {fmt_number(gp, 0)} games">'
            f'<span class="leader-rank">{rank}</span>'
            f'{team_dot(disp_tid, palette)}'
            f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>'
            f'<span class="leader-team">{esc(team_abbrev_for_tid(disp_tid, teams_by_tid))}</span>'
            f'<span class="fanl-track"><span class="fanl-bar" style="width:{bar_w:.0f}%"></span></span>'
            f'<span class="leader-value">{fppg_int}</span></li>'
        )
    sub = _season_label(fantasy_season, page_season)
    note = f"{sub} · " if sub else ""
    note += f"FPTS/G · min {fmt_number(min_gp, 0)} GP"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Fantasy Leaders</h2><span class="muted small-copy">{esc(note)}</span></div>
      <ol class="leader-list fanl-list">{''.join(rows)}</ol>
    </section>
    """


def _home_columns(main_cards: list[str], side_cards: list[str]) -> str:
    """Two-column layout that never emits empty wrappers (no hollow home-side)."""
    main_html = "".join(card for card in main_cards if card)
    side_html = "".join(card for card in side_cards if card)
    if main_html and side_html:
        return (f'<div class="home-columns"><div class="home-main">{main_html}</div>'
                f'<div class="home-side">{side_html}</div></div>')
    return main_html + side_html


def render_home_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]],
                     season: int, start_season: int, odds_history: list[dict[str, Any]] | None = None) -> str:
    chart_teams = active_teams_for_season(teams, season)
    # Once a season is over, the projection worth showing is the upcoming one (simulated from
    # current rosters); mid-season this is just the current season, so the card is unchanged.
    proj_season = inferred_upcoming_schedule_season(data)
    kind = home_phase_kind(data, season)
    completed = last_completed_season(data, season)
    if odds_history is None:
        odds_history = load_odds_history()
    river = odds_river_card(data, chart_teams, season, history=odds_history)
    if not river and proj_season != season:
        river = odds_river_card(data, active_teams_for_season(teams, proj_season), proj_season, history=odds_history)

    if kind == "preseason":
        # No real games yet: lead with the year-ahead projections and the offseason
        # story; zero-data standings/team-stats/award cards are replaced by the
        # banner's one-line explanation instead of rendering as dash walls.
        ff_season = completed
        fantasy_season = completed
        body = f"""
        <h1 class="sr-only">SMP Basketball League</h1>
        {preseason_banner(data, season)}
        {_home_columns(
            [
                playoff_odds_card(data, chart_teams, proj_season),
                stakes_card(data, chart_teams, season),
                four_factors_scatter_card(data, teams, ff_season, season),
                river,
            ],
            [
                offseason_digest_card(data, teams, completed),
                preseason_rookie_watch_card(players, teams, season),
                fantasy_leaders_card(data, players, teams, fantasy_season, season),
                injury_report_card(players, teams, season),
                news_feed_card(data, teams, season),
            ],
        )}
        {home_finances_table(data, teams, players, season)}
        """
    elif kind == "playoffs":
        body = f"""
        <h1 class="sr-only">SMP Basketball League</h1>
        {playoff_bracket_card(data, chart_teams, season)}
        {latest_results_strip(data, chart_teams, season)}
        {_home_columns(
            [
                standings_table(data, chart_teams, season),
                league_leaders_card(data, players, teams, season),
                four_factors_scatter_card(data, teams, season, season),
                river,
            ],
            [
                news_feed_card(data, teams, season),
                injury_report_card(players, teams, season),
                fantasy_leaders_card(data, players, teams, season, season),
                rookie_watch_card(data, players, teams, season),
            ],
        )}
        {team_stats_table(chart_teams, season)}
        {awards_voting_table(data, players, teams, season)}
        {home_finances_table(data, teams, players, season)}
        """
    elif kind == "offseason":
        body = f"""
        <h1 class="sr-only">SMP Basketball League</h1>
        {season_awards_card(data, teams, completed)}
        {_home_columns(
            [
                fa_watch_card(data, teams, season),
                standings_table(data, chart_teams, season),
                four_factors_scatter_card(data, teams, completed, season),
                river,
            ],
            [
                offseason_digest_card(data, teams, completed),
                fantasy_leaders_card(data, players, teams, completed, season),
                news_feed_card(data, teams, season),
            ],
        )}
        {team_stats_table(chart_teams, season)}
        {awards_voting_table(data, players, teams, season)}
        {home_finances_table(data, teams, players, season)}
        """
    else:
        body = f"""
        <h1 class="sr-only">SMP Basketball League</h1>
        {latest_results_strip(data, chart_teams, season)}
        {_home_columns(
            [
                standings_table(data, chart_teams, season),
                playoff_odds_card(data, chart_teams, proj_season),
                stakes_card(data, chart_teams, season),
                league_leaders_card(data, players, teams, season),
                four_factors_scatter_card(data, teams, season, season),
                river,
            ],
            [
                news_feed_card(data, teams, season),
                injury_report_card(players, teams, season),
                fantasy_leaders_card(data, players, teams, season, season),
                rookie_watch_card(data, players, teams, season),
            ],
        )}
        {team_stats_table(chart_teams, season)}
        {awards_voting_table(data, players, teams, season)}
        {home_finances_table(data, teams, players, season)}
        """
    return page_html("Home", body, teams, root="", active="home")
