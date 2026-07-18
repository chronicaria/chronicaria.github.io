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

