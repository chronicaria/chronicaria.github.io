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
    let hoverPt = null;

    // Theme-aware palette, resolved at draw time so light/dark both render true.
    function chartTheme() {
      const rootStyle = getComputedStyle(document.documentElement);
      const cssVar = (name, fallback) => (rootStyle.getPropertyValue(name) || '').trim() || fallback;
      return {
        line: cssVar('--line', '#2b313a'),
        muted: cssVar('--muted', '#939ca7'),
        text: cssVar('--text', '#e8ecf1'),
        accent: cssVar('--accent', '#5b9dff'),
        bg: getComputedStyle(chartCanvas).backgroundColor || '#171b21',
      };
    }

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

    // Dot radius scales gently with minutes: rotation players read larger.
    function dotRadius(p) {
      const min = Number.isFinite(p.v.min) ? p.v.min : 24;
      return 2.8 + 2.1 * Math.min(1, Math.max(0, min / 38));
    }

    function draw() {
      const theme = chartTheme();
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
        if (tooltip) tooltip.hidden = true;
        hoverPt = null;
        ctx.fillStyle = theme.muted;
        ctx.fillText('No data for this combination.', 16, 24);
        return;
      }
      if (hoverPt && pts.indexOf(hoverPt.p) === -1) hoverPt = null;
      let xLo = Math.min(...pts.map((p) => p.v[xKey]));
      let xHi = Math.max(...pts.map((p) => p.v[xKey]));
      let yLo = Math.min(...pts.map((p) => p.v[yKey]));
      let yHi = Math.max(...pts.map((p) => p.v[yKey]));
      const xPad = (xHi - xLo || 1) * 0.06;
      const yPad = (yHi - yLo || 1) * 0.08;
      xLo -= xPad; xHi += xPad; yLo -= yPad; yHi += yPad;

      const m = { left: 52, right: 16, top: 14, bottom: 40 };
      const plotW = cw - m.left - m.right;
      const plotH = ch - m.top - m.bottom;
      const px = (v) => m.left + ((v - xLo) / (xHi - xLo)) * plotW;
      const py = (v) => m.top + plotH - ((v - yLo) / (yHi - yLo)) * plotH;

      // Horizontal gridlines only; the x-axis gets small tick marks instead.
      const xt = niceTicks(xLo, xHi, 8);
      const yt = niceTicks(yLo, yHi, 6);
      ctx.lineWidth = 1;
      ctx.strokeStyle = theme.line;
      ctx.fillStyle = theme.muted;
      yt.ticks.forEach((v) => {
        const y = py(v);
        ctx.globalAlpha = 0.5;
        ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.textAlign = 'right';
        ctx.fillText(fmtTick(v, yt.step), m.left - 8, y + 3.5);
      });
      xt.ticks.forEach((v) => {
        const x = px(v);
        ctx.beginPath(); ctx.moveTo(x, m.top + plotH); ctx.lineTo(x, m.top + plotH + 5); ctx.stroke();
        ctx.textAlign = 'center';
        ctx.fillText(fmtTick(v, xt.step), x, m.top + plotH + 17);
      });
      // axis baselines
      ctx.strokeStyle = theme.line;
      ctx.beginPath();
      ctx.moveTo(m.left, m.top);
      ctx.lineTo(m.left, m.top + plotH);
      ctx.lineTo(m.left + plotW, m.top + plotH);
      ctx.stroke();
      // dashed zero lines when the range crosses zero
      ctx.strokeStyle = theme.muted;
      ctx.globalAlpha = 0.55;
      ctx.setLineDash([4, 4]);
      if (xLo < 0 && xHi > 0) { const x = px(0); ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke(); }
      if (yLo < 0 && yHi > 0) { const y = py(0); ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      // axis labels
      ctx.fillStyle = theme.text;
      ctx.textAlign = 'center';
      ctx.font = '600 11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
      ctx.fillText(labels[xKey] || xKey, m.left + plotW / 2, ch - 8);
      ctx.save();
      ctx.translate(13, m.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(labels[yKey] || yKey, 0, 0);
      ctx.restore();
      ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';

      pts.forEach((p) => {
        const x = px(p.v[xKey]);
        const y = py(p.v[yKey]);
        const r = dotRadius(p);
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.team] || theme.muted;
        ctx.globalAlpha = hoverPt && hoverPt.p !== p ? 0.55 : 0.95;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1;
        ctx.strokeStyle = theme.bg;
        ctx.stroke();
        drawn.push({ x, y, p });
      });

      // label every visible point (overlap allowed)
      if (labelsInput && labelsInput.checked) {
        ctx.fillStyle = theme.muted;
        ctx.textAlign = 'left';
        ctx.font = '10px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
        pts.forEach((p) => {
          if (hoverPt && hoverPt.p === p) return;
          ctx.fillText(p.name.split(' ').slice(-1)[0], px(p.v[xKey]) + dotRadius(p) + 3.5, py(p.v[yKey]) + 3);
        });
        ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
      }

      // hovered point: full-strength dot with a halo ring and its name
      if (hoverPt) {
        const x = px(hoverPt.p.v[xKey]);
        const y = py(hoverPt.p.v[yKey]);
        const r = dotRadius(hoverPt.p);
        ctx.beginPath();
        ctx.arc(x, y, r + 1, 0, Math.PI * 2);
        ctx.fillStyle = colors[hoverPt.p.team] || theme.muted;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = theme.bg;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, y, r + 4.5, 0, Math.PI * 2);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = theme.text;
        ctx.globalAlpha = 0.7;
        ctx.stroke();
        ctx.globalAlpha = 1;
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
      if ((hit && hit.p) !== (hoverPt && hoverPt.p)) {
        hoverPt = hit;
        draw();
      }
      if (!hit) { tooltip.hidden = true; chartCanvas.style.cursor = 'crosshair'; return; }
      chartCanvas.style.cursor = 'pointer';
      const dotColor = colors[hit.p.team] || '';
      tooltip.innerHTML = '<strong><span class=\"tip-dot\" style=\"--dot:' + dotColor + '\"></span>'
        + hit.p.name + ' <span class=\"tip-team\">' + hit.p.team + (hit.p.pos ? ' · ' + hit.p.pos : '') + '</span></strong>'
        + '<span>' + (labels[xKey] || xKey) + ' <b>' + hit.p.v[xKey] + '</b> · '
        + (labels[yKey] || yKey) + ' <b>' + hit.p.v[yKey] + '</b></span>';
      tooltip.hidden = false;
      const wrapRect = chartCanvas.parentElement.getBoundingClientRect();
      const rect = chartCanvas.getBoundingClientRect();
      let left = hit.x + (rect.left - wrapRect.left) + 14;
      let top = hit.y + (rect.top - wrapRect.top) - 14;
      if (left + tooltip.offsetWidth > wrapRect.width - 4) left = left - tooltip.offsetWidth - 28;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    });
    chartCanvas.addEventListener('mouseleave', () => {
      tooltip.hidden = true;
      if (hoverPt) { hoverPt = null; draw(); }
    });
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
    // repaint when the theme toggle stamps html[data-theme]
    new MutationObserver(() => draw()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    draw();
  }

