from __future__ import annotations

"""Compare Players page.

The page is a thin server-rendered shell; the client (static/js/compare.js)
fetches assets/app-data.json (built by smp.appdata every build) for the shared
player pool — names, ratings, per-game stats, contracts, team colors — instead
of this page embedding its own giant JSON payload.

Only the handful of stats app-data does not carry (GP, TS%, PER, BPM, WS for
the comparison table) ship as a compact per-pid supplement embedded here,
alongside the RATING_LABELS ordering so client row labels stay in sync with
core.py.

Radar spokes (rendered client-side, 6 spokes from the 15 subratings —
keep in sync with the SPOKES table in static/js/compare.js):

    Shooting     = mean(tp, fg, ft)          three pointers, mid range, free throws
    Finishing    = mean(ins, dnk)            inside scoring, dunks/layups
    Athleticism  = mean(spd, jmp, stre, endu)
    Playmaking   = mean(pss, drb, oiq)
    Defense      = mean(diq, reb, hgt)
    IQ           = mean(oiq, diq)

oiq/diq intentionally contribute to two spokes each (playmaking/defense and
IQ): the IQ spoke isolates feel-for-the-game, while playmaking/defense fold it
into the broader skill.
"""

import json
from typing import Any

from ..core import (
    RATING_LABELS,
    draft_prospects,
    latest_regular_stat,
    page_html,
    safe_float,
    stat_gp,
    ts_pct,
)


def compare_extras_payload(data: dict[str, Any], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    """Compact JSON supplement: stats app-data.json does not carry.

    ``stats`` maps pid -> [GP, TS%, PER, BPM, WS] (this season's regular-season
    row, matching appdata's latest_regular_stat selection); ``ratingKeys``
    carries the RATING_LABELS ordering so the client table matches core.py.
    """
    stats: dict[str, list[Any]] = {}
    for p in players + draft_prospects(data):
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        ts = ts_pct(stat)
        stats[str(p.get("pid"))] = [
            int(gp),
            round(ts, 1) if ts is not None else None,
            round(safe_float(stat.get("per")), 1),
            round(safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm")), 1),
            round(safe_float(stat.get("ows")) + safe_float(stat.get("dws")), 1),
        ]
    payload = {
        "ratingKeys": [[key, label] for key, label in RATING_LABELS.items()],
        "stats": stats,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def _combo_slot(index: int, label: str) -> str:
    return f"""
        <div class="combo-slot">
          <label class="select-label combo-label" for="cmp-combo-{index}">{label}</label>
          <div class="combo" data-compare-combo="{index}">
            <input id="cmp-combo-{index}" type="text" class="combo-input" role="combobox"
              aria-autocomplete="list" aria-expanded="false" aria-controls="cmp-combo-list-{index}"
              aria-activedescendant="" autocomplete="off" autocapitalize="off" spellcheck="false"
              placeholder="Type a player…" disabled>
            <div class="combo-list" id="cmp-combo-list-{index}" role="listbox" aria-label="{label} matches" hidden></div>
          </div>
        </div>"""


def render_compare_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, start_season: int) -> str:
    extras = compare_extras_payload(data, players, season, start_season)
    slots = "".join(_combo_slot(i, f"Player {i + 1}") for i in range(3))
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Compare Players</h1>
        <p class="muted">Pick two or three players · best value in each row is highlighted · share the URL to share the comparison</p>
      </div>
    </section>
    <section class="card" data-app="compare">
      <div class="toolbar compare-toolbar">{slots}
      </div>
      <div class="radar-block" data-compare-radar hidden>
        <div data-radar-out></div>
        <p class="muted small-copy radar-note">Spokes average the 15 subratings — Shooting: 3PT · Mid · FT&ensp;·&ensp;Finishing: Inside · Dunks&ensp;·&ensp;Athleticism: Speed · Jump · Strength · Endurance&ensp;·&ensp;Playmaking: Passing · Dribbling · Off IQ&ensp;·&ensp;Defense: Def IQ · Rebounding · Height&ensp;·&ensp;IQ: Off IQ · Def IQ</p>
      </div>
      <div data-compare-out aria-live="polite">
        <p class="app-loading">Loading player data…</p>
      </div>
      <noscript><p class="empty-state">The player comparison tool needs JavaScript.</p></noscript>
    </section>
    <script type="application/json" id="compare-extra">{extras}</script>
    """
    return page_html("Compare Players", body, teams, root="", active="players")
