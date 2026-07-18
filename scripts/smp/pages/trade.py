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
    age,
    esc,
    fmt_money,
    fmt_number,
    heat_style,
    latest_rating,
    page_html,
    player_link,
    player_name,
    player_url,
    safe_float,
    safe_int,
    season_regular_stat,
    table_html,
    td,
    team_abbrev,
    team_dot,
    team_full_name,
    team_label,
    team_palette_by_tid,
    team_payroll,
)


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
