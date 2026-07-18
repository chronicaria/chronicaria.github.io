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

from .core import RATING_GROUPS, RATING_LABELS, esc, player_name, safe_float, safe_int

from .simmodel import PROJ_N_SIMS, PROJ_SEASONS_AHEAD, _player_current_ovr, _player_projection


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
