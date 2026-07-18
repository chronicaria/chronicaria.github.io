  // ---------- home page: playoff-odds river hover crosshair ----------
  document.querySelectorAll('[data-oddsr]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.oddsr-chart');
    const tip = wrap.querySelector('[data-oddsr-tooltip]');
    const hLine = wrap.querySelector('[data-oddsr-hline]');
    const dataEl = wrap.parentElement &&
      wrap.parentElement.querySelector('script[type="application/json"]#oddsr-data');
    if (!svg || !tip || !hLine || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    if (!g || g.n < 2) return;
    const xs = (i) => g.ml + g.pw * i / (g.n - 1);

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
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let i = Math.round((loc.x - g.ml) / g.pw * (g.n - 1));
      if (i < 0) i = 0;
      if (i > g.n - 1) i = g.n - 1;
      const rows = d.teams
        .map((t) => ({ ab: t.ab, color: t.color, po: t.po[i] }))
        .filter((t) => t.po !== null && t.po !== undefined)
        .sort((a, b) => b.po - a.po);
      if (!rows.length) { hide(); return; }
      let html = '<strong>' + escapeHtml(d.names[i] || d.labels[i] || '') + '</strong>';
      rows.forEach((t) => {
        html += '<span class="oddsr-tip-row">' +
          '<span class="oddsr-tip-dot" style="background:' + escapeHtml(t.color) + '"></span>' +
          escapeHtml(t.ab) +
          '<span class="oddsr-tip-val">' + Math.round(t.po) + '%</span></span>';
      });
      const cx = xs(i);
      hLine.setAttribute('x1', cx);
      hLine.setAttribute('x2', cx);
      hLine.style.display = '';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;  // flip left
      if (left + tw > rect.width) left = rect.width - tw - 4;                // still over: pin right
      if (left < 0) left = 4;                                               // never off the left
      tip.style.left = left + 'px';
      let top = evt.clientY - rect.top + 12;
      if (top + tip.offsetHeight > rect.height) top = Math.max(4, rect.height - tip.offsetHeight - 4);
      tip.style.top = top + 'px';
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

