// ---------- Win-Out Machine (simulator.html) ----------
// Self-contained IIFE: appended after the main site bundle's closing wrapper,
// so it guards on its own root element and no-ops on every other page.
(function () {
  const app = document.querySelector('[data-wo-app]');
  if (!app) return;
  const root = document.body.dataset.root || '';

  const N_SIMS = 5000;
  // Deterministic PRNG. The stream is mulberry32 seeded with
  //   seed = 20290101 ^ fnv1a(lockString)
  // where 20290101 is the same constant the server-side Monte Carlo seeds with
  // (simmodel.simulate_league) and lockString is the canonical picks encoding
  // ("3h,17a", also the URL hash). Identical picks therefore always replay the
  // identical 5,000 simulations; changing any pick starts a fresh but equally
  // reproducible stream.
  function fnv1a(str) {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i += 1) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Client-side port of core.heat_style: red (worst) -> green (best) tint.
  // Same hsla convention as the server-rendered heat cells (exempt from theming).
  function heatStyle(value, lo, hi, direction) {
    if (!direction || value === null || value === undefined) return '';
    const v = Number(value);
    if (!Number.isFinite(v) || hi - lo <= 1e-12) return '';
    let frac = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    if (direction < 0) frac = 1 - frac;
    const hue = 4 + frac * 126;
    return 'background-color: hsla(' + hue.toFixed(0) + ', 55%, 41%, .45)';
  }

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtPct = (p) => (p * 100).toFixed(1) + '%';

  const gamesEl = app.querySelector('[data-wo-games]');
  const oddsEl = app.querySelector('[data-wo-odds]');
  const countEl = app.querySelector('[data-wo-count]');
  const resetBtn = app.querySelector('[data-wo-reset]');

  let payload = null;
  let teams = [];        // payload team entries, index == tid order of tidList
  let tidList = [];      // tids in payload order
  let tidIndex = {};     // tid -> index into tidList
  let schedule = [];     // [[day, homeTid, awayTid], ...] chronological
  let pHome = [];        // per-game home-win probability (model, unlocked)
  let state = [];        // per-game: 's' (simulate) | 'h' (home locked) | 'a' (away locked)
  let pending = false;

  // --- lock-state <-> URL hash ("3h,17a" — game index + winner) --------------
  function lockString() {
    const parts = [];
    state.forEach((s, i) => { if (s !== 's') parts.push(i + s); });
    return parts.join(',');
  }

  function syncHash() {
    const str = lockString();
    history.replaceState(null, '', str ? '#' + str : location.pathname + location.search);
  }

  function readHash() {
    (location.hash || '').replace(/^#/, '').split(',').forEach((part) => {
      const m = /^(\d+)([ha])$/.exec(part.trim());
      if (m) {
        const idx = Number(m[1]);
        if (idx >= 0 && idx < state.length) state[idx] = m[2];
      }
    });
  }

  // --- Monte Carlo over the unlocked games -----------------------------------
  // Mirrors simmodel.simulate_league's regular-season loop over the payload's
  // strengths: p(home) = 1 / (1 + exp(-(diff + hca) * k)), random tie-break on
  // equal win totals, top four seeds make the playoffs.
  function runSims() {
    const n = tidList.length;
    const baseWins = new Float64Array(n);
    teams.forEach((t, i) => { baseWins[i] = t.record.w; });
    const open = [];
    schedule.forEach((g, i) => {
      const hi = tidIndex[g[1]];
      const ai = tidIndex[g[2]];
      if (state[i] === 'h') baseWins[hi] += 1;
      else if (state[i] === 'a') baseWins[ai] += 1;
      else open.push([hi, ai, pHome[i]]);
    });

    const rng = mulberry32((20290101 ^ fnv1a(lockString())) >>> 0);
    const playoffCount = new Float64Array(n);
    const winTotal = new Float64Array(n);
    const seedCounts = [];
    for (let i = 0; i < n; i += 1) seedCounts.push(new Float64Array(n));

    const wins = new Float64Array(n);
    const order = new Array(n);
    const tie = new Float64Array(n);
    for (let s = 0; s < N_SIMS; s += 1) {
      wins.set(baseWins);
      for (let g = 0; g < open.length; g += 1) {
        if (rng() < open[g][2]) wins[open[g][0]] += 1;
        else wins[open[g][1]] += 1;
      }
      for (let i = 0; i < n; i += 1) { order[i] = i; tie[i] = rng(); }
      order.sort((a, b) => wins[b] - wins[a] || tie[a] - tie[b]);
      for (let seed = 0; seed < n; seed += 1) {
        const i = order[seed];
        seedCounts[i][seed] += 1;
        if (seed < 4) playoffCount[i] += 1;
        winTotal[i] += wins[i];
      }
    }

    return teams.map((t, i) => ({
      team: t,
      expWins: winTotal[i] / N_SIMS,
      playoff: playoffCount[i] / N_SIMS,
      seeds: Array.from(seedCounts[i], (c) => c / N_SIMS),
    }));
  }

  // --- rendering -------------------------------------------------------------
  function teamDot(tid) {
    const t = teams[tidIndex[tid]];
    const color = t && t.colors ? t.colors.chart : '#8899aa';
    return '<i class="wo-dot" style="background:' + escapeHtml(color) + '" aria-hidden="true"></i>';
  }

  function abbrev(tid) {
    const t = teams[tidIndex[tid]];
    return t ? t.abbrev : 'T' + tid;
  }

  function renderBoard() {
    if (!schedule.length) {
      gamesEl.innerHTML = '<p class="muted">No remaining games — the regular season is decided.</p>';
      return;
    }
    const byDay = new Map();
    schedule.forEach((g, i) => {
      if (!byDay.has(g[0])) byDay.set(g[0], []);
      byDay.get(g[0]).push(i);
    });
    let html = '';
    let first = true;
    byDay.forEach((idxs, day) => {
      html += '<details class="wo-day"' + (first ? ' open' : '') + '><summary>Day ' + day
        + ' <span class="muted">' + idxs.length + (idxs.length === 1 ? ' game' : ' games') + '</span></summary>'
        + '<div class="wo-day-games">';
      idxs.forEach((i) => {
        const g = schedule[i];
        const away = abbrev(g[2]);
        const home = abbrev(g[1]);
        const seg = (value, label, aria) =>
          '<label class="wo-seg"><input type="radio" name="wo-g' + i + '" value="' + value + '"'
          + ' data-game="' + i + '"' + (state[i] === value ? ' checked' : '') + ' aria-label="' + escapeHtml(aria) + '">'
          + '<span>' + escapeHtml(label) + '</span></label>';
        html += '<fieldset class="wo-game"><legend class="sr-only">' + escapeHtml(away + ' at ' + home + ', day ' + day) + '</legend>'
          + '<span class="wo-matchup">' + teamDot(g[2]) + escapeHtml(away)
          + ' <span class="muted">@</span> ' + teamDot(g[1]) + escapeHtml(home) + '</span>'
          + '<span class="wo-segs" role="radiogroup" aria-label="' + escapeHtml('Result of ' + away + ' at ' + home) + '">'
          + seg('a', away, away + ' wins')
          + seg('s', 'Sim', 'Simulate ' + away + ' at ' + home)
          + seg('h', home, home + ' wins')
          + '</span>'
          + '<span class="wo-hint muted">' + escapeHtml(home) + ' ' + Math.round(pHome[i] * 100) + '%</span>'
          + '</fieldset>';
      });
      html += '</div></details>';
      first = false;
    });
    gamesEl.innerHTML = html;
  }

  function syncBoardChecks() {
    gamesEl.querySelectorAll('input[data-game]').forEach((input) => {
      input.checked = state[Number(input.dataset.game)] === input.value;
    });
  }

  function renderOdds() {
    const rows = runSims().sort((a, b) => b.expWins - a.expWins || b.playoff - a.playoff
      || a.team.tid - b.team.tid);
    const n = tidList.length;
    let maxSeed = 0;
    rows.forEach((r) => r.seeds.forEach((p) => { if (p > maxSeed) maxSeed = p; }));
    let html = '<div class="table-wrap"><table class="wo-table">'
      + '<caption class="sr-only">Re-simulated playoff odds and seed distribution per team</caption>'
      + '<thead><tr><th scope="col">Team</th><th scope="col">Now</th><th scope="col">Proj W</th>'
      + '<th scope="col">Playoff %</th>';
    for (let s = 1; s <= n; s += 1) html += '<th scope="col" class="wo-seed-th">' + s + '</th>';
    html += '</tr></thead><tbody>';
    rows.forEach((r) => {
      const t = r.team;
      html += '<tr><th scope="row" class="wo-team-th">' + teamDot(t.tid) + escapeHtml(t.abbrev) + '</th>'
        + '<td>' + t.record.w + '-' + t.record.l + '</td>'
        + '<td>' + r.expWins.toFixed(1) + '</td>'
        + '<td style="' + heatStyle(r.playoff, 0, 1, 1) + '">' + fmtPct(r.playoff) + '</td>';
      r.seeds.forEach((p) => {
        // Blank out sub-0.5% cells (matches the server's seed-table convention),
        // scale the tint to the table's most likely seed so the mode pops green.
        if (p < 0.005) {
          html += '<td class="wo-seed-cell muted">·</td>';
        } else {
          html += '<td class="wo-seed-cell" style="' + heatStyle(p, 0, maxSeed, 1) + '">'
            + Math.round(p * 100) + '</td>';
        }
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>'
      + '<p class="tool-note muted">Seed columns show the share of simulations ending at each seed, in percent. '
      + 'Top four seeds make the playoffs.</p>';
    oddsEl.innerHTML = html;
    const locked = state.filter((s) => s !== 's').length;
    if (countEl) countEl.textContent = locked ? locked + ' of ' + state.length + ' games locked' : '';
  }

  function scheduleUpdate() {
    if (pending) return;
    pending = true;
    // Batch rapid pick changes into one 5,000-sim run per tick. setTimeout, not
    // requestAnimationFrame: rAF stalls in hidden/background tabs and the odds
    // would silently never refresh.
    window.setTimeout(() => {
      pending = false;
      renderOdds();
    }, 30);
  }

  gamesEl.addEventListener('change', (event) => {
    const input = event.target.closest('input[data-game]');
    if (!input) return;
    state[Number(input.dataset.game)] = input.value;
    syncHash();
    scheduleUpdate();
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      state = state.map(() => 's');
      syncHash();
      syncBoardChecks();
      scheduleUpdate();
    });
  }

  fetch(root + 'assets/app-data.json')
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((data) => {
      payload = data;
      teams = data.teams;
      tidList = teams.map((t) => t.tid);
      tidList.forEach((tid, i) => { tidIndex[tid] = i; });
      schedule = data.sim.schedule;
      const k = data.sim.logistic_k;
      const hca = data.sim.hca;
      const strengths = data.sim.strengths;
      pHome = schedule.map((g) => {
        const diff = (strengths[String(g[1])] || 0) - (strengths[String(g[2])] || 0) + hca;
        return 1 / (1 + Math.exp(-diff * k));
      });
      state = schedule.map(() => 's');
      readHash();
      renderBoard();
      renderOdds();
    })
    .catch(() => {
      gamesEl.innerHTML = '<p class="muted">Could not load the schedule (assets/app-data.json). Reload to try again.</p>';
      oddsEl.innerHTML = '<p class="muted">—</p>';
    });
})();
