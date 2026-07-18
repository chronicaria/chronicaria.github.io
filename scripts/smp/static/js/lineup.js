// ---------- Lineup Lab (lineup.html) ----------
// Self-contained IIFE: appended after the main site bundle's closing wrapper,
// so it guards on its own root element and no-ops on every other page.
(function () {
  const app = document.querySelector('[data-lineup-app]');
  if (!app) return;
  const root = document.body.dataset.root || '';

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  // Faithful JS port of scripts/projections.py team_ovr (regular-season branch),
  // itself a port of zengm team/ovr.basketball.ts with numPlayersOnCourt == 5:
  // sort OVRs descending, take the top 10, pad to 10 with 0.0, then
  //   predictedMOV = -OVR_K + sum_i OVR_A * exp(OVR_B * i) * ovr[i]
  //   raw = predictedMOV * 50 / 15 + 50, displayed rounded half-up.
  // tests/test_tools_pages.py regenerates these constants from projections.py
  // and asserts this formula matches projections.team_ovr on known groups.
  const OVR_A = 0.3334;
  const OVR_B = -0.1609;
  const OVR_K = 102.98;
  function teamOvrRaw(ovrs) {
    const top = ovrs.map(Number).sort((a, b) => b - a).slice(0, 10);
    while (top.length < 10) top.push(0);
    let mov = -OVR_K;
    for (let i = 0; i < 10; i += 1) mov += OVR_A * Math.exp(OVR_B * i) * top[i];
    return mov * 50 / 15 + 50;
  }
  const roundOvr = (raw) => Math.floor(raw + 0.5); // Math.round, like Python's floor(x+.5)
  // ADAPTATION for a hand-picked group: team_ovr rates a full roster, so a bare
  // five would drag five literal 0.0 bench slots into the weighting and every
  // lineup would grade absurdly negative. Instead the missing roster spots are
  // filled with app-data.sim.bench_ovrs — the league-average 6th..10th-best OVR
  // across the ten current rosters (5 floats, sorted desc) — i.e. your five
  // plus a league-average bench. The weighting itself is untouched:
  // lineupOvrRaw(five) is exactly projections.team_ovr(five + bench_ovrs).
  // Safety net for a stale app-data.json without bench_ovrs: pad with
  // simmodel.REPLACEMENT_OVR (40.0), the repo's "freely-available filler"
  // constant, which tests assert against projections.team_ovr.
  const REPLACEMENT_OVR = 40.0;
  let benchOvrs = null; // payload.sim.bench_ovrs when present, else null
  function benchAt(i) {
    return benchOvrs && Number.isFinite(benchOvrs[i]) ? benchOvrs[i] : REPLACEMENT_OVR;
  }
  function lineupOvrRaw(ovrs) {
    const padded = ovrs.slice(0, 10);
    for (let i = 0; padded.length < 10; i += 1) padded.push(benchAt(i));
    return teamOvrRaw(padded);
  }
  // team_ovr anchors its scale to scoring margin (raw = MOV * 50/15 + 50), so the
  // inverse maps a rating back to predicted margin. A custom five has no MOV
  // history, so BOTH matchup sides are rated this same way (five vs top-ten
  // roster) and the margin gap feeds the payload's logistic model — the exact
  // win-probability curve simulate_league uses (see simmodel.sim_client_inputs).
  const ovrToMov = (raw) => (raw - 50) * 15 / 50;

  // YIQ text-on-color pick (presentational only; server pages get the audited
  // on_primary from identity.py — app-data carries primary/secondary only).
  function textOn(hex) {
    let c = String(hex || '').replace('#', '');
    if (c.length === 3) c = c.split('').map((x) => x + x).join('');
    const n = parseInt(c, 16);
    if (!Number.isFinite(n)) return '#e8ecf1';
    const yiq = (((n >> 16) & 255) * 299 + (((n >> 8) & 255)) * 587 + (n & 255) * 114) / 1000;
    return yiq >= 140 ? '#101317' : '#e8ecf1';
  }

  const fmtMoney = (thousands) => '$' + (thousands / 1000).toFixed(1) + 'M';
  const fmtPct = (p) => (p * 100).toFixed(1) + '%';

  const slots = [null, null, null, null, null]; // pid or null per slot
  const inputs = Array.from(app.querySelectorAll('[data-ll-input]'));
  const summaryEl = app.querySelector('[data-ll-summary]');
  const matchupsEl = app.querySelector('[data-ll-matchups]');

  let payload = null;
  let byPid = {};
  let byTid = {};

  function teamChip(tid) {
    const team = byTid[tid];
    if (!team) {
      const label = tid === -2 ? 'Draft' : 'FA';
      return '<span class="team-chip ll-chip ll-chip-neutral">' + label + '</span>';
    }
    const c = team.colors || {};
    const style = '--team-primary:' + escapeHtml(c.primary || '#39424f')
      + ';--team-secondary:' + escapeHtml(c.secondary || '#8899aa')
      + ';--team-on-primary:' + escapeHtml(textOn(c.primary || '#39424f'));
    return '<span class="team-chip ll-chip" style="' + style + '"><span class="team-chip-dot"></span>'
      + escapeHtml(team.abbrev) + '</span>';
  }

  function optionLabel(p) {
    const team = byTid[p.tid];
    const t = team ? team.abbrev : (p.tid === -2 ? 'Draft' : 'FA');
    return t + ' · ' + p.pos + ' · ' + p.ovr + ' ovr';
  }

  // --- filterable combobox per slot (ARIA pattern modeled on search.js) ------
  function comboFor(input) {
    const slot = Number(input.dataset.slot);
    const list = document.getElementById(input.getAttribute('aria-controls'));
    const clearBtn = app.querySelector('[data-ll-clear][data-slot="' + slot + '"]');
    let selected = -1;

    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }

    function syncSelected(options) {
      options.forEach((o, i) => {
        const on = i === selected;
        o.classList.toggle('selected', on);
        o.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      input.setAttribute('aria-activedescendant', selected >= 0 && options[selected] ? options[selected].id : '');
    }

    function matches() {
      if (!payload) return [];
      const q = norm(input.value.trim());
      const taken = new Set(slots.filter((pid, i) => pid !== null && i !== slot));
      const pool = payload.players.filter((p) => !taken.has(p.pid));
      if (!q) return pool.slice(0, 12); // payload is sorted by ovr desc
      const score = (name) => {
        const n = norm(name);
        if (n.startsWith(q)) return 0;
        if (n.split(' ').some((w) => w.startsWith(q))) return 1;
        if (n.includes(q)) return 2;
        return -1;
      };
      const found = [];
      pool.forEach((p) => {
        const s = score(p.name);
        if (s >= 0) found.push([s, p]);
      });
      found.sort((a, b) => a[0] - b[0] || b[1].ovr - a[1].ovr || a[1].name.localeCompare(b[1].name));
      return found.slice(0, 12).map((f) => f[1]);
    }

    function open() {
      const found = matches();
      if (!found.length) {
        list.innerHTML = '<div class="search-empty" role="option" aria-disabled="true">No matches.</div>';
      } else {
        list.innerHTML = found.map((p, i) =>
          '<button type="button" class="ll-option" id="ll-opt-' + slot + '-' + i + '" role="option" aria-selected="false" data-pid="' + p.pid + '">'
          + '<span>' + escapeHtml(p.name) + '</span><span class="muted">' + escapeHtml(optionLabel(p)) + '</span></button>').join('');
      }
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
      input.setAttribute('aria-activedescendant', '');
    }

    function pickPid(pid) {
      slots[slot] = pid;
      if (byPid[pid]) input.value = byPid[pid].name; // even while focused (renderPicks skips the active input)
      close();
      syncHash();
      render();
    }

    input.addEventListener('input', open);
    input.addEventListener('focus', () => { if (payload) open(); });
    input.addEventListener('keydown', (event) => {
      const options = Array.from(list.querySelectorAll('[role="option"][data-pid]'));
      if (event.key === 'Escape') { close(); return; }
      if (event.key === 'ArrowDown' && list.hidden) { event.preventDefault(); open(); return; }
      if (!options.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, options.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = options[Math.max(0, selected)];
        if (target) pickPid(Number(target.dataset.pid));
        return;
      } else { return; }
      syncSelected(options);
    });
    list.addEventListener('click', (event) => {
      const option = event.target.closest('[data-pid]');
      if (option) pickPid(Number(option.dataset.pid));
    });
    document.addEventListener('click', (event) => {
      if (!input.contains(event.target) && !list.contains(event.target)) close();
    });
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        slots[slot] = null;
        input.value = '';
        syncHash();
        render();
        input.focus();
      });
    }
  }

  // --- shareable state: pids comma-joined in the hash (slot order kept) ------
  function syncHash() {
    const pids = slots.filter((pid) => pid !== null);
    history.replaceState(null, '', pids.length ? '#' + pids.join(',') : location.pathname + location.search);
  }

  function readHash() {
    const parts = (location.hash || '').replace(/^#/, '').split(',').filter(Boolean);
    parts.slice(0, 5).forEach((raw, i) => {
      const pid = Number(raw);
      if (byPid[pid]) slots[i] = pid;
    });
  }

  // --- rendering -------------------------------------------------------------
  function renderPicks() {
    slots.forEach((pid, i) => {
      const pickEl = app.querySelector('[data-ll-pick="' + i + '"]');
      const clearBtn = app.querySelector('[data-ll-clear][data-slot="' + i + '"]');
      const p = pid !== null ? byPid[pid] : null;
      if (!p) {
        pickEl.innerHTML = '<span class="muted">Empty slot</span>';
        if (clearBtn) clearBtn.hidden = true;
        return;
      }
      if (inputs[i] && document.activeElement !== inputs[i]) inputs[i].value = p.name;
      pickEl.innerHTML = teamChip(p.tid)
        + ' <span class="ll-pick-meta">' + escapeHtml(p.pos) + ' · <strong>' + p.ovr + '</strong> ovr · '
        + escapeHtml(fmtMoney(p.salary)) + (p.exp ? ' thru ' + p.exp : '') + '</span>';
      if (clearBtn) clearBtn.hidden = false;
    });
  }

  function renderSummary(picked, matchupRows) {
    const count = picked.length;
    const ovrs = picked.map((p) => p.ovr);
    const ovr = count ? roundOvr(lineupOvrRaw(ovrs)) : null;
    const salary = picked.reduce((sum, p) => sum + (p.salary || 0), 0);
    const taxLine = payload.finance.tax_line;
    const overTax = salary > taxLine;
    const gap = Math.abs(salary - taxLine);
    let avgWin = null;
    if (matchupRows.length) {
      avgWin = matchupRows.reduce((sum, r) => sum + (r.home + r.away) / 2, 0) / matchupRows.length;
    }
    const tile = (label, value, sub, cls) =>
      '<div class="ll-tile' + (cls ? ' ' + cls : '') + '"><span class="ll-tile-label">' + label + '</span>'
      + '<strong>' + value + '</strong><span class="muted">' + sub + '</span></div>';
    const benchLabel = benchOvrs ? 'a league-average bench' : 'a replacement-level bench';
    summaryEl.innerHTML = '<div class="ll-tiles">'
      + tile('Lineup OVR', ovr === null ? '—' : String(ovr),
             (count === 5 ? 'your five' : count + ' of 5 picked') + ' + ' + benchLabel, '')
      + tile('Total salary', fmtMoney(salary),
             fmtMoney(gap) + (overTax ? ' over' : ' under') + ' the ' + fmtMoney(taxLine) + ' tax line',
             overTax ? 'll-over-tax' : '')
      + tile('Average win %', avgWin === null ? '—' : fmtPct(avgWin),
             avgWin === null ? 'pick five players' : 'home/road average vs all ' + matchupRows.length + ' rosters', '')
      + '</div>';
  }

  function matchupData(picked) {
    if (picked.length < 5 || !payload) return [];
    const k = payload.sim.logistic_k;
    const hca = payload.sim.hca;
    const mine = ovrToMov(lineupOvrRaw(picked.map((p) => p.ovr)));
    return payload.teams.map((team) => {
      const roster = payload.players.filter((p) => p.tid === team.tid);
      const raw = teamOvrRaw(roster.map((p) => p.ovr));
      const diff = mine - ovrToMov(raw);
      return {
        team: team,
        ovr: roundOvr(raw),
        home: 1 / (1 + Math.exp(-(diff + hca) * k)),
        away: 1 / (1 + Math.exp(-(diff - hca) * k)),
      };
    }).sort((a, b) => b.ovr - a.ovr || a.team.tid - b.team.tid);
  }

  function renderMatchups(rows) {
    if (!rows.length) {
      matchupsEl.innerHTML = '<p class="muted">Pick five players to see the matchup board.</p>';
      return;
    }
    const bar = (p) => '<span class="ll-bar" aria-hidden="true"><i style="width:'
      + Math.max(2, Math.min(100, p * 100)).toFixed(1) + '%"></i></span>';
    let html = '<div class="table-wrap"><table class="ll-table">'
      + '<caption class="sr-only">Projected win probability for your lineup against each roster</caption>'
      + '<thead><tr><th scope="col">Opponent</th><th scope="col">Their OVR</th>'
      + '<th scope="col">Win % at home</th><th scope="col">Win % on road</th></tr></thead><tbody>';
    rows.forEach((r) => {
      html += '<tr><td>' + teamChip(r.team.tid) + ' <span class="ll-opp-name">'
        + escapeHtml(r.team.region + ' ' + r.team.name) + '</span></td>'
        + '<td>' + r.ovr + '</td>'
        + '<td>' + bar(r.home) + ' ' + fmtPct(r.home) + '</td>'
        + '<td>' + bar(r.away) + ' ' + fmtPct(r.away) + '</td></tr>';
    });
    html += '</tbody></table></div>';
    matchupsEl.innerHTML = html;
  }

  function render() {
    if (!payload) return;
    renderPicks();
    const picked = slots.filter((pid) => pid !== null).map((pid) => byPid[pid]);
    const rows = matchupData(picked);
    renderSummary(picked, rows);
    renderMatchups(rows);
  }

  fetch(root + 'assets/app-data.json')
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((data) => {
      payload = data;
      const bench = data.sim && data.sim.bench_ovrs;
      if (Array.isArray(bench) && bench.length === 5 && bench.every((v) => Number.isFinite(v))) {
        benchOvrs = bench;
      }
      data.players.forEach((p) => { byPid[p.pid] = p; });
      data.teams.forEach((t) => { byTid[t.tid] = t; });
      inputs.forEach(comboFor);
      readHash();
      render();
    })
    .catch(() => {
      summaryEl.innerHTML = '<p class="muted">Could not load player data (assets/app-data.json). Reload to try again.</p>';
    });
})();
