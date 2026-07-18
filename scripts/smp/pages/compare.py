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
    DRAFT_PROSPECT_TID,
    RATING_LABELS,
    age,
    draft_prospects,
    fmt_money,
    latest_rating,
    latest_regular_stat,
    page_html,
    per_game,
    player_name,
    player_url,
    safe_float,
    safe_int,
    stat_gp,
    team_abbrev_for_tid,
    total_rebounds,
    ts_pct,
)


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
