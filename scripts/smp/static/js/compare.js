  // ---------- client apps: shared helpers + Compare page ----------
  // compare.js owns window.SMPApps (app-data loader, combobox, portraits) and
  // must be concatenated BEFORE trade-extras.js, which consumes it.
(function () {
  'use strict';

  const rootPath = () => (document.body && document.body.dataset.root) || '';

  let appDataPromise = null;
  function loadAppData() {
    if (!appDataPromise) {
      appDataPromise = fetch(rootPath() + 'assets/app-data.json').then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }
    return appDataPromise;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  const norm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  // Mirrors core.fmt_money: thousands in, "$28M" / "$27.55M" / "$500K" out.
  function fmtSalary(k) {
    const num = Number(k);
    if (k === null || k === undefined || !Number.isFinite(num)) return '—';
    const sign = num < 0 ? '-' : '';
    const mag = Math.abs(num);
    if (mag >= 1000) {
      const millions = mag / 1000;
      if (Math.abs(millions - Math.round(millions)) < 1e-9) return sign + '$' + Math.round(millions) + 'M';
      return sign + '$' + millions.toFixed(2).replace(/0+$/, '').replace(/\.$/, '') + 'M';
    }
    return sign + '$' + Math.round(mag) + 'K';
  }

  // Mirrors core.slugify + player_url for the ASCII/diacritic names in play.
  function playerUrl(p) {
    let slug = String(p.name || '').normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '').replace(/[^\x00-\x7F]/g, '')
      .trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return rootPath() + 'players/' + (slug || 'player') + '-' + p.pid + '.html';
  }

  function teamAbbrevFor(tid, teamsByTid) {
    if (tid >= 0 && teamsByTid[tid]) return teamsByTid[tid].abbrev;
    return tid === -2 ? 'Draft' : 'FA';
  }

  const NEUTRAL_COLORS = { primary: '#3a4048', secondary: '#8a93a0', chart: '#8A93A5' };

  function teamColors(tid, teamsByTid) {
    return (tid >= 0 && teamsByTid[tid] && teamsByTid[tid].colors) || NEUTRAL_COLORS;
  }

  // WCAG-ish text-on-disc pick: white or near-black, whichever contrasts more
  // (mirrors identity._pick_on_color; app-data colors carry no on_primary).
  function onColor(bg) {
    const c = bg.replace('#', '');
    const chan = (i) => {
      const s = parseInt(c.slice(i, i + 2), 16) / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    const lum = 0.2126 * chan(0) + 0.7152 * chan(2) + 0.0722 * chan(4);
    return (1.05 / (lum + 0.05)) >= ((lum + 0.05) / 0.0565) ? '#FFFFFF' : '#10131A';
  }

  function initialsOf(name) {
    const parts = String(name || '').trim().split(/\s+/);
    const letters = (parts[0] ? parts[0][0] : '') + (parts.length > 1 ? parts[parts.length - 1][0] : '');
    return (letters || '?').toUpperCase();
  }

  // Mirrors identity.monogram_svg with literal colors (client has no --team-* vars).
  function monogramSvg(text, colors) {
    const t = String(text || '?').slice(0, 3).toUpperCase();
    const font = { 1: 26, 2: 22, 3: 17 }[t.length] || 17;
    return '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'
      + '<circle cx="32" cy="32" r="31" fill="' + colors.primary + '"/>'
      + '<circle cx="32" cy="32" r="28.5" fill="none" stroke="' + colors.secondary + '" stroke-width="2"/>'
      + '<text x="32" y="33.5" text-anchor="middle" dominant-baseline="central" '
      + 'font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif" font-weight="700" '
      + 'font-size="' + font + '" letter-spacing=".5" fill="' + onColor(colors.primary) + '">'
      + escapeHtml(t) + '</text></svg>';
  }

  // Portrait chip chain for client apps: face SVG asset -> monogram roundel.
  // (Photos/imgURL are not in app-data; the onerror hook keeps it unbreakable.)
  function hydrateFaces(container, byPid, teamsByTid) {
    container.querySelectorAll('[data-face-pid]').forEach((span) => {
      const p = byPid[span.dataset.facePid];
      if (!p) return;
      const colors = teamColors(p.tid, teamsByTid);
      const size = parseInt(span.dataset.faceSize || '24', 10);
      const img = document.createElement('img');
      img.src = rootPath() + 'assets/faces/' + p.pid + '.svg';
      img.alt = '';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.width = size;
      img.height = size;
      img.onerror = () => { span.innerHTML = monogramSvg(initialsOf(p.name), colors); };
      span.appendChild(img);
    });
  }

  function facePlaceholder(pid, size) {
    return '<span class="app-face" data-face-pid="' + pid + '" data-face-size="' + size + '" aria-hidden="true"></span>';
  }

  // Filterable combobox (ARIA 1.2 combobox pattern, modeled on the header
  // search). Expects the server-rendered skeleton: .combo > .combo-input +
  // .combo-list. opts: { options() -> [{id,label,sub,search[]}], onSelect(id),
  //                      committed(option) -> input text, maxResults }
  function createCombobox(container, opts) {
    const input = container.querySelector('.combo-input');
    const list = container.querySelector('.combo-list');
    const maxResults = opts.maxResults || 12;
    let committedText = '';
    let selected = -1;
    let items = [];

    function score(q, option) {
      const terms = option.search && option.search.length ? option.search : [option.label];
      let best = -1;
      terms.forEach((term) => {
        const n = norm(term);
        let s = -1;
        if (n.startsWith(q)) s = 0;
        else if (n.split(' ').some((w) => w.startsWith(q))) s = 1;
        else if (n.includes(q)) s = 2;
        if (s >= 0 && (best < 0 || s < best)) best = s;
      });
      return best;
    }

    function matches(q) {
      const options = opts.options();
      if (!q) return options.slice(0, maxResults);
      const scored = [];
      options.forEach((o, i) => {
        const s = score(q, o);
        if (s >= 0) scored.push([s, i, o]);
      });
      scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      return scored.slice(0, maxResults).map((x) => x[2]);
    }

    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }

    function syncSelected() {
      Array.from(list.querySelectorAll('[role="option"]')).forEach((el, i) => {
        const on = i === selected;
        el.classList.toggle('selected', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) el.scrollIntoView({ block: 'nearest' });
      });
      const active = selected >= 0 ? list.querySelectorAll('[role="option"]')[selected] : null;
      input.setAttribute('aria-activedescendant', active ? active.id : '');
    }

    function pick(option) {
      committedText = opts.committed ? opts.committed(option) : option.label;
      input.value = committedText;
      close();
      opts.onSelect(option.id);
    }

    function openList() {
      items = matches(norm(input.value.trim()));
      if (!items.length) {
        list.innerHTML = '<div class="combo-empty" role="option" aria-disabled="true">No matches.</div>';
      } else {
        list.innerHTML = items.map((o, i) =>
          '<div class="combo-option" id="' + list.id + '-opt-' + i + '" role="option" aria-selected="false">'
          + '<span>' + escapeHtml(o.label) + '</span>'
          + (o.sub ? '<span class="muted">' + escapeHtml(o.sub) + '</span>' : '')
          + '</div>').join('');
        Array.from(list.querySelectorAll('.combo-option')).forEach((el, i) => {
          // mousedown beats the input's focusout, so the pick lands first
          el.addEventListener('mousedown', (event) => { event.preventDefault(); pick(items[i]); });
        });
      }
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('input', () => {
      openList();
      if (input.value.trim() === '' && committedText !== '') {
        committedText = '';
        opts.onSelect(null);
      }
    });
    input.addEventListener('focus', () => { input.select(); openList(); });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { input.value = committedText; close(); return; }
      if (event.key === 'Tab') { input.value = committedText; close(); return; }
      if (list.hidden && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) { event.preventDefault(); openList(); return; }
      if (list.hidden || !items.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, items.length - 1); syncSelected(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); syncSelected(); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = items[Math.max(0, selected)];
        if (target) pick(target);
      }
    });
    input.addEventListener('blur', () => { input.value = committedText; close(); });

    return {
      input,
      enable() { input.disabled = false; },
      setSelection(option) {
        committedText = option ? (opts.committed ? opts.committed(option) : option.label) : '';
        input.value = committedText;
      },
    };
  }

  window.SMPApps = {
    loadAppData, escapeHtml, norm, fmtSalary, playerUrl, teamAbbrevFor,
    teamColors, monogramSvg, initialsOf, hydrateFaces, facePlaceholder,
    createCombobox, rootPath,
  };

  // ---------- Compare page ----------
  const out = document.querySelector('[data-compare-out]');
  const comboEls = Array.from(document.querySelectorAll('[data-compare-combo]'));
  if (!out || !comboEls.length) return;

  const extraEl = document.getElementById('compare-extra');
  const extras = extraEl ? JSON.parse(extraEl.textContent) : { ratingKeys: [], stats: {} };
  const radarBlock = document.querySelector('[data-compare-radar]');
  const radarOut = document.querySelector('[data-radar-out]');

  // Spoke -> subrating mapping (keep in sync with the docstring in
  // scripts/smp/pages/compare.py; oiq/diq intentionally feed two spokes each).
  const SPOKES = [
    ['Shooting', ['tp', 'fg', 'ft']],
    ['Finishing', ['ins', 'dnk']],
    ['Athleticism', ['spd', 'jmp', 'stre', 'endu']],
    ['Playmaking', ['pss', 'drb', 'oiq']],
    ['Defense', ['diq', 'reb', 'hgt']],
    ['IQ', ['oiq', 'diq']],
  ];

  loadAppData().then((data) => {
    const players = data.players;
    const byPid = {};
    players.forEach((p) => { byPid[p.pid] = p; });
    const teamsByTid = {};
    data.teams.forEach((t) => { teamsByTid[t.tid] = t; });

    const picked = [null, null, null];

    const comboOptions = players.map((p) => ({
      id: p.pid,
      label: p.name,
      sub: teamAbbrevFor(p.tid, teamsByTid) + ' · ' + p.pos + ' · ' + p.ovr + ' ovr',
      search: [p.name, teamAbbrevFor(p.tid, teamsByTid) + ' ' + p.name],
    }));
    const optionByPid = {};
    comboOptions.forEach((o) => { optionByPid[o.id] = o; });

    const combos = comboEls.map((el, i) => createCombobox(el, {
      options: () => comboOptions,
      onSelect: (pid) => { picked[i] = pid === null ? null : byPid[pid] || null; syncHash(); render(); },
    }));

    // Initial picks: the URL hash (share/permalink state, "#pid,pid,pid"),
    // else two computed defaults — the top-overall rostered player vs the
    // highest-potential rostered 23-and-under player.
    const fromHash = (location.hash || '').replace(/^#/, '').split(',').filter(Boolean);
    if (fromHash.length && fromHash.some((pid) => byPid[pid])) {
      fromHash.slice(0, 3).forEach((pid, i) => { if (byPid[pid]) picked[i] = byPid[pid]; });
    } else {
      const topOvr = players.find((p) => p.tid >= 0) || players[0];
      const young = players
        .filter((p) => p !== topOvr && p.tid >= 0 && p.age !== null && p.age <= 23)
        .sort((a, b) => (b.pot - a.pot) || (b.ovr - a.ovr) || (a.pid - b.pid))[0]
        || players.find((p) => p !== topOvr);
      picked[0] = topOvr || null;
      picked[1] = young || null;
    }
    combos.forEach((combo, i) => {
      combo.setSelection(picked[i] ? optionByPid[picked[i].pid] : null);
      combo.enable();
    });

    function syncHash() {
      const pids = picked.filter(Boolean).map((p) => p.pid);
      history.replaceState(null, '', pids.length ? '#' + pids.join(',') : location.pathname + location.search);
    }

    function extraOf(p) {
      return extras.stats[String(p.pid)] || [0, null, null, null, null];
    }

    function statRows(chosen) {
      // [label, values, {pct: format as %, lower: lower is better}]
      const pgRow = (key) => chosen.map((p) => p.pg[key]);
      const exRow = (idx) => chosen.map((p) => extraOf(p)[idx]);
      return [
        ['Games', exRow(0), {}],
        ['MP/G', pgRow('min'), {}],
        ['PTS/G', pgRow('pts'), {}],
        ['TRB/G', pgRow('trb'), {}],
        ['AST/G', pgRow('ast'), {}],
        ['STL/G', pgRow('stl'), {}],
        ['BLK/G', pgRow('blk'), {}],
        ['TOV/G', pgRow('tov'), { lower: true }],
        ['FG%', pgRow('fg_pct'), {}],
        ['3P%', pgRow('tp_pct'), {}],
        ['FT%', pgRow('ft_pct'), {}],
        ['FPTS/G', pgRow('fpts'), {}],
        ['TS%', exRow(1), {}],
        ['PER', exRow(2), {}],
        ['BPM', exRow(3), {}],
        ['WS', exRow(4), {}],
      ];
    }

    function render() {
      const chosen = picked.filter(Boolean);
      if (chosen.length < 2) {
        if (radarBlock) radarBlock.hidden = true;
        out.innerHTML = '<p class="muted">Pick at least two players.</p>';
        return;
      }
      let html = '<div class="table-wrap fit-table"><table class="cmp-players"><thead><tr><th scope="col"></th>';
      chosen.forEach((p) => {
        const ageText = p.age === null ? '—' : p.age + 'y';
        html += '<th scope="col">' + facePlaceholder(p.pid, 26)
          + '<a href="' + playerUrl(p) + '">' + escapeHtml(p.name) + '</a>'
          + '<span class="muted"> ' + escapeHtml(teamAbbrevFor(p.tid, teamsByTid)) + ' · ' + escapeHtml(p.pos) + ' · ' + ageText + '</span></th>';
      });
      html += '</tr></thead><tbody>';
      const row = (label, values, options) => {
        const withBar = options && options.bar;
        const lower = options && options.lower;
        html += '<tr><td class="cmp-label">' + label + '</td>';
        const nums = values.map(Number).filter(Number.isFinite);
        const best = nums.length > 1 ? (lower ? Math.min(...nums) : Math.max(...nums)) : null;
        values.forEach((v) => {
          const num = Number(v);
          const isBest = Number.isFinite(num) && best !== null && num === best;
          let cell = (v === null || v === undefined || v === '') ? '—' : escapeHtml(v);
          if (withBar && Number.isFinite(num)) {
            cell = '<span class="cmp-bar"><i style="width:' + Math.max(2, Math.min(100, num)) + '%"></i></span>' + cell;
          }
          html += '<td class="' + (isBest ? 'cmp-best' : '') + '">' + cell + '</td>';
        });
        html += '</tr>';
      };
      row('Overall', chosen.map((p) => p.ovr), { bar: true });
      row('Potential', chosen.map((p) => p.pot), { bar: true });
      row('Contract', chosen.map((p) => fmtSalary(p.salary) + '/' + (p.exp === null ? '—' : p.exp)), {});
      row('Trade value', chosen.map((p) => p.value), {});
      extras.ratingKeys.forEach(([key, label]) => row(label, chosen.map((p) => p.ratings[key]), { bar: true }));
      statRows(chosen).forEach(([label, values, options]) => row(label, values, options));
      html += '</tbody></table></div>';
      out.innerHTML = html;
      hydrateFaces(out, byPid, teamsByTid);
      renderRadar(chosen);
    }

    function spokeValues(p) {
      return SPOKES.map(([, keys]) => Math.round(keys.reduce((s, k) => s + (p.ratings[k] || 0), 0) / keys.length));
    }

    function renderRadar(chosen) {
      if (!radarBlock || !radarOut) return;
      radarBlock.hidden = false;
      const cx = 230, cy = 190, R = 130;
      const pt = (i, v) => {
        const ang = (Math.PI / 180) * (-90 + i * 60);
        const r = (v / 100) * R;
        return (cx + r * Math.cos(ang)).toFixed(1) + ',' + (cy + r * Math.sin(ang)).toFixed(1);
      };
      let svg = '<svg class="radar-svg" viewBox="0 0 460 400" role="img" aria-label="Skill radar comparing '
        + escapeHtml(chosen.map((p) => p.name).join(', ')) + '">';
      [20, 40, 60, 80, 100].forEach((ring) => {
        svg += '<polygon class="radar-grid" points="' + SPOKES.map((_, i) => pt(i, ring)).join(' ') + '"/>';
      });
      SPOKES.forEach(([label], i) => {
        svg += '<line class="radar-axis" x1="' + cx + '" y1="' + cy + '" x2="' + pt(i, 100).replace(',', '" y2="') + '"/>';
        const ang = (Math.PI / 180) * (-90 + i * 60);
        const lx = cx + (R + 16) * Math.cos(ang);
        const ly = cy + (R + 16) * Math.sin(ang);
        const anchor = Math.abs(Math.cos(ang)) < 0.3 ? 'middle' : (Math.cos(ang) > 0 ? 'start' : 'end');
        svg += '<text class="radar-label" x="' + lx.toFixed(1) + '" y="' + (ly + 4).toFixed(1) + '" text-anchor="' + anchor + '">' + label + '</text>';
      });
      const seenColors = [];
      chosen.forEach((p) => {
        const color = teamColors(p.tid, teamsByTid).chart;
        // repeat colors (teammates) get dashed outlines so polygons stay tellable-apart
        const dupes = seenColors.filter((c) => c === color).length;
        seenColors.push(color);
        const dash = dupes === 0 ? '' : ' stroke-dasharray="' + (dupes === 1 ? '7 4' : '2 5') + '"';
        const values = spokeValues(p);
        const points = values.map((v, i) => pt(i, v)).join(' ');
        svg += '<polygon class="radar-poly" points="' + points + '" fill="' + color + '" stroke="' + color + '"' + dash + '/>';
        values.forEach((v, i) => {
          const [x, y] = pt(i, v).split(',');
          svg += '<circle class="radar-dot" cx="' + x + '" cy="' + y + '" r="3.2" fill="' + color + '">'
            + '<title>' + escapeHtml(p.name) + ' — ' + SPOKES[i][0] + ' ' + v + '</title></circle>';
        });
      });
      svg += '</svg>';
      let legend = '<div class="radar-legend">';
      chosen.forEach((p, idx) => {
        const color = teamColors(p.tid, teamsByTid).chart;
        legend += '<span class="radar-chip">'
          + '<i class="radar-swatch' + (idx > 0 && seenColors.slice(0, idx).includes(color) ? ' radar-swatch--dashed' : '') + '" style="background:' + color + '"></i>'
          + facePlaceholder(p.pid, 28)
          + '<a href="' + playerUrl(p) + '">' + escapeHtml(p.name) + '</a>'
          + '<span class="muted">' + escapeHtml(teamAbbrevFor(p.tid, teamsByTid)) + '</span>'
          + '</span>';
      });
      legend += '</div>';
      radarOut.innerHTML = svg + legend;
      hydrateFaces(radarOut, byPid, teamsByTid);
    }

    if (location.hash) syncHash(); // normalize away any invalid pids; keep clean URLs clean
    render();
  }).catch(() => {
    out.innerHTML = '<p class="app-error">Couldn’t load player data (assets/app-data.json). Check your connection and refresh to retry.</p>';
  });
})();
