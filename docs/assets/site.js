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

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = table.querySelectorAll("thead th");
    headers.forEach((header, index) => {
      header.addEventListener("click", () => {
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.rows);
        const descending = header.classList.contains("sort-asc");
        headers.forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
        header.classList.add(descending ? "sort-desc" : "sort-asc");
        rows.sort((ra, rb) => {
          const result = compareValues(cellValue(ra, index), cellValue(rb, index));
          return descending ? -result : result;
        });
        rows.forEach((row) => tbody.appendChild(row));
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
      button.addEventListener('click', () => {
        wrap.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
        button.classList.add('active');
        table.classList.remove('show-adv', 'show-p36');
        if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      });
    });
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
    if (labelsInput && hashParams.get('labels') === '1') labelsInput.checked = true;

    function syncHash() {
      const params = new URLSearchParams();
      params.set('x', xKey);
      params.set('y', yKey);
      if (selPos && selPos.value !== 'all') params.set('pos', selPos.value);
      if (minMinInput && Number(minMinInput.value) > 0) params.set('min', minMinInput.value);
      if (labelsInput && labelsInput.checked) params.set('labels', '1');
      history.replaceState(null, '', '#' + params.toString());
    }

    data.teams.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.setProperty('--dot', t.color);
      btn.innerHTML = '<span class=\"dot\"></span>' + t.abbrev;
      btn.addEventListener('click', () => {
        if (hidden.has(t.abbrev)) hidden.delete(t.abbrev); else hidden.add(t.abbrev);
        btn.classList.toggle('off', hidden.has(t.abbrev));
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
      const pts = data.players.filter((p) =>
        !hidden.has(p.team)
        && Number.isFinite(p.v[xKey]) && Number.isFinite(p.v[yKey])
        && (posFilter === 'all' || (p.pos || '').includes(posFilter))
        && (!minMin || (Number.isFinite(p.v.min) && p.v.min >= minMin)));
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

    function close() { searchResults.hidden = true; selected = -1; }

    function renderResults(matches) {
      if (!matches.length) {
        searchResults.innerHTML = '<div class="search-empty">No matches.</div>';
        searchResults.hidden = false;
        return;
      }
      searchResults.innerHTML = matches.map((m) =>
        '<a href="' + root + m.u + '"><span>' + m.n + '</span><span class="muted">' + m.t + '</span></a>').join('');
      searchResults.hidden = false;
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
      links.forEach((l, i) => l.classList.toggle('selected', i === selected));
    });
    document.addEventListener('click', (event) => {
      if (!searchInput.contains(event.target) && !searchResults.contains(event.target)) close();
    });
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

  // ---------- favorite team ----------
  const FAV_KEY = 'smp-fav-tid';
  const favTid = localStorage.getItem(FAV_KEY);
  document.querySelectorAll('[data-fav-team]').forEach((btn) => {
    const tid = btn.dataset.favTeam;
    const sync = () => btn.classList.toggle('active', localStorage.getItem(FAV_KEY) === tid);
    sync();
    btn.addEventListener('click', () => {
      const current = localStorage.getItem(FAV_KEY);
      if (current === tid) localStorage.removeItem(FAV_KEY);
      else localStorage.setItem(FAV_KEY, tid);
      sync();
      applyFavorite();
    });
  });

  function applyFavorite() {
    const fav = localStorage.getItem(FAV_KEY);
    document.querySelectorAll('.fav-row').forEach((el) => el.classList.remove('fav-row'));
    document.querySelectorAll('.fav-pin').forEach((el) => el.remove());
    if (!fav) return;
    document.querySelectorAll('tr[data-tid="' + fav + '"], th[data-tid="' + fav + '"]').forEach((el) => el.classList.add('fav-row'));
    const menuLink = document.querySelector('.team-menu a[data-tid="' + fav + '"]');
    const nav = document.querySelector('.primary-nav');
    if (menuLink && nav) {
      const pin = document.createElement('a');
      pin.href = menuLink.href;
      pin.textContent = menuLink.dataset.abbrev || menuLink.textContent;
      pin.className = 'fav-pin' + (menuLink.classList.contains('active') ? ' active' : '');
      nav.insertBefore(pin, nav.firstElementChild);
    }
  }
  applyFavorite();

})();
