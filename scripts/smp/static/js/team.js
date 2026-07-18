(function () {
  // ---------- team pages (W2): standalone module, appended after the core bundle ----------

  // show/hide 0-GP roster rows behind the "show inactive" toggle
  document.querySelectorAll('[data-toggle-inactive]').forEach((input) => {
    const card = input.closest('[data-roster-card]');
    if (!card) return;
    const apply = () => card.classList.toggle('show-inactive', input.checked);
    input.addEventListener('change', apply);
    apply();
  });

  // scoring-share metric toggle (PTS / FGA / AST)
  document.querySelectorAll('[data-share-card]').forEach((card) => {
    const buttons = Array.from(card.querySelectorAll('button[data-share-metric]'));
    const panels = Array.from(card.querySelectorAll('[data-share-panel]'));
    if (!buttons.length) return;
    function activate(button) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      panels.forEach((p) => { p.hidden = p.dataset.sharePanel !== button.dataset.shareMetric; });
    }
    buttons.forEach((button) => button.addEventListener('click', () => activate(button)));
  });

  // rotation river: hover readout synced with the rotation heat table
  document.querySelectorAll('[data-river]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.river-chart');
    const guide = wrap.querySelector('[data-river-guide]');
    const tip = wrap.querySelector('[data-river-tooltip]');
    const dataEl = document.getElementById(wrap.dataset.river);
    if (!svg || !guide || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const n = d.games.length;
    if (n < 2) return;
    const table = document.querySelector('[data-rotation-table="' + d.tid + '"]');
    const bands = Array.from(svg.querySelectorAll('.river-band'));
    const chips = Array.from(document.querySelectorAll('.river-chip[data-pid]'));

    const xs = (i) => g.ml + g.pw * i / (n - 1);

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function clearTable() {
      if (!table) return;
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      table.querySelectorAll('.row-hl').forEach((r) => r.classList.remove('row-hl'));
    }

    function highlightTable(gid, pid) {
      if (!table) return;
      clearTable();
      const th = table.querySelector('th[data-gid="' + gid + '"]');
      if (th) {
        const idx = th.cellIndex;
        table.querySelectorAll('tr').forEach((tr) => {
          const cell = tr.cells[idx];
          if (cell) cell.classList.add('col-hl');
        });
      }
      if (pid !== null) {
        const row = table.querySelector('tr[data-pid="' + pid + '"]');
        if (row) row.classList.add('row-hl');
      }
    }

    function highlightBand(pid) {
      bands.forEach((b) => b.classList.toggle('river-dim', pid !== null && Number(b.dataset.pid) !== pid));
      chips.forEach((c) => c.classList.toggle('active', Number(c.dataset.pid) === pid));
    }

    function hide() {
      tip.hidden = true;
      guide.style.display = 'none';
      highlightBand(null);
      clearTable();
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let i = Math.round((loc.x - g.ml) / g.pw * (n - 1));
      if (i < 0) i = 0;
      if (i > n - 1) i = n - 1;
      const game = d.games[i];
      // which band is under the cursor: invert y to minutes, walk the stack
      const mins = (g.mt + g.ph - loc.y) / g.ph * g.ymax;
      let pid = null;
      let name = '';
      let bandMin = 0;
      let cum = 0;
      for (let p = 0; p < d.players.length; p += 1) {
        cum += d.players[p].mins[i];
        if (mins <= cum) {
          pid = d.players[p].pid;
          name = d.players[p].name;
          bandMin = d.players[p].mins[i];
          break;
        }
      }
      guide.setAttribute('x1', xs(i));
      guide.setAttribute('x2', xs(i));
      guide.style.display = '';
      let html = '<strong>Day ' + game.day + ' ' + game.opp + '</strong><span>' + game.res + '</span>';
      if (pid !== null) html += '<span>' + name + ' — ' + Math.round(bandMin) + ' min</span>';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
      highlightBand(pid);
      highlightTable(game.gid, pid);
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);

    // reverse sync: hovering a game column header in the heat table moves the guide
    if (table) {
      table.addEventListener('mouseover', (evt) => {
        const th = evt.target.closest('th[data-gid]');
        if (!th || !table.contains(th)) return;
        const i = d.games.findIndex((game) => game.gid === th.dataset.gid);
        if (i < 0) return;
        guide.setAttribute('x1', xs(i));
        guide.setAttribute('x2', xs(i));
        guide.style.display = '';
      });
      table.addEventListener('mouseleave', () => { guide.style.display = 'none'; });
    }
  });
})();
