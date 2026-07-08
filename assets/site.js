(function () {
  function cellValue(row, index) {
    const cell = row.children[index];
    if (!cell) return "";
    return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
  }

  function compareValues(a, b) {
    const na = Number(a);
    const nb = Number(b);
    const aNumeric = a !== "" && Number.isFinite(na);
    const bNumeric = b !== "" && Number.isFinite(nb);
    if (aNumeric && bNumeric) return na - nb;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const caption = table.querySelector('caption');
    if (caption) table.setAttribute('aria-label', caption.textContent.trim());
    function activateSort(header, index) {
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const rows = Array.from(tbody.rows);
      const descending = header.classList.contains("sort-asc");
      headers.forEach((h) => {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      header.classList.add(descending ? "sort-desc" : "sort-asc");
      header.setAttribute("aria-sort", descending ? "descending" : "ascending");
      rows.sort((ra, rb) => {
        const result = compareValues(cellValue(ra, index), cellValue(rb, index));
        return descending ? -result : result;
      });
      rows.forEach((row) => tbody.appendChild(row));
    }
    headers.forEach((header, index) => {
      header.tabIndex = 0;
      header.setAttribute("aria-sort", "none");
      header.addEventListener("click", () => activateSort(header, index));
      header.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        activateSort(header, index);
      });
    });
  });

  document.querySelectorAll("[data-table-filter]").forEach((input) => {
    const table = document.getElementById(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", () => {
      const needle = input.value.trim().toLowerCase();
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
      });
    });
  });

  document.querySelectorAll('[data-pos-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.posFilter);
    if (!table || table.dataset.posCol === undefined) return;
    const col = Number(table.dataset.posCol);
    const apply = () => {
      const f = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const cell = row.cells[col];
        const pos = cell ? cell.textContent.trim() : '';
        // single-letter groups (G/F/C) match by substring; two-letter picks match exactly
        const match = f === 'all' || (f.length === 1 ? pos.indexOf(f) !== -1 : pos === f);
        row.classList.toggle('pos-hidden', !match);
      });
    };
    select.addEventListener('change', apply);
    apply();
  });
  document.querySelectorAll('[data-schedule-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.scheduleFilter);
    if (!table) return;
    const apply = () => {
      const value = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = value !== 'all' && row.dataset.scheduleTeam !== value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('[data-day-select]').forEach((select) => {
    const panels = Array.from(document.querySelectorAll('[data-day-panel]'));
    const apply = () => {
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.dayPanel !== select.value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('.click-row[data-href]').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.closest && target.closest('a')) return;
      window.location.href = row.dataset.href;
    });
  });

  document.querySelectorAll('[data-view-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.viewToggle);
    if (!table) return;
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        wrap.querySelectorAll('button').forEach((b) => {
          b.classList.remove('active');
          b.setAttribute('aria-pressed', 'false');
        });
        button.classList.add('active');
        button.setAttribute('aria-pressed', 'true');
        table.classList.remove('show-adv', 'show-p36', 'show-rate');
        if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      });
    });
  });

  document.querySelectorAll('[data-group-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.groupToggle);
    if (!table) return;
    const apply = () => {
      const active = new Set(
        Array.from(wrap.querySelectorAll('button.active')).map((b) => b.dataset.group)
      );
      Array.from(table.tBodies[0].rows).forEach((row) => {
        if (!row.dataset.group) return;
        row.classList.toggle('group-hidden', !active.has(row.dataset.group));
      });
    };
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        button.classList.toggle('active');
        button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
        apply();
      });
    });
    apply();
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('details.team-dropdown[open]').forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute('open');
    });
  });

  // ---------- player scatter chart ----------
  const chartCanvas = document.querySelector('[data-player-chart]');
  const chartDataEl = document.getElementById('player-chart-data');
  if (chartCanvas && chartDataEl) {
    const data = JSON.parse(chartDataEl.textContent);
    const labels = {};
    data.metrics.forEach((m) => { labels[m.key] = m.label; });
    const colors = {};
    data.teams.forEach((t) => { colors[t.abbrev] = t.color; });
    const hidden = new Set();
    const tooltip = document.querySelector('[data-chart-tooltip]');
    const legend = document.querySelector('[data-chart-legend]');
    const selX = document.querySelector('[data-chart-axis=\"x\"]');
    const selY = document.querySelector('[data-chart-axis=\"y\"]');
    const selPos = document.querySelector('[data-chart-pos]');
    const minMinInput = document.querySelector('[data-chart-minmin]');
    const minGpInput = document.querySelector('[data-chart-mingp]');
    const labelsInput = document.querySelector('[data-chart-labels]');
    let xKey = data.defaultX;
    let yKey = data.defaultY;
    let drawn = [];

    // restore state from URL hash: #x=usg&y=ts&pos=G&min=20&labels=1
    const hashParams = new URLSearchParams((location.hash || '').replace(/^#/, ''));
    const validKeys = new Set(data.metrics.map((m) => m.key));
    if (validKeys.has(hashParams.get('x'))) xKey = hashParams.get('x');
    if (validKeys.has(hashParams.get('y'))) yKey = hashParams.get('y');
    if (selX) selX.value = xKey;
    if (selY) selY.value = yKey;
    if (selPos && ['G', 'F', 'C'].includes(hashParams.get('pos'))) selPos.value = hashParams.get('pos');
    if (minMinInput && hashParams.get('min')) minMinInput.value = hashParams.get('min');
    if (minGpInput && hashParams.get('mingp')) minGpInput.value = hashParams.get('mingp');
    if (labelsInput && hashParams.get('labels') === '1') labelsInput.checked = true;

    function syncHash() {
      const params = new URLSearchParams();
      params.set('x', xKey);
      params.set('y', yKey);
      if (selPos && selPos.value !== 'all') params.set('pos', selPos.value);
      if (minMinInput && Number(minMinInput.value) > 0) params.set('min', minMinInput.value);
      if (minGpInput && Number(minGpInput.value) > 0) params.set('mingp', minGpInput.value);
      if (labelsInput && labelsInput.checked) params.set('labels', '1');
      history.replaceState(null, '', '#' + params.toString());
    }

    data.teams.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.setProperty('--dot', t.color);
      btn.setAttribute('aria-label', 'Toggle ' + t.abbrev + ' players');
      btn.setAttribute('aria-pressed', 'true');
      btn.innerHTML = '<span class=\"dot\"></span>' + t.abbrev;
      btn.addEventListener('click', () => {
        if (hidden.has(t.abbrev)) hidden.delete(t.abbrev); else hidden.add(t.abbrev);
        btn.classList.toggle('off', hidden.has(t.abbrev));
        btn.setAttribute('aria-pressed', hidden.has(t.abbrev) ? 'false' : 'true');
        draw();
      });
      legend.appendChild(btn);
    });

    function niceTicks(lo, hi, count) {
      const span = hi - lo || 1;
      const step0 = span / Math.max(1, count);
      const mag = Math.pow(10, Math.floor(Math.log10(step0)));
      const norm = step0 / mag;
      const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
      const ticks = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
      return { ticks, step };
    }

    function fmtTick(value, step) {
      const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
      return value.toFixed(digits);
    }

    function draw() {
      if (tooltip) tooltip.hidden = true;
      const dpr = window.devicePixelRatio || 1;
      const cw = chartCanvas.clientWidth;
      const ch = chartCanvas.clientHeight;
      chartCanvas.width = cw * dpr;
      chartCanvas.height = ch * dpr;
      const ctx = chartCanvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';

      const posFilter = selPos ? selPos.value : 'all';
      const minMin = minMinInput ? Number(minMinInput.value) || 0 : 0;
      const minGp = minGpInput ? Number(minGpInput.value) || 0 : 0;
      const pts = data.players.filter((p) =>
        !hidden.has(p.team)
        && Number.isFinite(p.v[xKey]) && Number.isFinite(p.v[yKey])
        && (posFilter === 'all' || (p.pos || '').includes(posFilter))
        && (!minMin || (Number.isFinite(p.v.min) && p.v.min >= minMin))
        && (!minGp || (Number.isFinite(p.v.gp) && p.v.gp >= minGp)));
      drawn = [];
      if (!pts.length) {
        ctx.fillStyle = '#939ca7';
        ctx.fillText('No data for this combination.', 16, 24);
        return;
      }
      let xLo = Math.min(...pts.map((p) => p.v[xKey]));
      let xHi = Math.max(...pts.map((p) => p.v[xKey]));
      let yLo = Math.min(...pts.map((p) => p.v[yKey]));
      let yHi = Math.max(...pts.map((p) => p.v[yKey]));
      const xPad = (xHi - xLo || 1) * 0.06;
      const yPad = (yHi - yLo || 1) * 0.08;
      xLo -= xPad; xHi += xPad; yLo -= yPad; yHi += yPad;

      const m = { left: 48, right: 14, top: 12, bottom: 34 };
      const plotW = cw - m.left - m.right;
      const plotH = ch - m.top - m.bottom;
      const px = (v) => m.left + ((v - xLo) / (xHi - xLo)) * plotW;
      const py = (v) => m.top + plotH - ((v - yLo) / (yHi - yLo)) * plotH;

      const xt = niceTicks(xLo, xHi, 8);
      const yt = niceTicks(yLo, yHi, 6);
      ctx.strokeStyle = 'rgba(255,255,255,.06)';
      ctx.fillStyle = '#939ca7';
      ctx.lineWidth = 1;
      xt.ticks.forEach((v) => {
        const x = px(v);
        ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke();
        ctx.textAlign = 'center';
        ctx.fillText(fmtTick(v, xt.step), x, m.top + plotH + 16);
      });
      yt.ticks.forEach((v) => {
        const y = py(v);
        ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke();
        ctx.textAlign = 'right';
        ctx.fillText(fmtTick(v, yt.step), m.left - 7, y + 3.5);
      });
      // zero lines
      ctx.strokeStyle = 'rgba(255,255,255,.22)';
      if (xLo < 0 && xHi > 0) { const x = px(0); ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke(); }
      if (yLo < 0 && yHi > 0) { const y = py(0); ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke(); }
      // axis labels
      ctx.fillStyle = '#c6cdd5';
      ctx.textAlign = 'center';
      ctx.fillText(labels[xKey] || xKey, m.left + plotW / 2, ch - 6);
      ctx.save();
      ctx.translate(12, m.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(labels[yKey] || yKey, 0, 0);
      ctx.restore();

      pts.forEach((p) => {
        const x = px(p.v[xKey]);
        const y = py(p.v[yKey]);
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.team] || '#939ca7';
        ctx.globalAlpha = 0.9;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = 'rgba(0,0,0,.5)';
        ctx.stroke();
        drawn.push({ x, y, p });
      });

      // optionally label the most extreme points on the current axes
      if (labelsInput && labelsInput.checked && pts.length) {
        const meanX = pts.reduce((s, p) => s + p.v[xKey], 0) / pts.length;
        const meanY = pts.reduce((s, p) => s + p.v[yKey], 0) / pts.length;
        const sdX = Math.sqrt(pts.reduce((s, p) => s + (p.v[xKey] - meanX) ** 2, 0) / pts.length) || 1;
        const sdY = Math.sqrt(pts.reduce((s, p) => s + (p.v[yKey] - meanY) ** 2, 0) / pts.length) || 1;
        const ranked = pts.slice().sort((a, b) =>
          (Math.abs((b.v[xKey] - meanX) / sdX) + Math.abs((b.v[yKey] - meanY) / sdY))
          - (Math.abs((a.v[xKey] - meanX) / sdX) + Math.abs((a.v[yKey] - meanY) / sdY)));
        ctx.fillStyle = '#c6cdd5';
        ctx.textAlign = 'left';
        ranked.slice(0, Math.min(14, ranked.length)).forEach((p) => {
          const lx = px(p.v[xKey]) + 7;
          const ly = py(p.v[yKey]) + 3;
          ctx.fillText(p.name.split(' ').slice(-1)[0], lx, ly);
        });
      }
    }

    function nearest(event) {
      const rect = chartCanvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      let best = null;
      let bestDist = 144;
      drawn.forEach((d) => {
        const dist = (d.x - mx) * (d.x - mx) + (d.y - my) * (d.y - my);
        if (dist < bestDist) { bestDist = dist; best = d; }
      });
      return best;
    }

    chartCanvas.addEventListener('mousemove', (event) => {
      const hit = nearest(event);
      if (!hit) { tooltip.hidden = true; chartCanvas.style.cursor = 'crosshair'; return; }
      chartCanvas.style.cursor = 'pointer';
      tooltip.innerHTML = '<strong>' + hit.p.name + ' · ' + hit.p.team + '</strong>'
        + '<span>' + (labels[xKey] || xKey) + ': ' + hit.p.v[xKey] + ' · '
        + (labels[yKey] || yKey) + ': ' + hit.p.v[yKey] + '</span>';
      tooltip.hidden = false;
      const wrapRect = chartCanvas.parentElement.getBoundingClientRect();
      const rect = chartCanvas.getBoundingClientRect();
      let left = hit.x + (rect.left - wrapRect.left) + 12;
      let top = hit.y + (rect.top - wrapRect.top) - 12;
      if (left + tooltip.offsetWidth > wrapRect.width - 4) left = left - tooltip.offsetWidth - 24;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    });
    chartCanvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });
    chartCanvas.addEventListener('click', (event) => {
      const hit = nearest(event);
      if (hit && hit.p.url) window.location.href = hit.p.url;
    });
    if (selX) selX.addEventListener('change', () => { xKey = selX.value; syncHash(); draw(); });
    if (selY) selY.addEventListener('change', () => { yKey = selY.value; syncHash(); draw(); });
    if (selPos) selPos.addEventListener('change', () => { syncHash(); draw(); });
    if (minMinInput) minMinInput.addEventListener('input', () => { syncHash(); draw(); });
    if (minGpInput) minGpInput.addEventListener('input', () => { syncHash(); draw(); });
    if (labelsInput) labelsInput.addEventListener('change', () => { syncHash(); draw(); });
    window.addEventListener('resize', draw);
    draw();
  }


  // ---------- schedule/h2h column hover ----------
  document.querySelectorAll('.schedule-grid, .h2h-grid').forEach((table) => {
    table.addEventListener('mouseover', (event) => {
      const cell = event.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      const idx = cell.cellIndex;
      if (idx > 0) {
        table.querySelectorAll('tr').forEach((tr) => {
          const target = tr.cells[idx];
          if (target) target.classList.add('col-hl');
        });
      }
    });
    table.addEventListener('mouseleave', () => {
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
    });
  });

  // ---------- global search ----------
  const searchInput = document.querySelector('[data-global-search]');
  const searchResults = document.querySelector('[data-search-results]');
  if (searchInput && searchResults) {
    const root = document.body.dataset.root || '';
    let index = null;
    let selected = -1;
    const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    function load() {
      if (index) return Promise.resolve(index);
      return fetch(root + 'assets/search-index.json')
        .then((r) => r.json())
        .then((data) => { index = data; return index; })
        .catch(() => ({ players: [], teams: [] }));
    }

    function close() {
      searchResults.hidden = true;
      selected = -1;
      searchInput.setAttribute('aria-expanded', 'false');
      searchInput.setAttribute('aria-activedescendant', '');
    }

    function syncSelected(links) {
      links.forEach((l, i) => {
        const on = i === selected;
        l.classList.toggle('selected', on);
        l.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      searchInput.setAttribute('aria-activedescendant', selected >= 0 && links[selected] ? links[selected].id : '');
    }

    function renderResults(matches) {
      if (!matches.length) {
        searchResults.innerHTML = '<div class="search-empty" role="option" aria-disabled="true">No matches.</div>';
        searchResults.hidden = false;
        searchInput.setAttribute('aria-expanded', 'true');
        searchInput.setAttribute('aria-activedescendant', '');
        return;
      }
      searchResults.innerHTML = matches.map((m, i) =>
        '<a id="search-option-' + i + '" role="option" aria-selected="false" href="' + root + escapeHtml(m.u) + '"><span>' + escapeHtml(m.n) + '</span><span class="muted">' + escapeHtml(m.t) + '</span></a>').join('');
      searchResults.hidden = false;
      searchInput.setAttribute('aria-expanded', 'true');
      selected = -1;
    }

    function update() {
      const q = norm(searchInput.value.trim());
      if (q.length < 2) { close(); return; }
      load().then((data) => {
        const score = (name) => {
          const n = norm(name);
          if (n.startsWith(q)) return 0;
          if (n.split(' ').some((w) => w.startsWith(q))) return 1;
          if (n.includes(q)) return 2;
          return -1;
        };
        const matches = [];
        (data.teams || []).forEach((t) => { const s = score(t.n); if (s >= 0) matches.push({ ...t, s: s - 0.5 }); });
        (data.players || []).forEach((p) => { const s = score(p.n); if (s >= 0) matches.push({ ...p, s }); });
        matches.sort((a, b) => a.s - b.s || a.n.localeCompare(b.n));
        renderResults(matches.slice(0, 8));
      });
    }

    searchInput.addEventListener('input', update);
    searchInput.addEventListener('focus', () => { load(); if (searchInput.value.trim().length >= 2) update(); });
    searchInput.addEventListener('keydown', (event) => {
      const links = Array.from(searchResults.querySelectorAll('a'));
      if (event.key === 'Escape') { close(); searchInput.blur(); return; }
      if (!links.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, links.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = links[Math.max(0, selected)];
        if (target) window.location.href = target.href;
        return;
      } else { return; }
      syncSelected(links);
    });
    document.addEventListener('click', (event) => {
      if (!searchInput.contains(event.target) && !searchResults.contains(event.target)) close();
    });
  }

  // ---------- copy table as TSV ----------
  document.querySelectorAll('.table-wrap').forEach((wrap) => {
    const table = wrap.querySelector('table');
    if (!table || !navigator.clipboard) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-table';
    btn.title = 'Copy table for spreadsheets';
    btn.setAttribute('aria-label', 'Copy table for spreadsheets');
    btn.textContent = '⧉';
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      const lines = Array.from(table.querySelectorAll('tr')).map((tr) =>
        Array.from(tr.cells).map((cell) => cell.textContent.trim().replace(/\s+/g, ' ')).join('\t'));
      navigator.clipboard.writeText(lines.join('\n')).then(() => {
        btn.textContent = '✓';
        btn.setAttribute('aria-label', 'Copied table');
        setTimeout(() => {
          btn.textContent = '⧉';
          btn.setAttribute('aria-label', 'Copy table for spreadsheets');
        }, 1200);
      });
    });
    wrap.appendChild(btn);
  });

  // ---------- mobile nav toggle ----------
  const burger = document.querySelector('[data-nav-burger]');
  if (burger) {
    const nav = document.getElementById(burger.getAttribute('aria-controls')) || document.querySelector('.primary-nav');
    burger.addEventListener('click', () => {
      if (!nav) return;
      const open = !nav.classList.contains('open');
      nav.classList.toggle('open', open);
      burger.classList.toggle('open');
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || !nav || !nav.classList.contains('open')) return;
      nav.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    });
  }

  // ---------- generic tabs ----------
  document.querySelectorAll('[data-tabs]').forEach((tablist) => {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"][data-tab-target]'));
    if (!tabs.length) return;
    function activate(tab, focus) {
      tabs.forEach((btn) => {
        const on = btn === tab;
        const panel = document.getElementById(btn.dataset.tabTarget || '');
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', () => activate(tab, false));
      tab.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
        if (event.key === 'Home') next = tabs[0];
        if (event.key === 'End') next = tabs[tabs.length - 1];
        if (!next) return;
        event.preventDefault();
        activate(next, true);
      });
    });
    activate(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0], false);
  });

  // ---------- draft year tabs ----------
  const draftTabs = document.querySelector('[data-draft-tabs]');
  if (draftTabs) {
    const buttons = Array.from(draftTabs.querySelectorAll('button[data-draft-tab]'));
    function activateDraft(button, focus) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      });
      document.querySelectorAll('[data-draft-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.draftPanel !== button.dataset.draftTab;
      });
      if (focus) button.focus();
    }
    buttons.forEach((button, index) => {
      button.tabIndex = button.classList.contains('active') ? 0 : -1;
      button.addEventListener('click', () => {
        activateDraft(button, false);
      });
      button.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = buttons[(index + 1) % buttons.length];
        if (event.key === 'ArrowLeft') next = buttons[(index - 1 + buttons.length) % buttons.length];
        if (event.key === 'Home') next = buttons[0];
        if (event.key === 'End') next = buttons[buttons.length - 1];
        if (!next) return;
        event.preventDefault();
        activateDraft(next, true);
      });
    });
    if (buttons.length) activateDraft(buttons.find((b) => b.classList.contains('active')) || buttons[0], false);
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

  // ---------- player development projection charts (interactive hover) ----------
  document.querySelectorAll('[data-proj-chart]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.proj-chart');
    const tip = wrap.querySelector('[data-proj-tooltip]');
    const hLine = wrap.querySelector('[data-proj-hover-line]');
    const hDot = wrap.querySelector('[data-proj-hover-dot]');
    const dataEl = wrap.parentElement &&
      wrap.parentElement.querySelector('script[type="application/json"][id^="proj-data-"]');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (v - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(v);

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() {
      tip.hidden = true;
      hLine.style.display = 'none';
      hDot.style.display = 'none';
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const hi = d.hist.s.indexOf(season);
      const pi = d.proj.s.indexOf(season);
      let markY = null;
      let html = '';
      if (season <= d.cur && hi >= 0) {
        markY = d.hist.ovr[hi];
        html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
               '<span>Overall ' + fmt(d.hist.ovr[hi]) + ' · Potential ' + fmt(d.hist.pot[hi]) + '</span>';
        if (season === d.cur && pi >= 0) html += '<span>Projection starts here</span>';
      } else if (pi >= 0) {
        markY = d.proj.p50[pi];
        html = '<strong>' + season + ' · projected</strong>' +
               '<span>Median ' + fmt(d.proj.p50[pi]) + ' · 80% ' +
               fmt(d.proj.p10[pi]) + '–' + fmt(d.proj.p90[pi]) + '</span>' +
               '<span>50% ' + fmt(d.proj.p25[pi]) + '–' + fmt(d.proj.p75[pi]) + '</span>';
      } else {
        hide();
        return;
      }
      const cx = xs(season);
      hLine.setAttribute('x1', cx);
      hLine.setAttribute('x2', cx);
      hLine.style.display = '';
      hDot.setAttribute('cx', cx);
      hDot.setAttribute('cy', yv(markY));
      hDot.style.display = '';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;  // flip left
      if (left + tw > rect.width) left = rect.width - tw - 4;                // still over: pin right
      if (left < 0) left = 4;                                               // never off the left
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // subrating grid hover-sync: one scrubber drives all 15 mini-charts.
  document.querySelectorAll('[data-subrating-grid]').forEach((grid) => {
    const pid = grid.getAttribute('data-subg-pid');
    const dataEl = grid.parentElement &&
      grid.parentElement.querySelector('script[id="subrating-data-' + pid + '"]');
    if (!dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const sSpan = Math.max(1, d.smax - d.smin);
    const xs = (s) => g.ml + (s - d.smin) / sSpan * g.pw;

    const cells = [];
    grid.querySelectorAll('.subg-cell[data-subg-key]').forEach((cell) => {
      const key = cell.getAttribute('data-subg-key');
      const chart = d.charts[key];
      if (!chart) return;
      cells.push({
        cell: cell,
        chart: chart,
        svg: cell.querySelector('svg.subg-svg'),
        hline: cell.querySelector('.subg-hline'),
        hdot: cell.querySelector('.subg-hdot'),
        valEl: cell.querySelector('[data-subg-val]'),
        capEl: cell.querySelector('[data-subg-cap]'),
        curVal: cell.querySelector('[data-subg-val]')
          ? cell.querySelector('[data-subg-val]').textContent : ''
      });
    });
    if (!cells.length) return;

    function yv(v, lo, hi) {
      return g.mt + g.ph - (v - lo) / Math.max(1e-9, hi - lo) * g.ph;
    }

    function seasonFromEvent(svg, evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const loc = pt.matrixTransform(ctm.inverse());
      let season = Math.round(d.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < d.smin) season = d.smin;
      if (season > d.smax) season = d.smax;
      return season;
    }

    function clear() {
      cells.forEach((c) => {
        c.cell.classList.remove('subg-active');
        if (c.hline) c.hline.style.display = 'none';
        if (c.hdot) c.hdot.style.display = 'none';
        if (c.valEl) c.valEl.textContent = c.curVal;
        if (c.capEl) c.capEl.textContent = 'now';
      });
    }

    function sync(season) {
      const cx = xs(season);
      const future = season > d.cur;
      cells.forEach((c) => {
        const ch = c.chart;
        let v = null;
        if (season <= d.cur) {
          const hi = ch.hist.s.indexOf(season);
          if (hi >= 0) v = ch.hist.v[hi];
        } else {
          const pi = ch.proj.s.indexOf(season);
          if (pi >= 0) v = ch.proj.p50[pi];
        }
        if (v === null) {
          c.cell.classList.remove('subg-active');
          if (c.hline) c.hline.style.display = 'none';
          if (c.hdot) c.hdot.style.display = 'none';
          if (c.valEl) c.valEl.textContent = c.curVal;
          if (c.capEl) c.capEl.textContent = 'now';
          return;
        }
        c.cell.classList.add('subg-active');
        const cy = yv(v, ch.g.lo, ch.g.hi);
        if (c.hline) {
          c.hline.setAttribute('x1', cx);
          c.hline.setAttribute('x2', cx);
          c.hline.style.display = '';
        }
        if (c.hdot) {
          c.hdot.setAttribute('cx', cx);
          c.hdot.setAttribute('cy', cy);
          c.hdot.style.display = '';
        }
        if (c.valEl) c.valEl.textContent = Math.round(v);
        if (c.capEl) c.capEl.textContent = season + (future ? ' · proj' : (season === d.cur ? ' · now' : ''));
      });
    }

    cells.forEach((c) => {
      if (!c.svg) return;
      c.svg.addEventListener('mousemove', (evt) => {
        const s = seasonFromEvent(c.svg, evt);
        if (s !== null) sync(s);
      });
    });
    grid.addEventListener('mouseleave', clear);
  });

  // ---------- team trajectory (projected team strength fan chart) ----------
  document.querySelectorAll('[data-team-traj]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.ttraj-chart');
    const tip = wrap.querySelector('[data-ttraj-tooltip]');
    const hLine = wrap.querySelector('[data-ttraj-hover-line]');
    const hDot = wrap.querySelector('[data-ttraj-hover-dot]');
    const bandsG = wrap.querySelector('[data-ttraj-bands]');
    const lineG = wrap.querySelector('[data-ttraj-line]');
    const tid = wrap.getAttribute('data-ttraj-tid');
    const root = wrap.closest('section') || wrap.parentElement;
    const dataEl = document.getElementById('team-traj-' + tid);
    if (!svg || !tip || !dataEl || !bandsG || !lineG || !root) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const SVGNS = 'http://www.w3.org/2000/svg';
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (Math.max(0, v) - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(Math.max(0, v));
    let active = 'proj';

    function bandPts(upper, lower) {
      const fwd = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(upper[i]).toFixed(1));
      const back = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(lower[i]).toFixed(1)).reverse();
      return fwd.concat(back).join(' ');
    }
    function linePts(p50) {
      return d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(p50[i]).toFixed(1)).join(' ');
    }

    function draw(scn) {
      const b = d.scn[scn];
      if (!b) return;
      active = scn;
      bandsG.innerHTML = '';
      const p80 = document.createElementNS(SVGNS, 'polygon');
      p80.setAttribute('points', bandPts(b.p90, b.p10));
      p80.setAttribute('class', 'ttraj-band-80');
      const p50b = document.createElementNS(SVGNS, 'polygon');
      p50b.setAttribute('points', bandPts(b.p75, b.p25));
      p50b.setAttribute('class', 'ttraj-band-50');
      bandsG.appendChild(p80); bandsG.appendChild(p50b);
      lineG.innerHTML = '';
      const ml = document.createElementNS(SVGNS, 'polyline');
      ml.setAttribute('points', linePts(b.p50));
      ml.setAttribute('class', 'ttraj-median');
      lineG.appendChild(ml);
    }

    function updateWindow(scn) {
      const out = root.querySelector('[data-ttraj-window] strong');
      if (!out || d.contender == null) return;
      const p50 = d.scn[scn].p50;
      const hit = [];
      d.seasons.forEach((s, i) => { if (p50[i] >= d.contender) hit.push(s); });
      let txt = 'none in window';
      if (hit.length) {
        const run = [hit[0]];
        for (let i = 1; i < hit.length; i++) {
          if (hit[i] === run[run.length - 1] + 1) run.push(hit[i]); else break;
        }
        txt = run[0] === run[run.length - 1] ? '' + run[0] : run[0] + '–' + run[run.length - 1];
      }
      out.textContent = txt;
    }

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() { tip.hidden = true; hLine.style.display = 'none'; hDot.style.display = 'none'; }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const i = d.seasons.indexOf(season);
      if (i < 0) { hide(); return; }
      const b = d.scn[active];
      const med = b.p50[i];
      const cx = xs(season);
      hLine.setAttribute('x1', cx); hLine.setAttribute('x2', cx); hLine.style.display = '';
      hDot.setAttribute('cx', cx); hDot.setAttribute('cy', yv(med)); hDot.style.display = '';
      const cnt = (d.counts && d.counts[i] != null) ? d.counts[i] : null;
      let html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
        '<span>' + (d.labels[active] || active) + '</span>' +
        '<span>Median ' + fmt(med) + ' · 80% ' + fmt(b.p10[i]) + '–' + fmt(b.p90[i]) + '</span>';
      if (cnt != null) html += '<span>' + cnt + ' under contract</span>';
      tip.innerHTML = html; tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    root.querySelectorAll('.ttraj-btn[data-ttraj-scn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const scn = btn.getAttribute('data-ttraj-scn');
        if (!d.scn[scn]) return;
        root.querySelectorAll('.ttraj-btn').forEach((b2) => {
          const on = b2 === btn;
          b2.classList.toggle('active', on);
          b2.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        draw(scn);
        updateWindow(scn);
        hide();
      });
    });

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // power ranking bump: hover/highlight a team line + tooltip, dim the rest.
  document.querySelectorAll('[data-bump]').forEach((wrap) => {
    const card = wrap.closest('.bump-card') || wrap;
    const svg = wrap.querySelector('svg.bump-chart');
    const tip = wrap.querySelector('[data-bump-tooltip]');
    const dataEl = document.getElementById('bump-data');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const n = (d.seasons || []).length;
    const byId = {};
    (d.teams || []).forEach((t) => { byId[String(t.tid)] = t; });

    const groups = Array.from(card.querySelectorAll('.bump-team[data-tid]'));
    const labels = Array.from(card.querySelectorAll('.bump-endlabel[data-tid]'));
    const chips = Array.from(card.querySelectorAll('.bump-chip[data-tid]'));
    if (!groups.length) return;

    function setActive(tid) {
      tid = String(tid);
      card.classList.add('bump-has-active');
      const apply = (el) => {
        const on = String(el.getAttribute('data-tid')) === tid;
        el.classList.toggle('is-active', on);
        el.classList.toggle('is-dim', !on);
        if (el.matches && el.matches('.bump-chip')) el.setAttribute('aria-pressed', on ? 'true' : 'false');
      };
      groups.forEach(apply); labels.forEach(apply); chips.forEach(apply);
    }
    function clear() {
      card.classList.remove('bump-has-active');
      [].concat(groups, labels, chips).forEach((el) => el.classList.remove('is-active', 'is-dim'));
      chips.forEach((el) => el.setAttribute('aria-pressed', 'false'));
      tip.hidden = true;
    }

    function seasonIndex(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm || n < 2) return 0;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const loc = pt.matrixTransform(ctm.inverse());
      let i = Math.round((loc.x - g.ml) / (g.pw / (n - 1)));
      return Math.max(0, Math.min(n - 1, i));
    }

    function showTip(tid, i, evt) {
      const t = byId[String(tid)];
      if (!t) return;
      // abbrev comes from league data; escape it before innerHTML (defense-in-depth).
      const escHtml = (s) => String(s).replace(/[&<>"]/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      const games = (t.games && t.games[i] != null) ? t.games[i] : 0;
      const wins = (t.rec && t.rec[i] != null) ? t.rec[i] : 0;
      let html = '<strong>' + escHtml(t.abbrev || '') + ' · ' + d.seasons[i] +
        (i === 0 ? ' · now' : '') + '</strong>' +
        '<span>Rank #' + t.ranks[i] + ' of ' + d.rows + '</span>' +
        '<span>Strength ' + Math.round(t.p50[i]) + '</span>';
      if (games > 0) html += '<span>Est. ' + wins + '–' + Math.max(0, games - wins) + '</span>';
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
    }

    groups.forEach((grp) => {
      const tid = grp.getAttribute('data-tid');
      grp.addEventListener('mouseenter', () => setActive(tid));
      grp.addEventListener('mousemove', (e) => { setActive(tid); showTip(tid, seasonIndex(e), e); });
    });
    labels.forEach((l) => l.addEventListener('mouseenter', () => setActive(l.getAttribute('data-tid'))));
    chips.forEach((c) => {
      const tid = c.getAttribute('data-tid');
      c.addEventListener('mouseenter', () => setActive(tid));
      c.addEventListener('focus', () => setActive(tid));
      c.addEventListener('click', () => setActive(tid));
    });
    card.addEventListener('mouseleave', clear);
  });

})();
