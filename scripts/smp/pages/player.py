from __future__ import annotations

"""Per-player pages.

One unified page per player with a sticky section rail (Overview · Stats ·
Game Log · Ratings · Contract & Injuries) and scroll-spy (static/js/player.js).
The old ``-stats`` / ``-log`` / ``-ratings`` URLs are kept alive as tiny
meta-refresh stubs that forward to the unified page's anchors.
"""

from collections import defaultdict
from typing import Any

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
    team_full_for_tid,
    team_label,
    team_url,
    th,
    total_2p,
    total_2pa,
    ts_pct,
    turnover_pct,
)

from ..simmodel import _player_projection

from ..charts import development_chart_html

# The FA asking price is the free-agency board's model — import it so the two
# pages can never drift apart.
from .league import fa_asking_price

from ..identity import crest_svg, monogram_svg, team_css_vars, team_identity

from ..portraits import portrait_html as _portraits_portrait_html

from ..derived import fantasy_pts, led_league, player_shot_zones, SHOT_ZONES, ZONE_LABELS


# Basketball GM skill codes -> plain-English labels (chip tooltips).
SKILL_LABELS = {
    "3": "Three-point shooter",
    "A": "Athlete",
    "B": "Ball handler",
    "Di": "Interior defender",
    "Dp": "Perimeter defender",
    "Po": "Post scorer",
    "Ps": "Passer",
    "R": "Rebounder",
    "V": "Volume scorer",
}

# Trophy case: award type string -> (crest kind, shelf, short label).
# Shelf 0 = major hardware, shelf 1 = season honors; anything unmapped
# (stat titles, Hall of Fame) lands on a third text-chip shelf.
AWARD_CRESTS = {
    "Won Championship": ("champion", 0, "Champion"),
    "Most Valuable Player": ("mvp", 0, "MVP"),
    "Finals MVP": ("finals_mvp", 0, "Finals MVP"),
    "Semifinals MVP": ("sfmvp", 0, "Semis MVP"),
    "Defensive Player of the Year": ("dpoy", 0, "DPOY"),
    "Rookie of the Year": ("roy", 0, "ROY"),
    "Sixth Man of the Year": ("smoy", 0, "6MOY"),
    "Most Improved Player": ("mip", 0, "MIP"),
    "First Team All-League": ("all_league_1", 1, "All-League 1st"),
    "Second Team All-League": ("all_league_2", 1, "All-League 2nd"),
    "Third Team All-League": ("all_league_3", 1, "All-League 3rd"),
    "First Team All-Defensive": ("all_defensive", 1, "All-Defensive 1st"),
    "Second Team All-Defensive": ("all_defensive", 1, "All-Defensive 2nd"),
    "Third Team All-Defensive": ("all_defensive", 1, "All-Defensive 3rd"),
    "All-Rookie Team": ("all_rookie", 1, "All-Rookie"),
}

# Display order within the crest shelves (dict order above is the source of truth).
_AWARD_ORDER = {name: i for i, name in enumerate(AWARD_CRESTS)}

# led_league(data) is tiny but called for every player page; memoize per export.
# The cache pins the export dict itself so a recycled id() can never alias.
_LED_CACHE: dict[int, tuple[dict[str, Any], dict[int, dict[str, float]]]] = {}


def _led_index(data: dict[str, Any] | None) -> dict[int, dict[str, float]]:
    if not data:
        return {}
    cached = _LED_CACHE.get(id(data))
    if cached is None or cached[0] is not data:
        _LED_CACHE.clear()  # one export per build; don't hoard stale ones
        cached = (data, led_league(data))
        _LED_CACHE[id(data)] = cached
    return cached[1]


def _led_hits(led: dict[int, dict[str, float]], season: Any, values: dict[str, float | None]) -> set[str]:
    """Which seasonLeaders keys this row's values tie exactly (they led the league)."""
    if not isinstance(season, int):
        return set()
    leaders = led.get(season) or {}
    hits: set[str] = set()
    for key, value in values.items():
        lead = leaders.get(key)
        if lead is None or value is None:
            continue
        if abs(float(value) - float(lead)) <= 1e-6:
            hits.add(key)
    return hits


def _led_td(content: Any, sort: Any, hit: bool, label: str, cls: str = "") -> str:
    """A td() that gets the gold led-league treatment when ``hit``."""
    if not hit:
        return td(content, sort=sort, cls=cls)
    body = (
        f'{content}<span class="led-star" title="Led the league in {esc(label)}" aria-hidden="true">★</span>'
        f'<span class="sr-only">Led the league in {esc(label)}</span>'
    )
    classes = f"led-league {cls}".strip()
    return td(body, sort=sort, cls=classes)


def detail_item(label: str, value: str) -> str:
    return f'<div class="detail-item"><span>{esc(label)}</span><strong>{value}</strong></div>'


def _delta_titled(player: dict[str, Any], key: str, rating: dict[str, Any]) -> str:
    """rating_delta_html with a 'vs last season' tooltip on the delta readout."""
    return f'<span title="Change vs last season">{rating_delta_html(player, key, rating)}</span>'


def player_portrait(player: dict[str, Any], cls: str = "portrait", root: str = "../", size: int = 120) -> str:
    """portraits.portrait_html with a local guard: its monogram fallback currently
    passes ``size=`` to identity.monogram_svg (which takes ``css_class``); until
    that is fixed upstream, render the roundel directly rather than crash."""
    try:
        return _portraits_portrait_html(player, cls=cls, root=root, size=size)
    except TypeError:
        mono = monogram_svg(initials(player), player.get("tid"), jersey_number=player.get("jerseyNumber"))
        return (
            f'<span class="{esc(cls)} portrait-monogram" role="img" '
            f'aria-label="{esc(player_name(player))}">{mono}</span>'
        )


# ---------------------------------------------------------------------------
# Trading-card hero
# ---------------------------------------------------------------------------


def _career_team_dots(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    """One color dot per franchise the player has suited up for (statsTids order)."""
    seen: list[int] = []
    for tid in player.get("statsTids") or []:
        tid = safe_int(tid, -1)
        if tid >= 0 and tid not in seen:
            seen.append(tid)
    if not seen:
        return ""
    cur_tid = safe_int(player.get("tid"), RETIRED_TID)
    dots = []
    for tid in seen:
        ident = team_identity(tid)
        name = team_full_for_tid(tid, teams_by_tid)
        cur = " career-dot--now" if tid == cur_tid else ""
        style = f"background:{ident['primary']};box-shadow:inset 0 0 0 2px {ident['secondary']}"
        team = teams_by_tid.get(tid)
        if team:
            dots.append(
                f'<a class="career-dot{cur}" href="{team_url(team, root)}" '
                f'style="{style}" title="{esc(name)}"><span class="sr-only">{esc(name)}</span></a>'
            )
        else:
            dots.append(
                f'<span class="career-dot{cur}" style="{style}" title="{esc(name)}">'
                f'<span class="sr-only">{esc(name)}</span></span>'
            )
    return (
        '<div class="career-dots"><span class="career-dots-label">Career teams</span>'
        + "".join(dots)
        + "</div>"
    )


def _card_stat_tiles(player: dict[str, Any], season: int) -> str:
    """Headline per-game tiles (PTS/REB/AST + integer FPTS) from the player's
    most recent regular season with games played. Combines multi-team rows so a
    midseason trade still reads as one line. Returns "" when nothing was played."""
    rows = [
        s for s in player.get("stats", [])
        if not s.get("playoffs") and isinstance(s.get("season"), int)
        and s.get("season") <= season and stat_gp(s) > 0
    ]
    if not rows:
        return ""
    last_season = max(s["season"] for s in rows)
    season_rows = [s for s in rows if s["season"] == last_season]
    stat = combine_stat_rows(season_rows) if len(season_rows) > 1 else season_rows[0]
    gp = stat_gp(stat)
    if gp <= 0:
        return ""
    trb_pg = (safe_float(stat.get("orb")) + safe_float(stat.get("drb"))) / gp
    fpts = fantasy_pts(stat)
    tiles = [
        ("PTS", fmt_number(per_game(stat, "pts"), 1), ""),
        ("REB", fmt_number(trb_pg, 1), ""),
        ("AST", fmt_number(per_game(stat, "ast"), 1), ""),
    ]
    if fpts is not None:
        tiles.append(("FPTS", fmt_number(fpts / gp, 0), " card-tile--fpts"))
    tiles_html = "".join(
        f'<div class="card-tile{cls}"><strong>{value}</strong><span>{esc(label)}</span></div>'
        for label, value, cls in tiles
    )
    return (
        f'<div class="player-card-tiles" role="group" aria-label="Per-game averages, {last_season} season">'
        f'{tiles_html}<span class="card-tiles-cap">{last_season} per game</span></div>'
    )


def trading_card_html(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int, root: str = "../") -> str:
    tid = safe_int(player.get("tid"), RETIRED_TID)
    on_team = tid >= 0
    is_fa = tid == FREE_AGENT_TID
    rating = latest_rating(player, season)
    name = player_name(player)

    # Free agents / prospects get the neutral silver card (vars set in CSS).
    card_cls = "player-card" if on_team else "player-card player-card--fa"
    vars_attr = f' style="{team_css_vars(tid)}"' if on_team else ""

    number = player.get("jerseyNumber")
    number_txt = str(number).strip() if number not in (None, "") else ""
    numeral = (
        f'<span class="player-card-num" aria-label="Jersey number {esc(number_txt)}">{esc(number_txt)}</span>'
        if number_txt
        else ""
    )

    # Nameplate: position chip + team + age (+ asking price for free agents).
    if on_team:
        team = teams_by_tid.get(tid)
        team_html = (
            f'<a class="player-card-team" href="{team_url(team, root)}">{esc(team_full_for_tid(tid, teams_by_tid))}</a>'
            if team
            else esc(team_full_for_tid(tid, teams_by_tid))
        )
    elif is_fa:
        team_html = f'<a class="player-card-team" href="{root}free-agency.html">Free Agent</a>'
    else:
        team_html = "Draft prospect"
    ask_html = ""
    if is_fa:
        bid_k = fa_asking_price(player, season)
        ask_html = (
            f'<span class="plate-ask" title="One-year asking salary — same model as the Free Agency board">'
            f'<span>Asking price</span><strong>{fmt_money(bid_k)}</strong></span>'
        )
    plate_html = (
        f'<div class="player-card-plate">'
        f'<span class="plate-pos" title="Position">{esc(rating.get("pos", "—"))}</span>'
        f'<span class="plate-team">{team_html}</span>'
        f'<span class="plate-meta muted">Age {age(player, season)}</span>'
        f'{ask_html}</div>'
    )

    skills = rating.get("skills") or []
    skills_html = ""
    if skills:
        chips = "".join(
            f'<span class="player-card-skill" title="{esc(SKILL_LABELS.get(s, s))}">{esc(s)}</span>'
            for s in skills
        )
        skills_html = f'<div class="player-card-skills">{chips}</div>'

    dots_html = _career_team_dots(player, teams_by_tid, root)
    foot = f'<div class="player-card-foot">{dots_html}</div>' if dots_html else ""

    return f"""
    <section class="{card_cls}"{vars_attr}>
      <div class="player-card-face">
        {numeral}
        <div class="player-card-body">
          <h1>{esc(name)}</h1>
          {skills_html}
        </div>
        <div class="player-card-portrait">{player_portrait(player, cls="portrait card-portrait", root=root, size=132)}</div>
      </div>
      {plate_html}
      {_card_stat_tiles(player, season)}
      {foot}
    </section>
    """


def player_bio_html(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int) -> str:
    """Bio facts + current ratings (the old hero's grids, on a normal card)."""
    rating = latest_rating(player, season)
    team_html = team_label(player.get("tid"), teams_by_tid, "../")
    # Free agents: the export's contract stub is meaningless — show the market ask.
    if safe_int(player.get("tid"), RETIRED_TID) == FREE_AGENT_TID:
        contract_html = f"{fmt_money(fa_asking_price(player, season))}/yr asking"
    else:
        contract_html = fmt_contract(player)
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
        detail_item("Contract", contract_html),
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

    return f"""
    <section class="card player-bio">
      <div class="player-bio-cols">
        <div>
          <div class="section-title-row"><h2>Bio</h2></div>
          <div class="details-grid">{details}</div>
        </div>
        <div class="rating-panel full-rating-panel">
          <div class="rating-topline">
            <div class="big-rating"><span>Overall</span><strong>{_delta_titled(player, 'ovr', rating)}</strong></div>
            <div class="big-rating"><span>Potential</span><strong>{_delta_titled(player, 'pot', rating)}</strong></div>
          </div>
          <p class="rating-caption muted small-copy">Green/red = change vs last season.</p>
          <div class="rating-groups">{''.join(rating_groups_html)}</div>
        </div>
      </div>
    </section>
    """


# ---------------------------------------------------------------------------
# Trophy case
# ---------------------------------------------------------------------------


def trophy_case_html(player: dict[str, Any]) -> str:
    awards = [a for a in player.get("awards") or [] if isinstance(a, dict) and a.get("type")]
    if not awards:
        return ""
    grouped: dict[str, list[Any]] = defaultdict(list)
    first_seen: dict[str, int] = {}
    for i, award in enumerate(awards):
        atype = str(award.get("type"))
        grouped[atype].append(award.get("season"))
        first_seen.setdefault(atype, i)

    def seasons_text(seasons: list[Any]) -> str:
        return ", ".join(str(s) for s in seasons if s is not None)

    shelves: dict[int, list[str]] = {0: [], 1: [], 2: []}
    crest_types = sorted(
        (t for t in grouped if t in AWARD_CRESTS),
        key=lambda t: _AWARD_ORDER[t],
    )
    for atype in crest_types:
        kind, shelf, short = AWARD_CRESTS[atype]
        seasons = grouped[atype]
        count = f'<span class="trophy-count">×{len(seasons)}</span>' if len(seasons) > 1 else ""
        gold = " trophy--gold" if shelf == 0 else ""
        shelves[shelf].append(
            f'<div class="trophy{gold}" title="{esc(atype)} — {esc(seasons_text(seasons))}">'
            f'{crest_svg(kind, css_class="crest trophy-crest")}'
            f'<span class="trophy-label">{esc(short)}</span>{count}</div>'
        )
    # Stat titles, Hall of Fame, anything future BBGM invents: compact text chips.
    other_types = sorted((t for t in grouped if t not in AWARD_CRESTS), key=lambda t: first_seen[t])
    for atype in other_types:
        seasons = grouped[atype]
        label = atype.replace("League ", "")
        if atype == "Inducted into the Hall of Fame":
            label = "Hall of Fame"
        count = f" ×{len(seasons)}" if len(seasons) > 1 else ""
        shelves[2].append(
            f'<span class="trophy-chip" title="{esc(atype)} — {esc(seasons_text(seasons))}">'
            f"{esc(label)}{esc(count)}</span>"
        )

    shelf_html = "".join(
        f'<div class="trophy-shelf">{"".join(items)}</div>' for items in (shelves[0], shelves[1], shelves[2]) if items
    )
    return f"""
    <section class="card trophy-case">
      <div class="section-title-row"><h2>Trophy Case</h2><span class="count-pill">{len(awards)} award{"s" if len(awards) != 1 else ""}</span></div>
      {shelf_html}
    </section>
    """


# ---------------------------------------------------------------------------
# Season tables (summary, per-game, shot, advanced)
# ---------------------------------------------------------------------------


def _fpts_per_game(stat: dict[str, Any]) -> float | None:
    gp = stat_gp(stat)
    total = fantasy_pts(stat)
    if total is None or gp <= 0:
        return None
    return total / gp


def player_summary_rows(player: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], season: int, start_season: int) -> str:
    regular = regular_stats_since(player, start_season)
    current = [s for s in regular if s.get("season") == season]
    current_stat = current[-1] if current else (regular[-1] if regular else {})
    career = combine_stat_rows(regular) if regular else {}
    # Preseason exports have no current-season stats yet; label the row with the
    # season the numbers actually come from instead of claiming the new one.
    latest_label = str(current_stat.get("season", season)) if current_stat else str(season)

    def row(label: str, stat: dict[str, Any]) -> str:
        if not stat:
            values = [label] + ["—"] * 8
            sorts = [label] + [None] * 8
        else:
            gp = stat_gp(stat)
            trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
            fpts = _fpts_per_game(stat)
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
                fmt_number(fpts, 0) if fpts is not None else "—",
            ]
            sorts = [label, gp, per_game(stat, "min"), per_game(stat, "pts"), trb_pg, per_game(stat, "ast"), made_pct(stat.get("fg"), stat.get("fga")), made_pct(stat.get("tp"), stat.get("tpa")), made_pct(stat.get("ft"), stat.get("fta")), ts_pct(stat), stat.get("per"), (float(stat.get("ows") or 0) + float(stat.get("dws") or 0)), fpts]
        return "<tr>" + "".join(td(v, sort=s) for v, s in zip(values, sorts)) + "</tr>"

    headers = ["Summary", "G", "MP", "PTS", "TRB", "AST", "FG%", "3P%", "FT%", "TS%", "PER", "WS", "FPTS"]
    return f"""
    <section class="card compact-card">
      <div class="table-wrap summary-wrap">
        <table>
          <thead><tr>{''.join(th(h) for h in headers)}</tr></thead>
          <tbody>
            {row(latest_label, current_stat)}
            {row('Career', career)}
          </tbody>
        </table>
      </div>
    </section>
    """


def per_game_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str, led: dict[int, dict[str, float]] | None = None) -> str:
    led = led or {}
    source_rows = rows[:]
    display_rows = rows[:]
    if len(rows) > 1:
        display_rows.append(combine_stat_rows(rows))

    headers = ["Year", "Team", "Age", "G", "GS", "MP", "FG", "FGA", "FG%", "3P", "3PA", "3P%", "2P", "2PA", "2P%", "eFG%", "FT", "FTA", "FT%", "ORB", "DRB", "TRB", "AST", "TOV", "STL", "BLK", "BA", "PF", "PTS", "FPTS"]
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
        fpts = _fpts_per_game(stat)
        hits = _led_hits(led, season, {
            "min": per_game(stat, "min"),
            "fgp": fg_pct,
            "tpp": tp_pct,
            "2pp": two_pct,
            "efg": efg_pct(stat),
            "ftp": ft_pct,
            "orb": per_game(stat, "orb"),
            "drb": per_game(stat, "drb"),
            "trb": trb_pg,
            "ast": per_game(stat, "ast"),
            "stl": per_game(stat, "stl"),
            "blk": per_game(stat, "blk"),
            "pts": per_game(stat, "pts"),
        }) if not stat.get("playoffs") else set()
        html_rows.append("".join([
            td(year_cell, sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            _led_td(fmt_number(per_game(stat, "min"), 1), per_game(stat, "min"), "min" in hits, "minutes per game"),
            td(fmt_number(per_game(stat, "fg"), 1), sort=per_game(stat, "fg")),
            td(fmt_number(per_game(stat, "fga"), 1), sort=per_game(stat, "fga")),
            _led_td(fmt_pct(fg_pct), fg_pct, "fgp" in hits, "FG%"),
            td(fmt_number(per_game(stat, "tp"), 1), sort=per_game(stat, "tp")),
            td(fmt_number(per_game(stat, "tpa"), 1), sort=per_game(stat, "tpa")),
            _led_td(fmt_pct(tp_pct), tp_pct, "tpp" in hits, "3P%"),
            td(fmt_number(total_2p(stat) / gp if gp else 0, 1), sort=(total_2p(stat) / gp if gp else 0)),
            td(fmt_number(total_2pa(stat) / gp if gp else 0, 1), sort=(total_2pa(stat) / gp if gp else 0)),
            _led_td(fmt_pct(two_pct), two_pct, "2pp" in hits, "2P%"),
            _led_td(fmt_pct(efg_pct(stat)), efg_pct(stat), "efg" in hits, "eFG%"),
            td(fmt_number(per_game(stat, "ft"), 1), sort=per_game(stat, "ft")),
            td(fmt_number(per_game(stat, "fta"), 1), sort=per_game(stat, "fta")),
            _led_td(fmt_pct(ft_pct), ft_pct, "ftp" in hits, "FT%"),
            _led_td(fmt_number(per_game(stat, "orb"), 1), per_game(stat, "orb"), "orb" in hits, "offensive rebounds"),
            _led_td(fmt_number(per_game(stat, "drb"), 1), per_game(stat, "drb"), "drb" in hits, "defensive rebounds"),
            _led_td(fmt_number(trb_pg, 1), trb_pg, "trb" in hits, "rebounds"),
            _led_td(fmt_number(per_game(stat, "ast"), 1), per_game(stat, "ast"), "ast" in hits, "assists"),
            td(fmt_number(per_game(stat, "tov"), 1), sort=per_game(stat, "tov")),
            _led_td(fmt_number(per_game(stat, "stl"), 1), per_game(stat, "stl"), "stl" in hits, "steals"),
            _led_td(fmt_number(per_game(stat, "blk"), 1), per_game(stat, "blk"), "blk" in hits, "blocks"),
            td(fmt_number(per_game(stat, "ba"), 1), sort=per_game(stat, "ba")),
            td(fmt_number(per_game(stat, "pf"), 1), sort=per_game(stat, "pf")),
            _led_td(fmt_number(per_game(stat, "pts"), 1), per_game(stat, "pts"), "pts" in hits, "scoring"),
            td(fmt_number(fpts, 0) if fpts is not None else "—", sort=fpts),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2><span class="count-pill">{len(source_rows)}</span></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No stats from the selected seasons.")}
    </section>
    """


def shot_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str, led: dict[int, dict[str, float]] | None = None) -> str:
    led = led or {}
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
        hits = _led_hits(led, season, {
            "fgpAtRim": rim_pct,
            "fgpLowPost": post_pct,
            "fgpMidRange": mid_pct,
            "tpp": tp_pct,
            "dd": safe_float(stat.get("dd")) if stat.get("dd") is not None else None,
            "td": safe_float(stat.get("td")) if stat.get("td") is not None else None,
        }) if not stat.get("playoffs") else set()
        html_rows.append("".join([
            td(esc(season), sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_number(per_game(stat, "fgAtRim"), 1), sort=per_game(stat, "fgAtRim")),
            td(fmt_number(per_game(stat, "fgaAtRim"), 1), sort=per_game(stat, "fgaAtRim")),
            _led_td(fmt_pct(rim_pct), rim_pct, "fgpAtRim" in hits, "at-rim FG%"),
            td(fmt_number(per_game(stat, "fgLowPost"), 1), sort=per_game(stat, "fgLowPost")),
            td(fmt_number(per_game(stat, "fgaLowPost"), 1), sort=per_game(stat, "fgaLowPost")),
            _led_td(fmt_pct(post_pct), post_pct, "fgpLowPost" in hits, "low-post FG%"),
            td(fmt_number(per_game(stat, "fgMidRange"), 1), sort=per_game(stat, "fgMidRange")),
            td(fmt_number(per_game(stat, "fgaMidRange"), 1), sort=per_game(stat, "fgaMidRange")),
            _led_td(fmt_pct(mid_pct), mid_pct, "fgpMidRange" in hits, "mid-range FG%"),
            td(fmt_number(per_game(stat, "tp"), 1), sort=per_game(stat, "tp")),
            td(fmt_number(per_game(stat, "tpa"), 1), sort=per_game(stat, "tpa")),
            _led_td(fmt_pct(tp_pct), tp_pct, "tpp" in hits, "3P%"),
            _led_td(fmt_number(stat.get("dd"), 0), stat.get("dd"), "dd" in hits, "double-doubles"),
            _led_td(fmt_number(stat.get("td"), 0), stat.get("td"), "td" in hits, "triple-doubles"),
            td(fmt_number(stat.get("qd"), 0), sort=stat.get("qd")),
            td(fmt_number(stat.get("fxf"), 0), sort=stat.get("fxf")),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No shot-location stats from the selected seasons.")}
    </section>
    """


def advanced_table(player: dict[str, Any], rows: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, title: str, table_id: str, led: dict[int, dict[str, float]] | None = None) -> str:
    led = led or {}
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
        hits = _led_hits(led, season, {
            "per": stat.get("per"),
            "ewa": stat.get("ewa"),
            "tsp": ts_pct(stat),
            "orbp": stat.get("orbp"),
            "drbp": stat.get("drbp"),
            "trbp": stat.get("trbp"),
            "astp": stat.get("astp"),
            "stlp": stat.get("stlp"),
            "blkp": stat.get("blkp"),
            "usgp": stat.get("usgp"),
            "pm100": stat.get("pm100"),
            "onOff100": stat.get("onOff100"),
            "ortg": stat.get("ortg"),
            "drtg": stat.get("drtg"),
            "ows": ows,
            "dws": dws,
            "ws": ws,
            "ws48": ws48,
            "obpm": obpm if stat.get("obpm") is not None else None,
            "dbpm": dbpm if stat.get("dbpm") is not None else None,
            "bpm": bpm if (stat.get("obpm") is not None or stat.get("dbpm") is not None) else None,
            "vorp": stat.get("vorp"),
        }) if not stat.get("playoffs") else set()
        html_rows.append("".join([
            td(esc(season), sort=season if isinstance(season, int) else 99999),
            td(team_label(stat.get("tid"), teams_by_tid, root), sort=team_label(stat.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season) if isinstance(season, int) else "—", sort=age_sort),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(stat.get("gs"), 0), sort=stat.get("gs")),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            _led_td(fmt_number(stat.get("per"), 1), stat.get("per"), "per" in hits, "PER"),
            _led_td(fmt_number(stat.get("ewa"), 1), stat.get("ewa"), "ewa" in hits, "EWA"),
            _led_td(fmt_pct(ts_pct(stat)), ts_pct(stat), "tsp" in hits, "TS%"),
            td(fmt_ratio(pmar), sort=pmar),
            td(fmt_ratio(ftr), sort=ftr),
            _led_td(fmt_number(stat.get("orbp"), 1), stat.get("orbp"), "orbp" in hits, "ORB%"),
            _led_td(fmt_number(stat.get("drbp"), 1), stat.get("drbp"), "drbp" in hits, "DRB%"),
            _led_td(fmt_number(stat.get("trbp"), 1), stat.get("trbp"), "trbp" in hits, "TRB%"),
            _led_td(fmt_number(stat.get("astp"), 1), stat.get("astp"), "astp" in hits, "AST%"),
            _led_td(fmt_number(stat.get("stlp"), 1), stat.get("stlp"), "stlp" in hits, "STL%"),
            _led_td(fmt_number(stat.get("blkp"), 1), stat.get("blkp"), "blkp" in hits, "BLK%"),
            td(fmt_number(turnover_pct(stat), 1), sort=turnover_pct(stat)),
            _led_td(fmt_number(stat.get("usgp"), 1), stat.get("usgp"), "usgp" in hits, "usage"),
            _led_td(fmt_number(stat.get("pm100"), 1), stat.get("pm100"), "pm100" in hits, "plus-minus", cls=("delta-up" if float(stat.get("pm100") or 0) > 0 else "delta-down" if float(stat.get("pm100") or 0) < 0 else "")),
            _led_td(fmt_number(stat.get("onOff100"), 1), stat.get("onOff100"), "onOff100" in hits, "on-off", cls=("delta-up" if float(stat.get("onOff100") or 0) > 0 else "delta-down" if float(stat.get("onOff100") or 0) < 0 else "")),
            _led_td(fmt_number(stat.get("ortg"), 1), stat.get("ortg"), "ortg" in hits, "offensive rating"),
            _led_td(fmt_number(stat.get("drtg"), 1), stat.get("drtg"), "drtg" in hits, "defensive rating"),
            _led_td(fmt_number(ows, 1), ows, "ows" in hits, "offensive win shares"),
            _led_td(fmt_number(dws, 1), dws, "dws" in hits, "defensive win shares"),
            _led_td(fmt_number(ws, 1), ws, "ws" in hits, "win shares"),
            _led_td(fmt_ratio(ws48), ws48, "ws48" in hits, "WS/48"),
            _led_td(fmt_number(obpm, 1), obpm, "obpm" in hits, "OBPM"),
            _led_td(fmt_number(dbpm, 1), dbpm, "dbpm" in hits, "DBPM"),
            _led_td(fmt_number(bpm, 1), bpm, "bpm" in hits, "BPM"),
            _led_td(fmt_number(stat.get("vorp"), 1), stat.get("vorp"), "vorp" in hits, "VORP"),
        ]))

    return f"""
    <section class="card stats-section">
      <div class="section-title-row"><h2>{esc(title)}</h2></div>
      {table_html(headers, html_rows, table_id=table_id, empty_message="No advanced stats from the selected seasons.")}
    </section>
    """


# ---------------------------------------------------------------------------
# Shot diet (per-season 100%-stacked attempt-share bars)
# ---------------------------------------------------------------------------


def _zone_fill(pct: float | None, lg_pct: float | None) -> str:
    """heat_style()'s red→green hue ramp, keyed to FG% vs the league average
    in the same zone (±8 percentage points saturates)."""
    if pct is None or lg_pct is None:
        return "var(--panel-3)"
    diff = max(-8.0, min(8.0, pct - lg_pct))
    frac = (diff + 8.0) / 16.0
    hue = 4 + frac * 126
    return f"hsla({hue:.0f}, 55%, 41%, .45)"


def shot_diet_html(player: dict[str, Any], data: dict[str, Any] | None, start_season: int) -> str:
    """One 100%-stacked bar per retained season: segment width = share of FGA
    by zone, tint = zone FG% vs league average, hover title = makes/attempts."""
    if not data:
        return ""
    pid = safe_int(player.get("pid"), -1)
    seasons = sorted({
        s.get("season") for s in regular_stats_since(player, start_season)
        if isinstance(s.get("season"), int)
    })
    rows = []
    for s in seasons:
        zones = player_shot_zones(data, pid, s)
        if not zones:
            continue
        total_fga = sum(safe_float(z.get("fga")) for z in zones.values())
        if total_fga <= 0:
            continue
        segments = []
        aria_bits = []
        x = 0.0
        for zone, _, _ in SHOT_ZONES:
            z = zones[zone]
            fga = safe_float(z.get("fga"))
            if fga <= 0:
                continue
            share = fga / total_fga
            width = share * 100.0
            pct = z.get("pct")
            lg_pct = z.get("lg_pct")
            label = ZONE_LABELS[zone]
            pct_txt = fmt_pct(pct) if pct is not None else "—"
            lg_txt = f" (lg {fmt_pct(lg_pct)})" if lg_pct is not None else ""
            title = (
                f"{label}: {fmt_number(z.get('fg'), 0)}/{fmt_number(fga, 0)} · "
                f"{pct_txt}% FG{lg_txt} · {fmt_number(share * 100, 0)}% of attempts"
            )
            segments.append(
                f'<rect x="{x:.2f}" y="0" width="{max(0.0, width - 0.4):.2f}" height="12" '
                f'fill="{_zone_fill(pct, lg_pct)}"><title>{esc(title)}</title></rect>'
            )
            aria_bits.append(f"{label} {fmt_number(share * 100, 0)}% of attempts at {pct_txt}% FG")
            x += width
        if not segments:
            continue
        aria = f"Season {s} shot diet: " + "; ".join(aria_bits)
        rows.append(
            f'<div class="shotdiet-row">'
            f'<span class="shotdiet-season">{esc(s)}</span>'
            f'<svg class="shotdiet-bar" viewBox="0 0 100 12" preserveAspectRatio="none" '
            f'role="img" aria-label="{esc(aria)}">{"".join(segments)}</svg>'
            f'<span class="shotdiet-fga muted small-copy">{fmt_number(total_fga, 0)} FGA</span>'
            f"</div>"
        )
    if not rows:
        return ""
    return f"""
    <section class="card compact-card shotdiet-card">
      <div class="section-title-row"><h2>Shot Diet</h2>
        <span class="muted small-copy" title="Zones left to right: At Rim, Low Post, Mid-Range, Three. Hover a segment for makes/attempts.">width = attempt share · tint = FG% vs league</span>
      </div>
      {''.join(rows)}
    </section>
    """


# ---------------------------------------------------------------------------
# Ratings / game log / opponents / highs / form (existing sections)
# ---------------------------------------------------------------------------


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
    <section class="card stats-section">
      <div class="section-title-row"><h2>Ratings</h2></div>
      {table_html(headers, rows, table_id=f"ratings-{player.get('pid')}", empty_message="No ratings from the selected seasons.")}
    </section>
    """


def game_log_table(player: dict[str, Any], entries: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int, root: str) -> str:
    played = [e for e in entries if safe_float((e.get("box") or {}).get("min")) > 0]
    if not played:
        return ""
    headers = ["Day", "Opp", "Result", "MP", "FG", "3P", "FT", "ORB", "TRB", "AST", "TOV", "STL", "BLK", "PF", "PTS", "+/-", "FPTS"]
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
        fpts = fantasy_pts(box)
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
            td(fmt_number(fpts, 0) if fpts is not None else "—", sort=fpts),
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
        out["fpts"] = sum(safe_float(fantasy_pts(e["box"])) for e in entries) / n
        return out

    return {"recent": averages(last5), "season": averages(season_games), "n": len(last5)}


def form_card_html(player: dict[str, Any], log_entries: list[dict[str, Any]]) -> str:
    form = player_form(log_entries)
    if not form:
        return ""
    rows = []
    for key, label, digits in (("pts", "PTS", 1), ("trb", "TRB", 1), ("ast", "AST", 1), ("min", "MIN", 1), ("fpts", "FPTS", 0)):
        recent = form["recent"][key]
        season_avg = form["season"][key]
        delta = recent - season_avg
        # Color only when the delta survives its own display rounding.
        threshold = 0.5 if digits == 0 else 0.05
        cls = "delta-up" if delta >= threshold else "delta-down" if delta <= -threshold else ""
        rows.append(
            f'<div class="vital-tile"><span>{esc(label)}</span>'
            f'<strong>{fmt_number(recent, digits)} <span class="{cls} small-copy">({fmt_signed(delta, digits)})</span></strong></div>'
        )
    trend = form["recent"]["fpts"] - form["season"]["fpts"]
    verdict = "Running hot" if trend > 4 else "Cold spell" if trend < -4 else "Steady"
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Form · Last {form["n"]} Games</h2><span class="muted small-copy" title="Last-five per-game averages; deltas vs full-season averages">{esc(verdict)}</span></div>
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


# ---------------------------------------------------------------------------
# Contract & injuries
# ---------------------------------------------------------------------------


def salary_history_html(player: dict[str, Any], season: int | None = None) -> str:
    """Contract card: season-by-season salary ledger (guaranteed years first,
    then history), with the first post-contract season shown as a muted UFA row."""
    cur_season = season if isinstance(season, int) else safe_int(season, 0) or None
    salaries = [s for s in player.get("salaries", []) if isinstance(s, dict) and isinstance(s.get("season"), int)]
    contract = player.get("contract") or {}
    exp = contract.get("exp") if isinstance(contract.get("exp"), int) else None
    amount = safe_float(contract.get("amount"))
    tid = safe_int(player.get("tid"), RETIRED_TID)
    rostered = tid >= 0

    by_season: dict[int, float] = {}
    for s in salaries:
        by_season[s["season"]] = safe_float(s.get("amount"))
    # Fill any guaranteed contract years the export didn't enumerate. Free
    # agents are skipped: their "contract" is an asking price, not money owed.
    if rostered and exp is not None and cur_season is not None and amount > 0:
        for s in range(cur_season, exp + 1):
            by_season.setdefault(s, amount)
    if not by_season:
        return ""

    rows = []
    # Guaranteed years first (newest at top), then the paid history. Notes only
    # apply to rostered players: an FA's future "salary" is nothing but an ask.
    for s in sorted(by_season, reverse=True):
        note = ""
        cls = ""
        if rostered and cur_season is not None and s > cur_season:
            note = '<span class="salary-note muted small-copy">guaranteed</span>'
            cls = "salary-future"
        elif rostered and cur_season is not None and s == cur_season:
            note = '<span class="salary-note muted small-copy">current</span>'
        rows.append(f'<tr class="{cls}">' + "".join([
            td(esc(s), sort=s),
            td(f"{fmt_money(by_season[s])} {note}", sort=by_season[s]),
        ]) + "</tr>")
    # The season after the last guaranteed year: no salary on the books -> UFA.
    if rostered and exp is not None:
        rows.insert(0, "<tr>" + "".join([
            td(esc(exp + 1), sort=exp + 1),
            td('<span class="muted salary-ufa">UFA</span>', sort=0),
        ]) + "</tr>")
    total = sum(by_season.values())
    rows.append(f'<tr class="total-row">{td("Total", cls="total-label")}{td(fmt_money(total), sort=total)}</tr>')
    subtitle = "incl. guaranteed years" if rostered else "career earnings"
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Salary</h2><span class="muted small-copy">{esc(subtitle)}</span></div>
      {table_html(["Season", "Salary"], rows, table_id=f"salary-{player.get('pid')}", empty_message="No salary data.", wrap_cls="fit-table")}
    </section>
    """


def contract_summary_html(player: dict[str, Any], season: int) -> str:
    contract = player.get("contract") or {}
    exp = contract.get("exp") if isinstance(contract.get("exp"), int) else None
    amount = safe_float(contract.get("amount"))
    tid = safe_int(player.get("tid"), RETIRED_TID)
    is_fa = tid == FREE_AGENT_TID
    rostered = tid >= 0

    tiles = []
    if is_fa:
        # Asking price comes from the free-agency board's salary model, not the
        # export's contract stub — the two must always agree.
        bid_k = fa_asking_price(player, season)
        tiles.append(
            f'<div class="vital-tile" title="One-year asking salary — same model as the Free Agency board">'
            f'<span>Asking price</span><strong>{fmt_money(bid_k)}/yr</strong></div>'
        )
    else:
        tiles.append(f'<div class="vital-tile"><span>Current deal</span><strong>{fmt_contract(player)}</strong></div>')
    if rostered and exp is not None and exp >= season and amount > 0:
        years = exp - season + 1
        tiles.append(f'<div class="vital-tile"><span>Guaranteed</span><strong>{years} yr · {fmt_money(amount * years)}</strong></div>')
        tiles.append(f'<div class="vital-tile"><span>Free agent</span><strong>{esc(exp + 1)}</strong></div>')
    elif is_fa:
        tiles.append('<div class="vital-tile"><span>Status</span><strong>Free agent</strong></div>')
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Contract</h2></div>
      <div class="vitals-row">{''.join(tiles)}</div>
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


# ---------------------------------------------------------------------------
# Rail + page assembly
# ---------------------------------------------------------------------------

RAIL_SECTIONS = [
    ("overview", "Overview"),
    ("stats", "Stats"),
    ("log", "Game Log"),
    ("ratings", "Ratings"),
    ("contract", "Contract & Injuries"),
]


def player_rail_html(available: set[str]) -> str:
    links = []
    for key, label in RAIL_SECTIONS:
        if key not in available:
            continue
        links.append(f'<a class="rail-link" href="#{key}">{esc(label)}</a>')
    return f'<nav class="player-rail" aria-label="Player sections" data-player-rail>{"".join(links)}</nav>'


def redirect_stub_html(player: dict[str, Any], anchor: str, label: str) -> str:
    """Tiny meta-refresh stub keeping an old sub-page URL alive."""
    slug = player_slug(player)
    target = f"{slug}.html#{anchor}"
    name = player_name(player)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url={esc(target)}">
  <link rel="canonical" href="{esc(slug)}.html">
  <title>{esc(name)} — {esc(label)} — SMP Basketball League</title>
</head>
<body>
  <p><a href="{esc(target)}">{esc(name)} — {esc(label)} has moved</a></p>
</body>
</html>
"""


def render_player_pages(player: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int, log_entries: list[dict[str, Any]] | None = None, data: dict[str, Any] | None = None) -> dict[str, str]:
    """Build the player's pages. Returns ``{suffix: html}``: suffix "" is the
    unified page; "-stats"/"-log"/"-ratings" are redirect stubs to its anchors.

    ``data`` (the full export) is optional: without it the shot-diet strip and
    led-league gold styling are skipped, everything else renders as usual."""
    teams_by_tid = {t["tid"]: t for t in teams}
    regular = regular_stats_since(player, start_season)
    playoffs = playoff_stats_since(player, start_season)
    logs = log_entries or []
    proj = _player_projection(player, season)
    led = _led_index(data)

    # Sections only appear when they would render content: the stat tables skip
    # seasons with no games and the game log skips 0-minute (DNP) appearances.
    available: set[str] = {"overview", "ratings", "contract"}
    if any(stat_gp(s) > 0 for s in regular):
        available.add("stats")
    if any(safe_float((e.get("box") or {}).get("min")) > 0 for e in logs):
        available.add("log")

    pid = player.get("pid")
    overview_sections = [
        player_bio_html(player, teams_by_tid, season),
        player_summary_rows(player, teams_by_tid, season, start_season),
        trophy_case_html(player),
        season_highs_html(player, logs, teams_by_tid, season, "../"),
        form_card_html(player, logs),
        development_chart_html(player, season, proj),
    ]
    body_parts = [
        trading_card_html(player, teams_by_tid, season, "../"),
        player_rail_html(available),
        f'<div class="player-section" id="overview">{"".join(overview_sections)}</div>',
    ]
    if "stats" in available:
        stats_sections = [
            per_game_table(player, regular, teams_by_tid, "../", "Per Game · Regular Season", f"regular-{pid}", led=led),
            shot_diet_html(player, data, start_season),
            shot_table(player, regular, teams_by_tid, "../", "Shot Locations and Feats · Regular Season", f"shots-{pid}", led=led),
            advanced_table(player, regular, teams_by_tid, "../", "Advanced · Regular Season", f"advanced-{pid}", led=led),
        ]
        if playoffs:
            stats_sections.append(per_game_table(player, playoffs, teams_by_tid, "../", "Per Game · Playoffs", f"playoffs-{pid}"))
            stats_sections.append(advanced_table(player, playoffs, teams_by_tid, "../", "Advanced · Playoffs", f"playoff-advanced-{pid}"))
        body_parts.append(f'<div class="player-section" id="stats">{"".join(stats_sections)}</div>')
    if "log" in available:
        log_sections = [
            game_log_table(player, logs, teams_by_tid, season, "../"),
            vs_opponent_table(player, logs, teams_by_tid, "../"),
        ]
        body_parts.append(f'<div class="player-section" id="log">{"".join(log_sections)}</div>')
    body_parts.append(f'<div class="player-section" id="ratings">{ratings_table(player, start_season)}</div>')
    contract_sections = [
        contract_summary_html(player, season),
        '<div class="history-row">' + salary_history_html(player, season) + injury_history_html(player) + "</div>",
    ]
    body_parts.append(f'<div class="player-section" id="contract">{"".join(contract_sections)}</div>')

    pages: dict[str, str] = {}
    pages[""] = page_html(player_name(player), "".join(body_parts), teams, root="../", active="players")
    pages["-stats"] = redirect_stub_html(player, "stats", "Stats")
    pages["-log"] = redirect_stub_html(player, "log", "Game Log")
    pages["-ratings"] = redirect_stub_html(player, "ratings", "Ratings")
    return pages
