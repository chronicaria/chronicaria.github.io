  // ---------- trade machine (consumes window.SMPApps from compare.js) ----------
(function () {
  'use strict';

  let bootTries = 0;
  function boot() {
    const machine = document.querySelector('[data-app="trade"]');
    if (!machine) return;
    const A = window.SMPApps;
    if (!A) {
      // compare.js should precede this file in the bundle; one deferred retry
      // keeps a wrong concat order from silently killing the page.
      if (bootTries++ < 3) setTimeout(boot, 0);
      return;
    }

    const extraEl = document.getElementById('trade-extra');
    const picksByTid = (extraEl ? JSON.parse(extraEl.textContent) : { picks: {} }).picks || {};
    const summary = document.querySelector('[data-trade-summary]');
    const sides = [0, 1].map((i) => ({
      comboEl: document.querySelector('[data-trade-combo="' + i + '"]'),
      filterEl: document.querySelector('[data-trade-filter="' + i + '"]'),
      listEl: document.querySelector('[data-trade-list="' + i + '"]'),
      tid: null,
      picked: new Set(),
      pickedPicks: new Set(),
      filter: '',
    }));

    A.loadAppData().then((data) => init(data)).catch(() => {
      const msg = '<p class="app-error">Couldn’t load roster data (assets/app-data.json). Check your connection and refresh to retry.</p>';
      sides.forEach((side) => { side.listEl.innerHTML = msg; });
      if (summary) summary.innerHTML = '';
    });

    function init(data) {
      const esc = A.escapeHtml;
      const fmtM = A.fmtSalary;
      const teamsSorted = data.teams.slice().sort((a, b) => a.abbrev.localeCompare(b.abbrev));
      const teamsByTid = {};
      data.teams.forEach((t) => { teamsByTid[t.tid] = t; });
      const rostersByTid = {};
      data.players.forEach((p) => {
        if (p.tid >= 0) (rostersByTid[p.tid] = rostersByTid[p.tid] || []).push(p);
      });
      Object.keys(rostersByTid).forEach((tid) => {
        rostersByTid[tid].sort((a, b) => (b.salary - a.salary) || a.name.localeCompare(b.name) || (a.pid - b.pid));
      });
      const tax = data.finance.tax_line;
      const fullName = (t) => (t.region ? t.region + ' ' : '') + t.name;

      const comboOptions = teamsSorted.map((t) => ({
        id: t.tid,
        label: t.abbrev + ' — ' + fullName(t),
        search: [t.abbrev, fullName(t)],
      }));
      const optionByTid = {};
      comboOptions.forEach((o) => { optionByTid[o.id] = o; });

      const combos = sides.map((side, index) => A.createCombobox(side.comboEl, {
        options: () => comboOptions,
        onSelect: (tid) => {
          side.tid = tid;
          side.picked.clear();
          side.pickedPicks.clear();
          side.filter = '';
          side.filterEl.value = '';
          renderSide(index);
          syncHash();
          renderSummary();
        },
      }));

      // Initial state: the URL hash when present (a/b = tids, ap/bp = picked
      // pids, ak/bk = picked dpids), else the first two teams by abbrev.
      const params = new URLSearchParams((location.hash || '').replace(/^#/, ''));
      const defaults = [teamsSorted[0], teamsSorted[1]];
      sides.forEach((side, index) => {
        const key = index === 0 ? 'a' : 'b';
        const fromHash = parseInt(params.get(key), 10);
        side.tid = teamsByTid[fromHash] ? fromHash : (defaults[index] ? defaults[index].tid : null);
        const roster = rostersByTid[side.tid] || [];
        const pids = new Set(roster.map((p) => p.pid));
        (params.get(key + 'p') || '').split('.').forEach((pid) => {
          const num = parseInt(pid, 10);
          if (pids.has(num)) side.picked.add(num);
        });
        const dpids = new Set((picksByTid[String(side.tid)] || []).map((pick) => pick.id));
        (params.get(key + 'k') || '').split('.').forEach((id) => {
          const num = parseInt(id, 10);
          if (dpids.has(num)) side.pickedPicks.add(num);
        });
        combos[index].setSelection(side.tid !== null ? optionByTid[side.tid] : null);
        combos[index].enable();
        side.filterEl.disabled = false;
        side.filterEl.addEventListener('input', () => {
          side.filter = A.norm(side.filterEl.value.trim());
          renderSide(index);
        });
      });

      function syncHash() {
        const params = new URLSearchParams();
        let dirty = false;
        sides.forEach((side, index) => {
          const key = index === 0 ? 'a' : 'b';
          params.set(key, side.tid);
          if (side.picked.size) { params.set(key + 'p', Array.from(side.picked).sort((x, y) => x - y).join('.')); dirty = true; }
          if (side.pickedPicks.size) { params.set(key + 'k', Array.from(side.pickedPicks).sort((x, y) => x - y).join('.')); dirty = true; }
          if (!defaults[index] || side.tid !== defaults[index].tid) dirty = true;
        });
        if (!dirty && !location.hash) return; // untouched default state: keep the URL clean
        history.replaceState(null, '', '#' + params.toString());
      }

      function renderSide(index) {
        const side = sides[index];
        const team = teamsByTid[side.tid];
        if (!team) { side.listEl.innerHTML = '<p class="muted">Pick a team.</p>'; return; }
        side.listEl.innerHTML = '';
        let shown = 0;
        (rostersByTid[side.tid] || []).forEach((p) => {
          if (side.filter && !A.norm(p.name).includes(side.filter)) return;
          shown += 1;
          const row = document.createElement('label');
          row.className = 'trade-row';
          row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + esc(p.name) + '</span>'
            + '<span class="muted">' + esc(p.pos) + ' · ' + (p.age === null ? '—' : p.age + 'y') + ' · ' + p.ovr + ' ovr</span>'
            + '<span class="trade-amt">' + fmtM(p.salary) + '/' + (p.exp === null ? '—' : p.exp) + '</span>'
            + '<span class="trade-val">' + (p.value === null ? '—' : p.value) + '</span>';
          const box = row.querySelector('input');
          box.checked = side.picked.has(p.pid);
          box.setAttribute('aria-label', 'Trade ' + p.name);
          box.addEventListener('change', () => {
            if (box.checked) side.picked.add(p.pid); else side.picked.delete(p.pid);
            syncHash();
            renderSummary();
          });
          side.listEl.appendChild(row);
        });
        (picksByTid[String(side.tid)] || []).forEach((pick) => {
          if (side.filter && !A.norm(pick.label).includes(side.filter)) return;
          shown += 1;
          const row = document.createElement('label');
          row.className = 'trade-row trade-pick';
          row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + esc(pick.label) + '</span><span class="muted">draft pick</span><span class="trade-amt"></span><span class="trade-val">—</span>';
          const box = row.querySelector('input');
          box.checked = side.pickedPicks.has(pick.id);
          box.setAttribute('aria-label', 'Trade ' + pick.label + ' draft pick');
          box.addEventListener('change', () => {
            if (box.checked) side.pickedPicks.add(pick.id); else side.pickedPicks.delete(pick.id);
            syncHash();
            renderSummary();
          });
          side.listEl.appendChild(row);
        });
        if (!shown) {
          side.listEl.innerHTML = '<p class="empty-state">No assets match the filter.</p>';
        }
      }

      function sideAssets(side) {
        const team = teamsByTid[side.tid];
        const players = (rostersByTid[side.tid] || []).filter((p) => side.picked.has(p.pid));
        const picks = (picksByTid[String(side.tid)] || []).filter((pick) => side.pickedPicks.has(pick.id));
        const salary = players.reduce((s, p) => s + p.salary, 0);
        const value = players.reduce((s, p) => s + (p.value || 0), 0);
        return { team, players, picks, salary, value };
      }

      function taxReadout(team, salaryOut, salaryIn) {
        const before = team.payroll;
        const after = before - salaryOut + salaryIn;
        const scale = Math.max(tax * 1.15, before, after);
        const over = after > tax;
        const room = tax - after;
        const note = over
          ? fmtM(-room) + ' over the ' + fmtM(tax) + ' tax line'
          : fmtM(room) + ' under the ' + fmtM(tax) + ' tax line';
        return '<div class="tfin-team' + (over ? ' tfin-team--over' : '') + '">'
          + '<div class="tfin-head"><strong>' + esc(team.abbrev) + '</strong>'
          + '<span class="tfin-nums">' + fmtM(before) + ' → <strong>' + fmtM(after) + '</strong></span></div>'
          + '<div class="tfin-bar"><i class="tfin-fill" style="width:' + Math.min(100, (after / scale) * 100).toFixed(1) + '%"></i>'
          + '<span class="tfin-tick" style="left:' + ((tax / scale) * 100).toFixed(1) + '%"></span></div>'
          + '<div class="tfin-note' + (over ? ' tfin-note--over' : '') + '">' + note + '</div>'
          + '</div>';
      }

      function renderSummary() {
        const a = sideAssets(sides[0]);
        const b = sideAssets(sides[1]);
        if (!a.team || !b.team) { summary.innerHTML = '<p class="muted">Pick two teams.</p>'; return; }
        if (a.team.tid === b.team.tid) {
          summary.innerHTML = '<p class="muted">Pick two different teams.</p>';
          return;
        }
        const diff = a.value - b.value;
        let verdict = 'Even value trade.';
        if (Math.abs(diff) > 1) {
          const winner = diff > 0 ? b.team.abbrev : a.team.abbrev;
          verdict = winner + ' wins this trade by ' + Math.abs(Math.round(diff * 10) / 10) + ' value' + (a.picks.length || b.picks.length ? ' (draft picks not valued)' : '');
        }
        const lines = [];
        const describe = (from, to) => {
          const bits = from.players.map((p) => esc(p.name)).concat(from.picks.map((pick) => esc(pick.label)));
          return '<p><strong>' + esc(from.team.abbrev) + ' → ' + esc(to.team.abbrev) + ':</strong> ' + (bits.join(', ') || '<span class="muted">nothing</span>')
            + ' <span class="muted">(salary ' + fmtM(from.salary) + ', value ' + (Math.round(from.value * 10) / 10) + ')</span></p>';
        };
        lines.push(describe(a, b));
        lines.push(describe(b, a));
        lines.push('<div class="tfin">' + taxReadout(a.team, a.salary, b.salary) + taxReadout(b.team, b.salary, a.salary) + '</div>');
        lines.push('<p class="trade-verdict">' + verdict + '</p>');
        summary.innerHTML = lines.join('');
      }

      renderSide(0);
      renderSide(1);
      renderSummary();
    }
  }

  boot();
})();
