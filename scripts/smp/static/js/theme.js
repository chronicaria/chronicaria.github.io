  // ---------- platform config + storage (shared by later fragments) ----------
  const smpConfigEl = document.getElementById('smp-config');
  let siteConfig = {};
  if (smpConfigEl) {
    try { siteConfig = JSON.parse(smpConfigEl.textContent) || {}; } catch (e) { siteConfig = {}; }
  }
  const smpStore = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) {} },
    remove(key) { try { localStorage.removeItem(key); } catch (e) {} },
  };

  // ---------- three-state theme toggle (auto / dark / light) ----------
  // Persisted as localStorage.theme = "dark"|"light"; auto = key absent, which is
  // exactly what the pre-paint snippet in page_html reads before first render.
  const themeBtn = document.querySelector('[data-theme-toggle]');
  const themeMedia = matchMedia('(prefers-color-scheme: light)');
  const THEME_LABELS = {
    auto: 'Theme: auto (follows your system)',
    dark: 'Theme: dark',
    light: 'Theme: light',
  };
  function applyThemePref(pref, persist) {
    document.documentElement.dataset.themePref = pref;
    document.documentElement.dataset.theme = pref === 'auto' ? (themeMedia.matches ? 'light' : 'dark') : pref;
    if (persist) {
      if (pref === 'auto') smpStore.remove('theme');
      else smpStore.set('theme', pref);
    }
    if (themeBtn) {
      themeBtn.setAttribute('aria-label', THEME_LABELS[pref]);
      themeBtn.title = THEME_LABELS[pref] + ' — click to change';
    }
  }
  const savedTheme = smpStore.get('theme');
  applyThemePref(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : 'auto', false);
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const order = ['auto', 'dark', 'light'];
      const current = document.documentElement.dataset.themePref || 'auto';
      applyThemePref(order[(order.indexOf(current) + 1) % order.length], true);
    });
  }
  const onThemeMediaChange = () => {
    if ((document.documentElement.dataset.themePref || 'auto') === 'auto') applyThemePref('auto', false);
  };
  if (themeMedia.addEventListener) themeMedia.addEventListener('change', onThemeMediaChange);
  else if (themeMedia.addListener) themeMedia.addListener(onThemeMediaChange);

  // ---------- My Team mode ----------
  // Picking a team stores the tid, retints --accent with the team's chart color
  // (readable on both themes by design), tags body[data-my-team], highlights every
  // row carrying data-tid, and pins the team to the top of the Teams menu.
  const teamPicker = document.querySelector('[data-my-team-picker]');
  const myTeamColors = siteConfig.teamColors || {};
  function applyMyTeam(tid, persist) {
    const rootStyle = document.documentElement.style;
    const colors = tid ? myTeamColors[tid] : null;
    document.querySelectorAll('tr.my-team-row').forEach((row) => row.classList.remove('my-team-row'));
    document.querySelectorAll('.my-team-link').forEach((a) => a.classList.remove('my-team-link'));
    if (!colors) {
      delete document.body.dataset.myTeam;
      rootStyle.removeProperty('--accent');
      rootStyle.removeProperty('--accent-soft');
      if (persist) { smpStore.remove('myTeam'); smpStore.remove('myTeamAccent'); }
    } else {
      document.body.dataset.myTeam = tid;
      rootStyle.setProperty('--accent', colors.chart);
      rootStyle.setProperty('--accent-soft', 'color-mix(in srgb, ' + colors.chart + ' 14%, transparent)');
      document.querySelectorAll('tr[data-tid="' + tid + '"]').forEach((row) => row.classList.add('my-team-row'));
      const navLink = document.querySelector('.team-menu a[data-tid="' + tid + '"]');
      if (navLink) {
        navLink.classList.add('my-team-link');
        if (navLink.parentElement && navLink.parentElement.firstElementChild !== navLink) {
          navLink.parentElement.insertBefore(navLink, navLink.parentElement.firstElementChild);
        }
      }
      if (persist) { smpStore.set('myTeam', tid); smpStore.set('myTeamAccent', colors.chart); }
    }
    if (teamPicker && teamPicker.value !== tid) teamPicker.value = tid;
  }
  const savedTeam = smpStore.get('myTeam');
  if (savedTeam && myTeamColors[savedTeam]) applyMyTeam(savedTeam, false);
  else if (savedTeam) { smpStore.remove('myTeam'); smpStore.remove('myTeamAccent'); }
  if (teamPicker) teamPicker.addEventListener('change', () => applyMyTeam(teamPicker.value, true));

  // ---------- heading anchor links (hover #, click copies the URL) ----------
  document.querySelectorAll('main.page-shell h2').forEach((heading) => {
    const text = heading.textContent.trim();
    if (!text) return;
    if (!heading.id) {
      const base = text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'section';
      let id = base;
      let n = 2;
      while (document.getElementById(id)) { id = base + '-' + n; n += 1; }
      heading.id = id;
    }
    const anchor = document.createElement('a');
    anchor.className = 'h-anchor';
    anchor.href = '#' + heading.id;
    anchor.setAttribute('aria-label', 'Link to section: ' + text);
    anchor.textContent = '#';
    anchor.addEventListener('click', () => {
      if (!navigator.clipboard) return;
      const url = location.origin + location.pathname + '#' + heading.id;
      navigator.clipboard.writeText(url).then(() => {
        anchor.textContent = '✓';
        setTimeout(() => { anchor.textContent = '#'; }, 1200);
      }).catch(() => {});
    });
    heading.appendChild(anchor);
  });

