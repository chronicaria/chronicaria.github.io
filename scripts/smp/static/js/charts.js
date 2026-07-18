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
