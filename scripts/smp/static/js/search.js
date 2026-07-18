  // ---------- shared search index ----------
  const searchIndexRoot = document.body.dataset.root || '';
  let smpSearchIndex = null;
  function loadSearchIndex() {
    if (smpSearchIndex) return Promise.resolve(smpSearchIndex);
    return fetch(searchIndexRoot + 'assets/search-index.json')
      .then((r) => r.json())
      .then((data) => { smpSearchIndex = data; return smpSearchIndex; })
      .catch(() => ({ players: [], teams: [] }));
  }
  const smpNorm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  function smpMatchScore(name, q) {
    const n = smpNorm(name);
    if (n.startsWith(q)) return 0;
    if (n.split(' ').some((w) => w.startsWith(q))) return 1;
    if (n.includes(q)) return 2;
    return -1;
  }

  // ---------- global nav search ----------
  const searchInput = document.querySelector('[data-global-search]');
  const searchResults = document.querySelector('[data-search-results]');
  if (searchInput && searchResults) {
    const root = searchIndexRoot;
    let selected = -1;

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
      const q = smpNorm(searchInput.value.trim());
      if (q.length < 2) { close(); return; }
      loadSearchIndex().then((data) => {
        const matches = [];
        (data.teams || []).forEach((t) => { const s = smpMatchScore(t.n, q); if (s >= 0) matches.push({ ...t, s: s - 0.5 }); });
        (data.players || []).forEach((p) => { const s = smpMatchScore(p.n, q); if (s >= 0) matches.push({ ...p, s }); });
        matches.sort((a, b) => a.s - b.s || a.n.localeCompare(b.n));
        renderResults(matches.slice(0, 8));
      });
    }

    searchInput.addEventListener('input', update);
    searchInput.addEventListener('focus', () => { loadSearchIndex(); if (searchInput.value.trim().length >= 2) update(); });
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

  // ---------- command palette (Cmd+K / Ctrl+K / "/") ----------
  // Searches the same index as the nav search, grouped into Pages / Teams /
  // Players, with recent selections and t: / p: / g: prefix filters.
  const PALETTE_GROUPS = [
    { key: 'Pages', prefix: 'g' },
    { key: 'Teams', prefix: 't' },
    { key: 'Players', prefix: 'p' },
  ];
  let paletteOverlay = null;
  let paletteInput = null;
  let paletteResults = null;
  let paletteSelected = -1;
  let paletteReturnFocus = null;

  function paletteRecents() {
    try { return JSON.parse(smpStore.get('paletteRecents') || '[]') || []; } catch (e) { return []; }
  }
  function rememberRecent(item) {
    const next = [item].concat(paletteRecents().filter((r) => r.u !== item.u)).slice(0, 8);
    smpStore.set('paletteRecents', JSON.stringify(next));
  }

  function paletteEntries(data) {
    const pages = ((siteConfig && siteConfig.pages) || []).map((p) => ({ n: p.label, u: p.url, t: 'Page', g: 'Pages' }));
    const teams = (data.teams || []).map((t) => ({ n: t.n, u: t.u, t: t.t, g: 'Teams' }));
    const players = (data.players || []).map((p) => ({ n: p.n, u: p.u, t: p.t, g: 'Players' }));
    return { Pages: pages, Teams: teams, Players: players };
  }

  function renderPalette(groups) {
    const options = [];
    let html = '';
    groups.forEach((group) => {
      if (!group.items.length) return;
      html += '<div class="palette-group" role="presentation">' + escapeHtml(group.label) + '</div>';
      group.items.forEach((item) => {
        const i = options.length;
        options.push(item);
        html += '<a class="pal-opt" id="pal-opt-' + i + '" role="option" aria-selected="false" href="' + searchIndexRoot + escapeHtml(item.u) + '">'
          + '<span>' + escapeHtml(item.n) + '</span><span class="muted">' + escapeHtml(item.t || '') + '</span></a>';
      });
    });
    if (!options.length) html = '<div class="palette-empty">No matches.</div>';
    paletteResults.innerHTML = html;
    paletteSelected = options.length ? 0 : -1;
    syncPaletteSelected();
    paletteResults.querySelectorAll('a.pal-opt').forEach((a, i) => {
      a.addEventListener('click', () => rememberRecent(options[i]));
    });
    paletteResults._options = options;
  }

  function syncPaletteSelected() {
    const links = Array.from(paletteResults.querySelectorAll('a.pal-opt'));
    links.forEach((l, i) => {
      const on = i === paletteSelected;
      l.classList.toggle('selected', on);
      l.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) l.scrollIntoView({ block: 'nearest' });
    });
    paletteInput.setAttribute('aria-activedescendant', paletteSelected >= 0 && links[paletteSelected] ? links[paletteSelected].id : '');
  }

  function updatePalette() {
    const raw = paletteInput.value.trim();
    let only = null;
    let q = raw;
    const prefixMatch = raw.match(/^([gtp]):\s*(.*)$/i);
    if (prefixMatch) {
      const found = PALETTE_GROUPS.find((g) => g.prefix === prefixMatch[1].toLowerCase());
      if (found) { only = found.key; q = prefixMatch[2]; }
    }
    q = smpNorm(q);
    loadSearchIndex().then((data) => {
      const entries = paletteEntries(data);
      if (!q) {
        const groups = [];
        const recents = paletteRecents();
        if (recents.length && !only) groups.push({ label: 'Recent', items: recents });
        (only ? [only] : ['Pages']).forEach((key) => groups.push({ label: key, items: entries[key].slice(0, only ? 24 : 8) }));
        renderPalette(groups);
        return;
      }
      const caps = { Pages: 6, Teams: 6, Players: 9 };
      const groups = PALETTE_GROUPS
        .filter((g) => !only || g.key === only)
        .map((g) => {
          const items = entries[g.key]
            .map((item) => ({ item, s: smpMatchScore(item.n, q) }))
            .filter((x) => x.s >= 0)
            .sort((a, b) => a.s - b.s || a.item.n.localeCompare(b.item.n))
            .slice(0, only ? 24 : caps[g.key])
            .map((x) => x.item);
          return { label: g.key, items };
        });
      renderPalette(groups);
    });
  }

  function closePalette() {
    if (!paletteOverlay) return;
    paletteOverlay.hidden = true;
    if (paletteReturnFocus && paletteReturnFocus.focus) paletteReturnFocus.focus();
    paletteReturnFocus = null;
  }

  function buildPalette() {
    if (paletteOverlay) return;
    paletteOverlay = document.createElement('div');
    paletteOverlay.className = 'palette-overlay';
    paletteOverlay.hidden = true;
    paletteOverlay.innerHTML = '<div class="palette" role="dialog" aria-modal="true" aria-label="Site search">'
      + '<input type="text" class="palette-input" placeholder="Search players, teams, pages…" '
      + 'role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls="palette-results" '
      + 'aria-activedescendant="" autocomplete="off" spellcheck="false">'
      + '<div class="palette-results" id="palette-results" role="listbox" aria-label="Search results"></div>'
      + '<p class="palette-hint muted">↑↓ navigate · Enter open · Esc close · prefixes: t: teams · p: players · g: pages</p>'
      + '</div>';
    document.body.appendChild(paletteOverlay);
    paletteInput = paletteOverlay.querySelector('.palette-input');
    paletteResults = paletteOverlay.querySelector('.palette-results');
    paletteOverlay.addEventListener('click', (event) => {
      if (event.target === paletteOverlay) closePalette();
    });
    paletteInput.addEventListener('input', updatePalette);
    paletteInput.addEventListener('keydown', (event) => {
      const links = Array.from(paletteResults.querySelectorAll('a.pal-opt'));
      if (event.key === 'Escape') { event.preventDefault(); closePalette(); return; }
      if (event.key === 'Tab') { event.preventDefault(); return; }
      if (!links.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); paletteSelected = Math.min(paletteSelected + 1, links.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); paletteSelected = Math.max(paletteSelected - 1, 0); }
      else if (event.key === 'Home' && paletteSelected > 0) { event.preventDefault(); paletteSelected = 0; }
      else if (event.key === 'End') { event.preventDefault(); paletteSelected = links.length - 1; }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = links[Math.max(0, paletteSelected)];
        if (target) {
          const options = paletteResults._options || [];
          const item = options[Math.max(0, paletteSelected)];
          if (item) rememberRecent(item);
          window.location.href = target.href;
        }
        return;
      } else { return; }
      syncPaletteSelected();
    });
  }

  function openPalette() {
    buildPalette();
    paletteReturnFocus = document.activeElement;
    paletteOverlay.hidden = false;
    paletteInput.value = '';
    paletteInput.focus();
    updatePalette();
  }

  document.addEventListener('keydown', (event) => {
    const isK = (event.key === 'k' || event.key === 'K') && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
    const isSlash = event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey;
    if (!isK && !isSlash) return;
    if (isSlash) {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT' || active.isContentEditable)) return;
    }
    if (paletteOverlay && !paletteOverlay.hidden) return;
    event.preventDefault();
    openPalette();
  });

  // =====================================================================
  // SMP.combobox — reusable filterable combobox factory
  //
  //   SMP.combobox({
  //     input:    HTMLInputElement (required). Gets combobox ARIA wiring; the
  //               popup list is created as a sibling inside a positioning wrap.
  //     items:    array of {label, sub?, value?} OR a function returning one.
  //               `label` is matched and shown left; `sub` shown right, muted.
  //     onSelect: function(item) called when the user picks an option (required).
  //     maxItems: cap on rendered options (default 12).
  //     minChars: minimum typed characters before the list opens (default 0;
  //               0 shows the top of the list on focus, like a select).
  //   }) -> { refresh(), close(), destroy() }
  //
  // Matching uses the same normalized prefix/word/substring scoring as site
  // search. Keyboard: ArrowUp/Down, Enter selects, Escape closes. On select the
  // input shows item.label and onSelect(item) fires.
  // =====================================================================
  window.SMP = window.SMP || {};
  window.SMP.combobox = function (opts) {
    const input = opts.input;
    if (!input) return null;
    const maxItems = opts.maxItems || 12;
    const minChars = opts.minChars || 0;
    const wrap = document.createElement('span');
    wrap.className = 'smp-combobox';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const list = document.createElement('div');
    list.className = 'smp-combobox-list';
    list.setAttribute('role', 'listbox');
    list.id = 'smp-cbx-' + Math.abs((input.id || input.name || 'cbx').split('').reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7));
    list.hidden = true;
    wrap.appendChild(list);
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('autocomplete', 'off');
    let selected = -1;
    let current = [];

    function itemsNow() {
      return (typeof opts.items === 'function' ? opts.items() : opts.items) || [];
    }
    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }
    function choose(index) {
      const item = current[index];
      if (!item) return;
      input.value = item.label;
      close();
      opts.onSelect(item);
    }
    function sync() {
      Array.from(list.children).forEach((el, i) => {
        const on = i === selected;
        el.classList.toggle('selected', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) el.scrollIntoView({ block: 'nearest' });
      });
      input.setAttribute('aria-activedescendant', selected >= 0 && list.children[selected] ? list.children[selected].id : '');
    }
    function refresh() {
      const q = smpNorm(input.value.trim());
      if (q.length < minChars) { close(); return; }
      const scored = itemsNow()
        .map((item) => ({ item, s: q ? smpMatchScore(item.label, q) : 0 }))
        .filter((x) => x.s >= 0);
      if (q) scored.sort((a, b) => a.s - b.s || String(a.item.label).localeCompare(String(b.item.label)));
      current = scored.slice(0, maxItems).map((x) => x.item);
      if (!current.length) { close(); return; }
      list.innerHTML = current.map((item, i) =>
        '<div class="smp-cbx-opt" id="' + list.id + '-' + i + '" role="option" aria-selected="false">'
        + '<span>' + escapeHtml(item.label) + '</span>'
        + (item.sub ? '<span class="muted">' + escapeHtml(item.sub) + '</span>' : '')
        + '</div>').join('');
      Array.from(list.children).forEach((el, i) => {
        el.addEventListener('mousedown', (event) => { event.preventDefault(); choose(i); });
      });
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
    }
    function onKeydown(event) {
      if (event.key === 'Escape') { close(); return; }
      if (list.hidden) {
        if (event.key === 'ArrowDown') { event.preventDefault(); refresh(); }
        return;
      }
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, current.length - 1); sync(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); sync(); }
      else if (event.key === 'Enter') { event.preventDefault(); choose(Math.max(0, selected)); }
    }
    function onDocClick(event) {
      if (!wrap.contains(event.target)) close();
    }
    input.addEventListener('input', refresh);
    input.addEventListener('focus', refresh);
    input.addEventListener('keydown', onKeydown);
    document.addEventListener('click', onDocClick);
    return {
      refresh,
      close,
      destroy() {
        input.removeEventListener('input', refresh);
        input.removeEventListener('focus', refresh);
        input.removeEventListener('keydown', onKeydown);
        document.removeEventListener('click', onDocClick);
        list.remove();
      },
    };
  };

