/* SMP League site. One data file (data/league.json), hash routes, no framework. */
(() => {
  const $app = document.getElementById('app');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const f1 = (x) => (Number.isFinite(x) ? x.toFixed(1) : '—');
  const pct = (m, a) => (a ? (100 * m / a).toFixed(1) : '—');
  const sgn = (x, d = 0) => (x > 0 ? '+' : '') + x.toFixed(d);
  const ord = (n) => n + (n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th');
  const htS = (i) => (i ? `${Math.floor(i / 12)}′${i % 12}″` : '—');
  const ZONES = [['At rim', 'fgAtRim', 'fgaAtRim'], ['Low post', 'fgLowPost', 'fgaLowPost'], ['Mid-range', 'fgMidRange', 'fgaMidRange'], ['Three', 'tp', 'tpa']];
  const SUM = ['min', 'pts', 'ast', 'stl', 'blk', 'tov', 'fg', 'fga', 'tp', 'tpa', 'ft', 'fta', 'pm', 'orb', 'drb', 'pf', 'gs', 'fgAtRim', 'fgaAtRim', 'fgLowPost', 'fgaLowPost', 'fgMidRange', 'fgaMidRange'];

  let D, T, P, C, byGid, lastDay, rec, stats, tstat, odds, move, R = {};

  /* ---------- derived data ---------- */
  const blank = () => Object.assign({ gp: 0, reb: 0 }, Object.fromEntries(SUM.map((k) => [k, 0])));
  const add = (s, r) => { s.gp++; for (const k of SUM) s[k] += r[C[k]]; s.reb += r[C.orb] + r[C.drb]; return s; };
  const gmsc = (r) => r[C.pts] + 0.4 * r[C.fg] - 0.7 * r[C.fga] - 0.4 * (r[C.fta] - r[C.ft]) + 0.7 * r[C.orb] + 0.3 * r[C.drb] + r[C.stl] + 0.7 * r[C.ast] + 0.7 * r[C.blk] - 0.4 * r[C.pf] - r[C.tov];
  const tot = (side, k) => side.box.reduce((a, r) => a + r[C[k]], 0);
  const phi = (z) => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; };

  function derive() {
    T = D.teams; P = new Map(D.players.map((p) => [p.pid, p]));
    C = Object.fromEntries(D.cols.map((c, i) => [c, i + 1]));
    byGid = new Map(D.games.map((g) => [g.gid, g]));
    lastDay = Math.max(...D.games.map((g) => g.day));
    rec = T.map(() => ({ w: 0, l: 0, hw: 0, hl: 0, aw: 0, al: 0, pf: 0, pa: 0, res: [] }));
    tstat = T.map(() => ({ me: blank(), op: blank() }));
    stats = new Map();
    for (const g of D.games) {
      for (const [me, op, home] of [[g.home, g.away, true], [g.away, g.home, false]]) {
        const r = rec[me.tid], won = me.pts > op.pts;
        r[won ? 'w' : 'l']++; r[(home ? 'h' : 'a') + (won ? 'w' : 'l')]++; r.pf += me.pts; r.pa += op.pts; r.res.push(won ? 'W' : 'L');
        tstat[me.tid].me.gp++; tstat[me.tid].op.gp++;
        for (const row of me.box) {
          const s = stats.get(row[0]) ?? stats.set(row[0], Object.assign(blank(), { tid: me.tid })).get(row[0]);
          add(s, row); s.tid = me.tid;
          for (const k of SUM) tstat[me.tid].me[k] += row[C[k]];
          tstat[me.tid].me.reb += row[C.orb] + row[C.drb];
        }
        for (const row of op.box) { for (const k of SUM) tstat[me.tid].op[k] += row[C[k]]; tstat[me.tid].op.reb += row[C.orb] + row[C.drb]; }
      }
    }
    const prev = T.map(() => ({ w: 0, l: 0, d: 0 }));
    for (const g of D.games) if (g.day < lastDay) for (const [me, op] of [[g.home, g.away], [g.away, g.home]]) { prev[me.tid][me.pts > op.pts ? 'w' : 'l']++; prev[me.tid].d += me.pts - op.pts; }
    const po = T.map((t) => t.tid).sort((a, b) => prev[b].w / Math.max(1, prev[b].w + prev[b].l) - prev[a].w / Math.max(1, prev[a].w + prev[a].l) || prev[b].d - prev[a].d), now = order();
    move = T.map((t) => po.indexOf(t.tid) - now.indexOf(t.tid));   // positive = climbed since the last game day
    odds = playoffOdds();
  }
  let DIST = null;
  const HK = { min: (s) => per(s, 'min'), pts: (s) => per(s, 'pts'), reb: (s) => per(s, 'reb'), ast: (s) => per(s, 'ast'), stl: (s) => per(s, 'stl'), blk: (s) => per(s, 'blk'), tov: (s) => per(s, 'tov'),
    fgp: (s) => (s.fga >= 2 * s.gp ? s.fg / s.fga : null), tpp: (s) => (s.tpa >= s.gp ? s.tp / s.tpa : null), ftp: (s) => (s.fta >= s.gp ? s.ft / s.fta : null), pm: (s) => per(s, 'pm') };
  const rankIn = (arr, v) => { let lo = 0, hi = 0; for (const y of arr) { if (y < v) lo++; if (y <= v) hi++; } return arr.length ? (lo + hi) / 2 / arr.length : 0.5; };
  const tintOf = (p) => `background:color-mix(in srgb, var(${p >= 0.5 ? '--up' : '--bad'}) ${(Math.abs(p - 0.5) * 64).toFixed(0)}%, transparent)`;
  function heat(k, s, low) {   // style for a table cell: how a player's per-game number ranks among everyone who has played three games
    DIST ??= Object.fromEntries(Object.keys(HK).map((key) => [key, [...stats.values()].filter((x) => x.gp >= 3).map(HK[key]).filter((v) => v != null)]));
    const v = HK[k](s); if (v == null) return '';
    const p = rankIn(DIST[k], v); return ` style="${tintOf(low ? 1 - p : p)}"`;
  }
  const team = (tid) => T[tid];
  const gpT = (tid) => rec[tid].w + rec[tid].l;
  const streakTxt = (tid) => { const s = streak(tid), n = +s.slice(1); return n >= 2 ? `${s[0] === 'W' ? 'Won' : 'Lost'} ${n} straight` : ''; };
  const banners = (t) => (t.banners && t.banners.length ? `<div class="banners">${t.banners.map((y) => `<span style="background:${t.color};border-color:${t.accent}"><b>${esc(y)}</b>Champions</span>`).join('')}</div>` : '');
  const recStr = (tid) => `${rec[tid].w}-${rec[tid].l}`;
  const streak = (tid) => { const r = rec[tid].res; if (!r.length) return '—'; let n = 0; for (let i = r.length - 1; i >= 0 && r[i] === r.at(-1); i--) n++; return r.at(-1) + n; };
  const last10 = (tid) => { const r = rec[tid].res.slice(-10); return `${r.filter((x) => x === 'W').length}-${r.filter((x) => x === 'L').length}`; };
  const diff = (tid) => (rec[tid].pf - rec[tid].pa) / Math.max(1, gpT(tid));
  const order = () => T.map((t) => t.tid).sort((a, b) => rec[b].w / Math.max(1, gpT(b)) - rec[a].w / Math.max(1, gpT(a)) || diff(b) - diff(a));
  const gb = (tid, lead) => { const v = ((rec[lead].w - rec[tid].w) + (rec[tid].l - rec[lead].l)) / 2; return v ? String(v) : '—'; };
  const short = (n) => { const p = n.split(' '); return p.length > 1 ? `${p[0][0]}. ${p.slice(1).join(' ')}` : n; };
  const per = (s, k) => s[k] / s.gp;
  const qualified = () => [...stats.entries()].filter(([, s]) => s.gp >= Math.max(3, lastDay * 0.4));
  function rankOf(pid, f) { const q = qualified().map(([id, s]) => [id, f(s)]).sort((a, b) => b[1] - a[1]); const i = q.findIndex((x) => x[0] === pid); return i < 0 ? null : i + 1; }
  function teamRank(tid, f, asc) { const v = T.map((t) => [t.tid, f(t.tid)]).sort((a, b) => (asc ? a[1] - b[1] : b[1] - a[1])); return v.findIndex((x) => x[0] === tid) + 1; }

  /* playoff odds: 3,000 seeded sims of the remaining schedule from each team's shrunk point differential */
  function playoffOdds() {
    let a = 20270; const rnd = () => { a = (a + 0x6d2b79f5) | 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    const rt = T.map((t) => diff(t.tid) * gpT(t.tid) / (gpT(t.tid) + 8)), N = 3000, made = T.map(() => 0), wins = T.map(() => 0), champ = T.map(() => 0);
    const pr = D.schedule.map((s) => phi((rt[s.home] - rt[s.away] + 2.5) / 12));
    const series = (hi, lo) => { let a = 0, b = 0; for (const home of [1, 1, 0, 0, 1]) { if (rnd() < phi((rt[hi] - rt[lo] + (home ? 2.5 : -2.5)) / 12)) a++; else b++; if (a === 3 || b === 3) break; } return a === 3 ? hi : lo; };   // best of five, 2-2-1
    for (let i = 0; i < N; i++) {
      const w = T.map((t) => rec[t.tid].w + rnd() * 0.01);
      D.schedule.forEach((s, j) => { w[rnd() < pr[j] ? s.home : s.away]++; });
      const sd = T.map((t) => t.tid).sort((x, y) => w[y] - w[x]).slice(0, 4);
      sd.forEach((tid) => made[tid]++);
      const s1 = series(sd[0], sd[3]), s2 = series(sd[1], sd[2]);
      champ[sd.indexOf(s1) < sd.indexOf(s2) ? series(s1, s2) : series(s2, s1)]++;
      w.forEach((v, tid) => { wins[tid] += Math.floor(v); });
    }
    return T.map((t) => ({ p: made[t.tid] / N, w: wins[t.tid] / N, c: champ[t.tid] / N }));
  }
  const arrow = (tid) => (move[tid] > 0 ? `<span class="mv up">▲ ${move[tid]}</span>` : move[tid] < 0 ? `<span class="mv dn">▼ ${-move[tid]}</span>` : '<span class="mv"></span>');
  const recPl = (tid) => `${recStr(tid)} (${ord(order().indexOf(tid) + 1)})`;
  const pctStr = (p) => (p > 0.9995 ? '>99.9%' : p < 0.0005 ? '<0.1%' : (100 * p).toFixed(1) + '%');
  const oddsStr = (tid) => pctStr(odds[tid].p);

  /* game flow from the score timeline [sec, away, home] */
  function flow(g) {
    const total = 2880 + 300 * g.ot, tl = [[0, 0, 0], ...g.tl], f = { total, bigA: 0, bigH: 0, changes: 0, ties: 0, ledA: 0, ledH: 0, series: [] };
    let prev = 0;
    for (let i = 0; i < tl.length; i++) {
      const [t, a, h] = tl[i], lead = h - a, end = i + 1 < tl.length ? tl[i + 1][0] : total;
      f.bigA = Math.max(f.bigA, -lead); f.bigH = Math.max(f.bigH, lead);
      if (lead > 0) f.ledH += end - t; else if (lead < 0) f.ledA += end - t;
      if (lead === 0 && i) f.ties++;
      if (lead && prev && Math.sign(lead) !== Math.sign(prev)) f.changes++;
      if (lead) prev = lead;
    }
    const M = D.wp, wp = (t, lead) => { if (t >= total) return lead > 0 ? 1 : lead < 0 ? 0 : 0.5; const fr = (t < 2880 ? 2880 - t : total - t) / 2880; return phi((lead + M.hca * fr) / Math.sqrt(M.sd * M.sd * fr + M.kappa)); };
    f.series = tl.map(([t, a, h]) => [t, a, h, wp(t, h - a)]);
    for (let t = 240; t < total; t += 240) { const e = tl.findLast((x) => x[0] <= t); f.series.push([t, e[1], e[2], wp(t, e[2] - e[1])]); }   // a point every four minutes so quiet stretches still drift
    f.series.sort((x, y) => x[0] - y[0]); f.series.push([total, g.away.pts, g.home.pts, 0]);
    // display curve: the model sampled every 12 s, averaged over 24 s either side (less near the ends, so it still starts and finishes true)
    const at = (t) => { const e = tl.findLast((x) => x[0] <= t) || tl[0]; return wp(t, e[2] - e[1]); }, grid = [];
    for (let t = 0; t <= total; t += 12) grid.push([t, at(Math.min(t, total - 0.5))]);
    f.curve = grid.map(([t], k) => { const w = Math.round(Math.min(24, t, total - t) / 12); let s = 0; for (let m = k - w; m <= k + w; m++) s += grid[m][1]; return [t, s / (2 * w + 1)]; });
    f.curve.push([total, g.home.pts > g.away.pts ? 1 : 0]);
    f.series[f.series.length - 1][3] = g.home.pts > g.away.pts ? 1 : 0;
    return f;
  }
  const clock = (t, total) => { if (t >= total) return 'Final'; const q = t < 2880 ? Math.floor(t / 720) : 4 + Math.floor((t - 2880) / 300), len = q < 4 ? 720 : 300, into = q < 4 ? t - q * 720 : (t - 2880) % 300, rem = len - into; return `${q < 4 ? 'Q' + (q + 1) : 'OT' + (q > 4 ? q - 3 : '')} ${Math.floor(rem / 60)}:${String(Math.floor(rem % 60)).padStart(2, '0')}`; };

  /* ---------- atoms ---------- */
  const logo = (tid, size = 26) => `<img class="logo" src="${team(tid).logo}" width="${size}" height="${size}" alt="${esc(team(tid).region)} ${esc(team(tid).name)}">`;
  function face(pid, size = 32) {
    const p = P.get(pid), ini = esc((p?.name || '?').split(' ').map((x) => x[0]).join('').slice(0, 2));
    const img = p?.espn ? `<img src="https://a.espncdn.com/i/headshots/nba/players/full/${p.espn}.png" alt="" loading="lazy" onerror="this.outerHTML='<span class=&quot;ini&quot;>${ini}</span>'">` : `<span class="ini">${ini}</span>`;
    return `<span class="face" style="width:${size}px;height:${size}px">${img}</span>`;
  }
  const pface = (pid, size = 32) => { const p = P.get(pid), b = Math.max(14, Math.round(size * 0.4)); return `<span class="pf" style="width:${size}px;height:${size}px">${face(pid, size)}${p && p.tid >= 0 ? `<img class="fb" src="${team(p.tid).logo}" width="${b}" height="${b}" alt="">` : ''}</span>`; };
  const card = (title, body, meta = '', cls = '') => `<section class="card ${cls}"><div class="ch"><h2>${title}</h2>${meta}</div>${body}</section>`;
  const plink = (pid, text) => `<a href="#player-${pid}">${esc(text ?? P.get(pid)?.name)}</a>`;
  const tname = (tid) => `${esc(team(tid).region)} ${esc(team(tid).name)}`;
  const tlink = (tid, inner) => `<a href="#team-${team(tid).abbrev}">${inner}</a>`;
  const fin = (g) => `Final${g.ot ? `/${g.ot > 1 ? g.ot : ''}OT` : ''}`;
  const lrow = (pid, s, v, i, sub) => `<a class="row r-lead${i ? '' : ' first'}" href="#player-${pid}"><span class="n">${i + 1}</span>${face(pid)}<span class="who"><b>${esc(P.get(pid).name)}</b><span>${sub ?? `${team(s.tid).abbrev} · ${P.get(pid).pos}`}</span></span><span class="v">${v}</span></a>`;
  const line = (r) => `${r[C.pts]} pts, ${r[C.orb] + r[C.drb]} reb, ${r[C.ast]} ast`;
  const allRows = (g) => [...g.home.box.map((r) => [r, g.home.tid, g]), ...g.away.box.map((r) => [r, g.away.tid, g])];

  /* ---------- game cards ---------- */
  function gameCard(g) {
    const row = (s, o) => `<div class="gr${s.pts < o.pts ? ' lost' : ''}">${logo(s.tid)}<span class="tn">${esc(team(s.tid).name)}<small>${recPl(s.tid)}</small></span><span class="sc">${s.pts}</span></div>`;
    const [r] = allRows(g).sort((a, b) => gmsc(b[0]) - gmsc(a[0]))[0];
    return `<a class="card gc" href="#game-${g.gid}"><div class="ch"><h2>Game ${g.day}${g.ot ? ` · ${g.ot > 1 ? g.ot : ''}OT` : ''}</h2><span>Box score</span></div>${row(g.away, g.home)}${row(g.home, g.away)}<div class="gf">${face(r[0], 24)}<span><b>${esc(short(P.get(r[0]).name))}</b> ${line(r)}</span></div></a>`;
  }
  function upCard(s) {
    const row = (tid) => `<div class="gr">${logo(tid)}<span class="tn">${esc(team(tid).name)}<small>${recStr(tid)}</small></span><span class="sc"></span></div>`;
    return `<div class="card gc"><div class="ch"><h2>Upcoming</h2><span>Game ${s.day}</span></div>${row(s.away)}${row(s.home)}<div class="gf"><span>Line: <b>${spread(s)}</b></span></div></div>`;
  }
  const power = (tid) => diff(tid) * gpT(tid) / (gpT(tid) + 8);
  const spread = (s) => { const x = Math.round((power(s.home) - power(s.away) + 2.5) * 2) / 2; return x ? `${team(x > 0 ? s.home : s.away).abbrev} -${Math.abs(x).toFixed(1)}` : 'Pick ’em'; };
  const strip = (day) => `<div class="strip">${D.games.filter((g) => g.day === day).map((g) => { const ln = (s, o) => `<span class="ln${s.pts < o.pts ? ' lost' : ''}">${logo(s.tid, 18)}<span>${team(s.tid).abbrev}</span><b>${s.pts}</b></span>`;
    return `<a href="#game-${g.gid}"><span class="st">Game ${g.day}${g.ot ? ` · ${g.ot > 1 ? g.ot : ''}OT` : ''}</span>${ln(g.away, g.home)}${ln(g.home, g.away)}</a>`; }).join('')}</div>`;

  /* ---------- shared blocks ---------- */
  function standingsMini() {
    const o = order();
    return card('Standings', `<table class="mini"><thead><tr><th class="t">Team</th><th>W</th><th>L</th><th>GB</th><th>Playoffs</th><th>Title</th></tr></thead><tbody>${o.map((tid, i) =>
      `<tr${i === 3 ? ' class="cut"' : ''}><td class="t nm">${arrow(tid)}${tlink(tid, `${logo(tid, 20)}${esc(team(tid).name)}`)}</td><td>${rec[tid].w}</td><td>${rec[tid].l}</td><td>${gb(tid, o[0])}</td><td>${oddsStr(tid)}</td><td>${pctStr(odds[tid].c)}</td></tr>`).join('')}</tbody></table>`, '<a href="#standings">Full table</a>');
  }
  const CATS = [['Points', 'PTS', (s) => per(s, 'pts')], ['Rebounds', 'REB', (s) => per(s, 'reb')], ['Assists', 'AST', (s) => per(s, 'ast')], ['Steals', 'STL', (s) => per(s, 'stl')], ['Blocks', 'BLK', (s) => per(s, 'blk')],
    ['3-point %', '3P%', (s) => (s.tpa >= 3 * s.gp ? 100 * s.tp / s.tpa : -99)], ['Offensive BPM', 'oBPM', (s, p) => (p.adv ? p.adv[6] : -99)], ['Defensive BPM', 'dBPM', (s, p) => (p.adv ? p.adv[7] : -99)]];
  const topN = (f, n) => qualified().map(([pid, s]) => [pid, s, f(s, P.get(pid))]).filter((x) => x[2] > -90).sort((a, b) => b[2] - a[2]).slice(0, n);
  function injuryCard(tid, wide) {
    const out = D.players.filter((p) => p.inj && p.tid >= 0 && (tid == null || p.tid === tid)).sort((a, b) => b.inj[1] - a.inj[1]);
    const rows = out.map((p) => `<a class="row r-news" href="#player-${p.pid}">${face(p.pid)}<span class="who"><b>${esc(p.name)}</b><span>${team(p.tid).abbrev} · ${esc(p.inj[0])}</span></span><span class="v" style="font-size:13px;font-weight:500">${p.inj[1]} g</span></a>`).join('');
    return card('Injury report', rows ? (wide ? `<div class="injgrid">${rows}</div>` : rows) : '<p class="note">Nobody is hurt.</p>', `<span>${out.length} out · games remaining</span>`);
  }
  function teamStatsTable() {
    const ma = (m, a, g) => `${f1(m / g)}-${f1(a / g)}`;
    const V = { pf: (t) => tstat[t].me.pts / gpT(t), pa: (t) => tstat[t].op.pts / gpT(t), fgp: (t) => tstat[t].me.fg / tstat[t].me.fga, tpp: (t) => tstat[t].me.tp / tstat[t].me.tpa, ftp: (t) => tstat[t].me.ft / tstat[t].me.fta,
      reb: (t) => tstat[t].me.reb / gpT(t), ast: (t) => tstat[t].me.ast / gpT(t), tov: (t) => tstat[t].me.tov / gpT(t), stl: (t) => tstat[t].me.stl / gpT(t), blk: (t) => tstat[t].me.blk / gpT(t) };
    const all = Object.fromEntries(Object.keys(V).map((k) => [k, T.map((t) => V[k](t.tid))]));
    const h = (k, tid, low) => { const p = rankIn(all[k], V[k](tid)); return ` style="${tintOf(low ? 1 - p : p)}"`; };
    const rows = order().map((tid) => { const m = tstat[tid].me, o = tstat[tid].op, g = m.gp;
      return `<tr><td class="t nm">${tlink(tid, `${logo(tid, 20)}${esc(team(tid).name)}`)}</td><td class="grp"${h('pf', tid)}><b>${f1(m.pts / g)}</b></td><td${h('pa', tid, 1)}>${f1(o.pts / g)}</td><td class="grp">${ma(m.fg, m.fga, g)}</td><td${h('fgp', tid)}><b>${pct(m.fg, m.fga)}</b></td><td class="grp">${ma(m.tp, m.tpa, g)}</td><td${h('tpp', tid)}><b>${pct(m.tp, m.tpa)}</b></td><td class="grp">${ma(m.ft, m.fta, g)}</td><td${h('ftp', tid)}><b>${pct(m.ft, m.fta)}</b></td><td class="grp"${h('reb', tid)}>${f1(m.reb / g)}</td><td${h('ast', tid)}>${f1(m.ast / g)}</td><td${h('tov', tid, 1)}>${f1(m.tov / g)}</td><td${h('stl', tid)}>${f1(m.stl / g)}</td><td${h('blk', tid)}>${f1(m.blk / g)}</td></tr>`; }).join('');
    return card('Team stats', `<div class="scroll"><table><thead><tr><th class="t">Team</th><th class="grp">PF</th><th>PA</th><th class="grp">FG</th><th>FG%</th><th class="grp">3P</th><th>3P%</th><th class="grp">FT</th><th>FT%</th><th class="grp">REB</th><th>AST</th><th>TO</th><th>STL</th><th>BLK</th></tr></thead><tbody>${rows}</tbody></table></div>`, '<span>Per game</span>');
  }

  /* ---------- win probability chart ---------- */
  function wpChart(g, f, h = 190) {
    const W = 1000, x = (t) => t / f.total * W, y = (p) => p * h, c = f.curve.map(([t, p]) => [x(t), y(p)]);
    const pts = c.map(([px, py], k) => { if (!k) return `${px.toFixed(1)},${py.toFixed(1)}`; const p0 = c[Math.max(0, k - 2)], p1 = c[k - 1], p3 = c[Math.min(c.length - 1, k + 1)];
      return `C${(p1[0] + (px - p0[0]) / 6).toFixed(1)},${(p1[1] + (py - p0[1]) / 6).toFixed(1)} ${(px - (p3[0] - p1[0]) / 6).toFixed(1)},${(py - (p3[1] - p1[1]) / 6).toFixed(1)} ${px.toFixed(1)},${py.toFixed(1)}`; }).join(' ');
    const area = `M0,${h / 2} L${pts} L${W},${h / 2} Z`, id = 'c' + g.gid;
    const qs = [720, 1440, 2160, ...(g.ot ? [2880] : [])].map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="0" y2="${h}" stroke="var(--line)"/>`).join('');
    return `<svg viewBox="0 0 ${W} ${h}" preserveAspectRatio="none" data-wp="${g.gid}" role="img" aria-label="Win probability over the game">
      <defs><clipPath id="${id}a"><rect width="${W}" height="${h / 2}"/></clipPath><clipPath id="${id}h"><rect y="${h / 2}" width="${W}" height="${h / 2}"/></clipPath></defs>
      ${qs}<path d="${area}" fill="var(--away)" opacity=".35" clip-path="url(#${id}a)"/><path d="${area}" fill="var(--home)" opacity=".35" clip-path="url(#${id}h)"/>
      <line x1="0" x2="${W}" y1="${h / 2}" y2="${h / 2}" stroke="var(--faint)" stroke-dasharray="3 5"/><path d="M${pts}" fill="none" stroke="var(--ink)" stroke-width="2" vector-effect="non-scaling-stroke"/>
      <line class="cur" y1="0" y2="${h}" stroke="var(--gold)" vector-effect="non-scaling-stroke" visibility="hidden"/></svg>`;
  }
  function wpCard(g, f) {
    const a = team(g.away.tid), h = team(g.home.tid);
    return card('Win probability', `<div class="wp"><div class="read"><span>▲ ${a.abbrev}</span><span id="wpread">Hover the chart to follow the game</span><span>${h.abbrev} ▼</span></div>${wpChart(g, f)}
      <div class="qs">${['Q1', 'Q2', 'Q3', 'Q4'].map((q) => `<span style="grid-column:span 12">${q}</span>`).join('')}${Array.from({ length: g.ot }, (_, i) => `<span style="grid-column:span 5">OT${i ? i + 1 : ''}</span>`).join('')}</div></div>
      <div class="kv"><div><b>${Math.max(f.bigA, 0)}</b><span>${a.abbrev} largest lead</span></div><div><b>${Math.max(f.bigH, 0)}</b><span>${h.abbrev} largest lead</span></div><div><b>${f.changes}</b><span>Lead changes</span></div><div><b>${f.ties}</b><span>Ties</span></div></div>`);
  }
  function wireWp(g, f) {
    const svg = document.querySelector(`[data-wp="${g.gid}"]`), out = document.getElementById('wpread'); if (!svg || !out) return;
    const cur = svg.querySelector('.cur'), a = team(g.away.tid).abbrev, h = team(g.home.tid).abbrev;
    svg.addEventListener('pointermove', (e) => { const b = svg.getBoundingClientRect(), fr = Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)), s = f.series.findLast((x) => x[0] <= fr * f.total) || f.series[0];
      cur.setAttribute('x1', fr * 1000); cur.setAttribute('x2', fr * 1000); cur.setAttribute('visibility', 'visible');
      out.innerHTML = `${clock(s[0], f.total)} · ${a} <b>${s[1]}</b> – <b>${s[2]}</b> ${h} · <b>${s[3] >= 0.5 ? h : a} ${(100 * Math.max(s[3], 1 - s[3])).toFixed(1)}%</b>`; });
    svg.addEventListener('pointerleave', () => { cur.setAttribute('visibility', 'hidden'); out.textContent = 'Hover the chart to follow the game'; });
  }

  /* ---------- home ---------- */
  const recapLead = (r) => { const lead = byGid.get(r.games[0]?.gid); return `--away:${lead ? team(lead.away.tid).accent : '#444'};--home:${lead ? team(lead.home.tid).accent : '#444'}`; };
  function recap() {
    const r = R[lastDay]; if (!r) return '';
    return `<a class="card lede" href="#recap-${lastDay}" style="display:block;${recapLead(r)}"><div class="gh lede-top" style="border-bottom:0"><span class="kick">Game ${lastDay} recap</span><h1>${esc(r.headline)}</h1><p class="dek">${esc(r.dek)}</p><span class="more">Read the full recap →</span></div></a>`;
  }
  function recapPage(n) {
    const r = R[n]; if (!r) return notFound();
    const sc = (g) => { const w = g.home.pts > g.away.pts ? g.home : g.away, l = w === g.home ? g.away : g.home; return `${logo(w.tid, 18)}${team(w.tid).abbrev} ${w.pts}, ${team(l.tid).abbrev} ${l.pts}${g.ot ? ` · ${g.ot > 1 ? g.ot : ''}OT` : ''} · Box score`; };
    const others = Object.keys(R).map(Number).filter((x) => x !== n).sort((a, b) => b - a);
    $app.innerHTML = `<article class="card lede story" style="${recapLead(r)}"><div class="gh lede-top"><span class="kick">Game ${n} recap</span><h1>${esc(r.headline)}</h1><p class="dek">${esc(r.dek)}</p></div>
      <div class="art">${r.games.map((x) => { const g = byGid.get(x.gid); return g ? `<p><b class="dateline">${esc(team(g.home.tid).region)}</b> — ${esc(x.text)}</p><a class="slug" href="#game-${g.gid}">${sc(g)}</a>` : ''; }).join('')}</div></article>
      ${others.length ? `<p class="note" style="max-width:760px;margin:0 auto">Earlier recaps: ${others.map((x) => `<a href="#recap-${x}">Game ${x}</a>`).join(' · ')}</p>` : ''}`;
  }
  function around() {
    const out = [], rows = D.games.flatMap(allRows), best = new Map();
    for (const [r] of rows) best.set(r[0], Math.max(best.get(r[0]) || 0, r[C.pts]));
    const top = Math.max(...rows.map(([r]) => r[C.pts])), nm = (r) => esc(P.get(r[0]).name);
    T.map((t) => [t, streak(t.tid)]).filter(([, s]) => +s.slice(1) >= 3).sort((a, b) => +b[1].slice(1) - +a[1].slice(1)).slice(0, 4)
      .forEach(([t, s]) => out.push([logo(t.tid, 32), `The ${esc(t.name)} have ${s[0] === 'W' ? 'won' : 'lost'} ${s.slice(1)} straight`, `${recStr(t.tid)} · ${ord(order().indexOf(t.tid) + 1)} seed`, `#team-${t.abbrev}`]));
    const today = D.games.filter((g) => g.day === lastDay).flatMap(allRows).sort((a, b) => b[0][C.pts] - a[0][C.pts]);
    for (const [r, tid, g] of today) {
      const reb = r[C.orb] + r[C.drb], dbl = [r[C.pts], reb, r[C.ast], r[C.stl], r[C.blk]].filter((v) => v >= 10).length, vs = `${g.home.tid === tid ? 'vs' : '@'} ${team(g.home.tid === tid ? g.away.tid : g.home.tid).abbrev}`;
      if (dbl >= 3) out.push([face(r[0]), `${nm(r)} had a triple-double`, `${line(r)} ${vs}`, `#game-${g.gid}`]);
      else if (r[C.pts] === top) out.push([face(r[0]), `${nm(r)} set the league's season high with ${r[C.pts]}`, `${line(r)} ${vs}`, `#game-${g.gid}`]);
      else if (r[C.pts] >= 25 && r[C.pts] === best.get(r[0]) && stats.get(r[0]).gp >= 5) out.push([face(r[0]), `${nm(r)} scored a season-high ${r[C.pts]}`, `${line(r)} ${vs}`, `#game-${g.gid}`]);
    }
    return out.length ? card('Around the league', out.slice(0, 7).map(([img, a, b, href]) => `<a class="row r-news" href="${href}">${img}<span class="who"><b>${a}</b><span>${b}</span></span><span></span></a>`).join(''), `<span>After Game ${lastDay}</span>`) : '';
  }
  function home() {
    const today = D.games.filter((g) => g.day === lastDay), feat = [...today].sort((a, b) => { const fa = flow(a), fb = flow(b); return (fb.changes + fb.ties * 0.5 - Math.abs(b.home.pts - b.away.pts)) - (fa.changes + fa.ties * 0.5 - Math.abs(a.home.pts - a.away.pts)); })[0];
    const f = flow(feat), a = feat.away, h = feat.home, aw = a.pts > h.pts;
    const blk = (s, home, won) => `<div class="gt${home ? ' h' : ''}">${logo(s.tid, 64)}<div class="who"><b>${tname(s.tid)}</b><span>${recStr(s.tid)}</span></div><span class="big ${won ? '' : 'lost'}">${s.pts}</span></div>`;
    const best = allRows(feat).sort((x, y) => gmsc(y[0]) - gmsc(x[0])).slice(0, 3);
    const featured = `<section class="card" style="--away:${team(a.tid).accent};--home:${team(h.tid).accent}"><div class="ch"><h2>Game of the day</h2><a href="#game-${feat.gid}">Full box score</a></div>
      <a class="gh" href="#game-${feat.gid}" style="display:block"><div class="gh-in" style="--wa:url(${team(a.tid).logo});--wh:url(${team(h.tid).logo})">${blk(a, false, aw)}<div class="ls"><div class="sub">Game ${feat.day}<br>${esc(team(h.tid).arena)}</div></div>${blk(h, true, !aw)}</div></a>
      <div class="wp" style="border-top:1px solid var(--line)">${wpChart(feat, f, 110)}</div>
      <div class="grid g-3" style="gap:0;border-top:1px solid var(--line)">${best.map(([r, tid]) => `<a class="row r-news" style="border-bottom:0" href="#player-${r[0]}">${face(r[0])}<span class="who"><b>${esc(short(P.get(r[0]).name))}</b><span>${team(tid).abbrev} · ${line(r)}</span></span><span></span></a>`).join('')}</div></section>`;
    $app.innerHTML = `${strip(lastDay)}
      <div class="grid g-main"><div class="stack">${recap()}${featured}
        <div class="grid g-2">${today.filter((g) => g !== feat).map(gameCard).join('')}</div>
        ${teamStatsTable()}</div>
      <aside class="stack">${standingsMini()}${around()}${injuryCard(null)}</aside></div>`;
  }

  /* ---------- scores ---------- */
  function scoreRow(g) {
    const a = g.away, h = g.home, f = flow(g), qh = a.q.map((_, i) => (i < 4 ? i + 1 : 'OT'));
    const tr = (s, o) => `<tr class="${s.pts > o.pts ? 'won' : 'lost'}"><td class="t tm"><div class="tmw">${logo(s.tid, 30)}<span><b>${esc(team(s.tid).name)}</b><small>${recPl(s.tid)}</small></span></div></td>${s.q.map((x) => `<td>${x}</td>`).join('')}<td class="tt">${s.pts}</td></tr>`;
    const top = (s) => { const r = s.box.reduce((x, y) => (gmsc(y) > gmsc(x) ? y : x)); return `<a class="tp" href="#player-${r[0]}">${face(r[0], 38)}<span><b>${esc(short(P.get(r[0]).name))}</b> <small>${P.get(r[0]).pos} · ${team(s.tid).abbrev}</small><em>${r[C.pts]} PTS, ${r[C.orb] + r[C.drb]} REB, ${r[C.ast]} AST${r[C.stl] >= 3 ? `, ${r[C.stl]} STL` : ''}${r[C.blk] >= 3 ? `, ${r[C.blk]} BLK` : ''}</em></span></a>`; };
    const t = (s, k) => tot(s, k), st = (lab, fa, fh) => `<tr><td>${fa}</td><th>${lab}</th><td>${fh}</td></tr>`;
    return `<section class="card grow" style="--away:${team(a.tid).accent};--home:${team(h.tid).accent}">
      <a class="gcell ls2" href="#game-${g.gid}"><table><thead><tr><th class="t">${g.ot ? (g.ot > 1 ? g.ot : '') + 'OT' : ''}</th>${qh.map((q) => `<th>${q}</th>`).join('')}<th>T</th></tr></thead><tbody>${tr(a, h)}${tr(h, a)}</tbody></table></a>
      <a class="gcell" href="#game-${g.gid}"><span class="label">Win probability</span>${wpChart(g, f, 150)}<span class="cap">${f.changes} lead change${f.changes === 1 ? '' : 's'} · largest lead ${team(f.bigA > f.bigH ? a.tid : h.tid).abbrev} ${Math.max(f.bigA, f.bigH)}</span></a>
      <div class="gcell"><span class="label">Top performers</span>${top(a)}${top(h)}</div>
      <div class="gcell"><table class="ks"><thead><tr><td>${team(a.tid).abbrev}</td><th></th><td>${team(h.tid).abbrev}</td></tr></thead><tbody>${st('FG%', pct(t(a, 'fg'), t(a, 'fga')), pct(t(h, 'fg'), t(h, 'fga')))}${st('3PT', `${t(a, 'tp')}-${t(a, 'tpa')}`, `${t(h, 'tp')}-${t(h, 'tpa')}`)}${st('REB', t(a, 'orb') + t(a, 'drb'), t(h, 'orb') + t(h, 'drb'))}${st('AST', t(a, 'ast'), t(h, 'ast'))}${st('TO', t(a, 'tov'), t(h, 'tov'))}</tbody></table><a class="btn" href="#game-${g.gid}">Box score</a></div></section>`;
  }
  function upRow(s) {
    const tr = (tid) => `<tr><td class="t tm"><div class="tmw">${logo(tid, 30)}<span><b>${esc(team(tid).name)}</b><small>${recPl(tid)}</small></span></div></td></tr>`;
    const lead = (tid) => { const b = [...stats.entries()].filter(([, x]) => x.tid === tid && x.gp >= 3).sort((x, y) => per(y[1], 'pts') - per(x[1], 'pts'))[0]; return b ? `<a class="tp" href="#player-${b[0]}">${face(b[0], 38)}<span><b>${esc(short(P.get(b[0]).name))}</b> <small>${P.get(b[0]).pos} · ${team(tid).abbrev}</small><em>${f1(per(b[1], 'pts'))} PPG, ${f1(per(b[1], 'reb'))} RPG, ${f1(per(b[1], 'ast'))} APG</em></span></a>` : ''; };
    return `<section class="card grow up"><div class="gcell ls2"><table><thead><tr><th class="t">Upcoming</th></tr></thead><tbody>${tr(s.away)}${tr(s.home)}</tbody></table></div>
      <div class="gcell"><span class="label">Line</span><span class="line">${spread(s)}</span><span class="cap">${team(s.away).abbrev} at ${team(s.home).abbrev}</span></div>
      <div class="gcell"><span class="label">Leading scorers</span>${lead(s.away)}${lead(s.home)}</div><div class="gcell"></div></section>`;
  }
  function scores(day) {
    const days = [...new Set([...D.games.map((g) => g.day), ...D.schedule.map((s) => s.day)])].sort((a, b) => a - b);
    day = days.includes(day) ? day : lastDay;
    const games = D.games.filter((g) => g.day === day), up = D.schedule.filter((s) => s.day === day), i = days.indexOf(day);
    $app.innerHTML = `<div class="page-h"><h1>Scores</h1><span>Game ${day} of ${days.at(-1)}</span></div>
      <div class="days"><a class="btn" href="#scores-${days[Math.max(0, i - 1)]}" aria-label="Previous game">‹</a><div class="dayrail" id="rail">${days.map((d) => `<a href="#scores-${d}" class="${d > lastDay ? 'fut' : ''}" aria-current="${d === day}" aria-label="Game ${d}">${d}</a>`).join('')}</div><a class="btn" href="#scores-${days[Math.min(days.length - 1, i + 1)]}" aria-label="Next game">›</a></div>
      <div class="stack">${games.map(scoreRow).join('') + up.map(upRow).join('')}</div>`;
    document.querySelector('#rail [aria-current="true"]')?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }

  /* ---------- game ---------- */
  function boxTable(side) {
    const cols = ['MIN', 'PTS', 'FG', '3PT', 'FT', 'REB', 'AST', 'TO', 'STL', 'BLK', 'OREB', 'DREB', 'PF', '+/-'];
    const row = (r) => { const p = P.get(r[0]), pm = r[C.pm];
      return `<tr><td class="t nm">${plink(r[0], short(p.name))} <small>${p.pos}</small></td><td>${Math.round(r[C.min])}</td><td><b>${r[C.pts]}</b></td><td>${r[C.fg]}-${r[C.fga]}</td><td>${r[C.tp]}-${r[C.tpa]}</td><td>${r[C.ft]}-${r[C.fta]}</td><td>${r[C.orb] + r[C.drb]}</td><td>${r[C.ast]}</td><td>${r[C.tov]}</td><td>${r[C.stl]}</td><td>${r[C.blk]}</td><td>${r[C.orb]}</td><td>${r[C.drb]}</td><td>${r[C.pf]}</td><td class="${pm > 0 ? 'up' : pm < 0 ? 'dn' : ''}">${sgn(pm)}</td></tr>`; };
    const dnp = ([pid, why]) => `<tr><td class="t nm">${plink(pid, short(P.get(pid).name))} <small>${P.get(pid).pos}</small></td><td class="dnp" colspan="14">DNP - ${esc(why.toUpperCase())}</td></tr>`;
    const head = (lab) => `<tr class="sub"><th class="t">${lab}</th>${cols.map((c) => `<th>${c}</th>`).join('')}</tr>`, t = (k) => tot(side, k);
    return card(`${logo(side.tid, 22)}${tname(side.tid)}`, `<div class="scroll"><table class="box">
      <thead>${head('Starters')}</thead><tbody>${side.box.filter((r) => r[C.gs]).map(row).join('')}</tbody><thead>${head('Bench')}</thead><tbody>${side.box.filter((r) => !r[C.gs]).map(row).join('')}${side.dnp.map(dnp).join('')}
      <tr class="tot"><td class="t">Team</td><td></td><td>${t('pts')}</td><td>${t('fg')}-${t('fga')}</td><td>${t('tp')}-${t('tpa')}</td><td>${t('ft')}-${t('fta')}</td><td>${t('orb') + t('drb')}</td><td>${t('ast')}</td><td>${t('tov')}</td><td>${t('stl')}</td><td>${t('blk')}</td><td>${t('orb')}</td><td>${t('drb')}</td><td>${t('pf')}</td><td></td></tr>
      <tr class="pct"><td></td><td></td><td></td><td>${pct(t('fg'), t('fga'))}%</td><td>${pct(t('tp'), t('tpa'))}%</td><td>${pct(t('ft'), t('fta'))}%</td><td colspan="9"></td></tr></tbody></table></div>`, `<span>${recStr(side.tid)}</span>`);
  }
  const keys = (g) => `<div class="keys"><span>${logo(g.away.tid, 22)}<i class="sw" style="background:repeating-linear-gradient(-55deg,var(--away) 0 3px,transparent 3px 5px)"></i>${team(g.away.tid).abbrev}</span><span>${team(g.home.tid).abbrev}<i class="sw" style="background:var(--home)"></i>${logo(g.home.tid, 22)}</span></div>`;
  function gameLeaders(g) {
    const best = (side, f) => side.box.reduce((a, r) => (f(r) > f(a) ? r : a), side.box[0]);
    const cats = [['Points', (r) => r[C.pts], (r) => `${r[C.fg]}/${r[C.fga]} FG, ${r[C.ft]}/${r[C.fta]} FT`], ['Rebounds', (r) => r[C.orb] + r[C.drb], (r) => `${r[C.drb]} DREB, ${r[C.orb]} OREB`], ['Assists', (r) => r[C.ast], (r) => `${r[C.tov]} TO, ${Math.round(r[C.min])} MIN`]];
    const side = (s, f, ln, h) => { const r = best(s, f); return `<a class="p${h ? ' h' : ''}" href="#player-${r[0]}">${face(r[0], 40)}<b>${f(r)}</b><span class="nm1">${esc(short(P.get(r[0]).name))}</span><span class="ln1">${ln(r)}</span></a>`; };
    return card('Game leaders', keys(g) + cats.map(([lab, f, ln]) => `<div class="lead">${side(g.away, f, ln, false)}<span class="lab">${lab}</span>${side(g.home, f, ln, true)}</div>`).join(''));
  }
  function gameTeamStats(g, f) {
    const a = g.away, h = g.home, A = (k) => tot(a, k), H = (k) => tot(h, k);
    const pr = (lab, m, at) => { const pa = A(at) ? 100 * A(m) / A(at) : 0, ph = H(at) ? 100 * H(m) / H(at) : 0;
      return `<div class="ts"><div class="ts-top"><span class="v">${Math.round(pa)}%<small>${A(m)}-${A(at)}</small></span><span class="lab">${lab}</span><span class="v h"><small>${H(m)}-${H(at)}</small>${Math.round(ph)}%</span></div><div class="bars"><div class="track"><div class="fa" style="width:${pa}%"></div></div><div class="track h"><div class="fh" style="width:${ph}%"></div></div></div></div>`; };
    const cr = (lab, va, vh, sfx = '') => `<div class="ts"><div class="ts-top"><span class="v">${va}${sfx}</span><span class="lab">${lab}</span><span class="v h">${vh}${sfx}</span></div><div class="split"><div class="fa" style="flex:${+va || 0.01}"></div><div class="fh" style="flex:${+vh || 0.01}"></div></div></div>`;
    return card('Team stats', keys(g) + pr('Field goal %', 'fg', 'fga') + pr('Three point %', 'tp', 'tpa') + pr('Free throw %', 'ft', 'fta') + cr('Rebounds', A('orb') + A('drb'), H('orb') + H('drb')) + cr('Assists', A('ast'), H('ast')) + cr('Turnovers', A('tov'), H('tov')) + cr('Steals', A('stl'), H('stl')) + cr('Blocks', A('blk'), H('blk'))
      + cr('Percent led', Math.round(100 * f.ledA / f.total), Math.round(100 * f.ledH / f.total), '%') + cr('Largest lead', f.bigA, f.bigH));
  }
  function game(gid) {
    const g = byGid.get(gid); if (!g) return notFound();
    const a = g.away, h = g.home, ta = team(a.tid), th = team(h.tid), aw = a.pts > h.pts, f = flow(g);
    const qh = a.q.map((_, i) => (i < 4 ? i + 1 : `OT${i > 4 ? i - 3 : ''}`));
    const ls = `<table><thead><tr><th></th>${qh.map((q) => `<th>${q}</th>`).join('')}<th>T</th></tr></thead><tbody><tr><td class="t">${ta.abbrev}</td>${a.q.map((x) => `<td>${x}</td>`).join('')}<td>${a.pts}</td></tr><tr><td class="t">${th.abbrev}</td>${h.q.map((x) => `<td>${x}</td>`).join('')}<td>${h.pts}</td></tr></tbody></table>`;
    const blk = (s, home, won) => `<div class="gt${home ? ' h' : ''}">${tlink(s.tid, logo(s.tid, 76))}<div class="who"><b>${tlink(s.tid, tname(s.tid))}</b><span>${recStr(s.tid)} · ${home ? 'Home' : 'Away'}</span></div><span class="big ${won ? '' : 'lost'}">${s.pts}</span></div>`;
    $app.innerHTML = `<div style="--away:${ta.accent};--home:${th.accent}"><section class="card gh" style="margin-bottom:var(--gap)"><div class="gh-in" style="--wa:url(${ta.logo});--wh:url(${th.logo})">${blk(a, false, aw)}<div class="ls">${ls}<div class="sub">Game ${g.day} · ${esc(th.arena)}</div></div>${blk(h, true, !aw)}</div></section>
      <div class="grid g-game"><aside class="stack">${gameLeaders(g)}${gameTeamStats(g, f)}</aside><div class="stack">${wpCard(g, f)}${boxTable(a)}${boxTable(h)}</div></div></div>`;
    wireWp(g, f);
  }

  /* ---------- standings ---------- */
  function standings() {
    const o = order();
    const rows = o.map((tid, i) => { const r = rec[tid], gp = gpT(tid), d = diff(tid);
      return `<tr${i === 3 ? ' class="cut"' : ''}><td class="t muted">${arrow(tid)}${i + 1}</td><td class="t nm">${tlink(tid, `${logo(tid, 24)}${tname(tid)}`)}</td><td>${r.w}</td><td>${r.l}</td><td>${(r.w / Math.max(1, gp)).toFixed(3).replace(/^0/, '')}</td><td>${gb(tid, o[0])}</td><td>${r.hw}-${r.hl}</td><td>${r.aw}-${r.al}</td><td>${f1(r.pf / gp)}</td><td>${f1(r.pa / gp)}</td><td class="${d > 0 ? 'up' : 'dn'}">${sgn(d, 1)}</td><td>${streak(tid)}</td><td>${last10(tid)}</td><td>${f1(odds[tid].w)}</td><td><b>${oddsStr(tid)}</b></td><td><b>${pctStr(odds[tid].c)}</b></td></tr>`; }).join('');
    const h2h = (a, b) => { const ms = D.games.filter((g) => (g.home.tid === a && g.away.tid === b) || (g.home.tid === b && g.away.tid === a)); const w = ms.filter((g) => (g.home.tid === a ? g.home.pts > g.away.pts : g.away.pts > g.home.pts)).length; return ms.length ? `${w}-${ms.length - w}` : '·'; };
    $app.innerHTML = `<div class="page-h"><h1>Standings</h1><span>${D.season} · through Game ${lastDay} of 36</span></div><div class="stack">
      ${card('League table', `<div class="scroll"><table><thead><tr><th class="t">#</th><th class="t">Team</th><th>W</th><th>L</th><th>Pct</th><th>GB</th><th>Home</th><th>Away</th><th>PF</th><th>PA</th><th>Diff</th><th>Strk</th><th>L10</th><th>Proj W</th><th>Playoffs</th><th>Title</th></tr></thead><tbody>${rows}</tbody></table></div><p class="note">Top four make the playoffs (best of five). Arrows show movement since the last game. Projected wins, playoff chances and title chances come from 3,000 simulations of the remaining schedule and a best-of-five bracket, based on each team's point differential.</p>`)}
      ${card('Head to head', `<div class="scroll"><table class="h2h"><thead><tr><th class="t">Row vs column</th>${o.map((t) => `<th>${team(t).abbrev}</th>`).join('')}</tr></thead><tbody>${o.map((a) => `<tr><td class="t nm">${tlink(a, `${logo(a, 20)}${esc(team(a).name)}`)}</td>${o.map((b) => (a === b ? '<td class="x">—</td>' : `<td>${h2h(a, b)}</td>`)).join('')}</tr>`).join('')}</tbody></table></div>`)}
      ${teamStatsTable()}</div>`;
  }

  /* ---------- teams ---------- */
  function shotProfile(tid, roster) {
    const Z = [['Rim', 'fgAtRim', 'fgaAtRim'], ['Post', 'fgLowPost', 'fgaLowPost'], ['Mid', 'fgMidRange', 'fgaMidRange'], ['Three', 'tp', 'tpa']];
    const line = (label, s, g, cls = '') => { const fga = Math.max(1, s.fga);
      return `<div class="sp ${cls}"><span class="nm2">${label}</span><span class="n">${f1(s.fga / g)}</span><span class="mix">${Z.map(([, , a], i) => `<i class="z${i + 1}" style="width:${100 * s[a] / fga}%" title="${Z[i][0]}: ${(100 * s[a] / fga).toFixed(1)}% of shots"></i>`).join('')}</span>${Z.map(([, m, a], i) => `<span class="zc"><b>${(100 * s[a] / fga).toFixed(0)}%</b><small>${s[a] >= 5 ? pct(s[m], s[a]) : '—'}</small></span>`).join('')}</div>`; };
    const players = roster.filter(([, s]) => s && s.fga >= 10).sort((a, b) => b[1].fga / b[1].gp - a[1].fga / a[1].gp);
    return card('Shot profile', `<div class="sp head"><span class="nm2"></span><span class="n">FGA</span><span class="mix lg">${Z.map(([lab], i) => `<span><i class="sw z${i + 1}"></i>${lab}</span>`).join('')}</span>${Z.map(([lab]) => `<span class="zc"><b>${lab}</b><small>share · FG%</small></span>`).join('')}</div>
      ${line(`${logo(tid, 20)}<b>${esc(team(tid).name)}</b>`, tstat[tid].me, gpT(tid), 'tot')}
      ${players.map(([p, s]) => line(`<a href="#player-${p.pid}">${face(p.pid, 26)}<span>${esc(p.name)}</span></a>`, s, s.gp)).join('')}`, '<span>Where the shots come from, per game</span>');
  }
  function teamPage(abbrev) {
    const t = T.find((x) => x.abbrev === abbrev); if (!t) return notFound();
    const tid = t.tid, o = order(), r = rec[tid], gp = gpT(tid), m = tstat[tid].me, op = tstat[tid].op;
    const roster = D.players.filter((p) => p.tid === tid).map((p) => [p, stats.get(p.pid)]).sort((a, b) => (b[1] ? per(b[1], 'min') : -1) - (a[1] ? per(a[1], 'min') : -1));
    const starters = new Set(roster.filter(([, s]) => s).sort((a, b) => b[1].gs - a[1].gs || b[1].min - a[1].min).slice(0, 5).map(([p]) => p.pid));
    roster.sort((a, b) => starters.has(b[0].pid) - starters.has(a[0].pid));
    const rows = roster.map(([p, s], i) => `<tr${i === 4 ? ' class="cut"' : ''}><td class="t nm"><a href="#player-${p.pid}">${face(p.pid, 28)}<span>${esc(p.name)}</span>${p.inj ? `<span class="inj">out ${p.inj[1]}</span>` : ''}</a></td><td class="t"><span class="chip">${p.pos}</span></td><td>${p.age}</td><td>${htS(p.ht)}</td>${
      s ? `<td class="grp">${s.gp}</td><td>${s.gs}</td><td${heat('min', s)}>${f1(per(s, 'min'))}</td><td class="grp"${heat('pts', s)}><b>${f1(per(s, 'pts'))}</b></td><td${heat('reb', s)}>${f1(per(s, 'reb'))}</td><td${heat('ast', s)}>${f1(per(s, 'ast'))}</td><td${heat('stl', s)}>${f1(per(s, 'stl'))}</td><td${heat('blk', s)}>${f1(per(s, 'blk'))}</td><td${heat('tov', s, 1)}>${f1(per(s, 'tov'))}</td><td class="grp"${heat('fgp', s)}>${pct(s.fg, s.fga)}</td><td${heat('tpp', s)}>${pct(s.tp, s.tpa)}</td><td${heat('ftp', s)}>${pct(s.ft, s.fta)}</td><td class="grp"${heat('pm', s)}>${sgn(per(s, 'pm'), 1)}</td>` : '<td colspan="13" class="grp muted" style="text-align:center">Has not played</td>'}<td class="grp">${p.sal ? '$' + p.sal + 'M' : '—'}</td><td>${p.exp || '—'}</td></tr>`).join('');
    const prof = [['Points', (x) => tstat[x].me.pts / gpT(x), 0, f1], ['Points allowed', (x) => tstat[x].op.pts / gpT(x), 1, f1], ['Field goal %', (x) => 100 * tstat[x].me.fg / tstat[x].me.fga, 0, f1], ['Three point %', (x) => 100 * tstat[x].me.tp / tstat[x].me.tpa, 0, f1], ['Threes made', (x) => tstat[x].me.tp / gpT(x), 0, f1],
      ['Rebounds', (x) => tstat[x].me.reb / gpT(x), 0, f1], ['Assists', (x) => tstat[x].me.ast / gpT(x), 0, f1], ['Turnovers', (x) => tstat[x].me.tov / gpT(x), 1, f1], ['Steals', (x) => tstat[x].me.stl / gpT(x), 0, f1], ['Blocks', (x) => tstat[x].me.blk / gpT(x), 0, f1], ['Opp field goal %', (x) => 100 * tstat[x].op.fg / tstat[x].op.fga, 1, f1]];
    const profile = `<table><thead><tr><th class="t">Per game</th><th>Value</th><th>Rank</th></tr></thead><tbody>${prof.map(([lab, f, asc, fmt]) => { const rk = teamRank(tid, f, asc); return `<tr><td class="t" style="font-family:var(--f)">${lab}</td><td><b>${fmt(f(tid))}</b></td><td class="${rk <= 3 ? 'up' : rk >= 8 ? 'dn' : ''}">${ord(rk)}</td></tr>`; }).join('')}</tbody></table>`;
    const games = D.games.filter((g) => g.home.tid === tid || g.away.tid === tid).map((g) => { const hm = g.home.tid === tid, me = hm ? g.home : g.away, opp = hm ? g.away : g.home, w = me.pts > opp.pts, top = me.box.reduce((a, x) => (x[C.pts] > a[C.pts] ? x : a));
      return `<tr><td class="t"><a href="#game-${g.gid}">${g.day}</a></td><td class="t nm">${tlink(opp.tid, `${logo(opp.tid, 20)}<span>${hm ? 'vs' : '@'} ${esc(team(opp.tid).name)}</span>`)}</td><td class="t ${w ? 'up' : 'dn'}"><a href="#game-${g.gid}">${w ? 'W' : 'L'} ${me.pts}-${opp.pts}${g.ot ? ' OT' : ''}</a></td><td class="t" style="font-family:var(--f)">${plink(top[0], short(P.get(top[0]).name))} <span class="muted mono">${top[C.pts]}</span></td></tr>`; }).reverse();
    const next = D.schedule.filter((s) => s.home === tid || s.away === tid).slice(0, 5).map((s) => { const hm = s.home === tid, opp = hm ? s.away : s.home; return `<a class="row r-sched" href="#team-${team(opp).abbrev}"><span class="d">Game ${s.day}</span>${logo(opp, 20)}<span>${hm ? 'vs' : '@'} ${esc(team(opp).name)}</span><span class="res muted">${recStr(opp)}</span></a>`; }).join('');
    const tl = (lab, k, f = (s) => per(s, k)) => { const b = roster.filter(([, s]) => s && s.gp >= 3).sort((x, y) => f(y[1]) - f(x[1]))[0]; return b ? `<a class="row r-news" href="#player-${b[0].pid}">${face(b[0].pid)}<span class="who"><b>${esc(b[0].name)}</b><span>${lab}</span></span><span class="v">${f1(f(b[1]))}</span></a>` : ''; };
    const nm = (v, lab, rk) => `<div><b>${v}</b><span>${lab}</span>${rk ? `<small>${ord(rk)}</small>` : ''}</div>`;
    $app.innerHTML = `<section class="card hd" style="--c:${t.accent};--wm:url(${t.logo})">${logo(tid, 96)}<div><h1>${tname(tid)}</h1><div class="sub"><span>${recStr(tid)} · ${ord(o.indexOf(tid) + 1)} of 10 · ${gb(tid, o[0])} GB</span><span class="form">${r.res.slice(-10).map((x) => `<i class="${x}">${x}</i>`).join('')}</span>${streakTxt(tid) ? `<span>${streakTxt(tid)}</span>` : ''}</div><div class="sub"><span>Home: ${esc(t.arena)} (${r.hw}-${r.hl})</span></div>${banners(t)}</div>
      <div class="nums">${nm(f1(r.pf / gp), 'PF', teamRank(tid, (x) => rec[x].pf / gpT(x)))}${nm(f1(r.pa / gp), 'PA', teamRank(tid, (x) => rec[x].pa / gpT(x), 1))}${nm(sgn(diff(tid), 1), 'Diff', teamRank(tid, diff))}${nm(`${r.hw}-${r.hl}`, 'Home')}${nm(`${r.aw}-${r.al}`, 'Away')}${nm(oddsStr(tid), 'Playoffs')}${nm(pctStr(odds[tid].c), 'Title')}</div></section>
      ${card('Roster', `<div class="scroll"><table><thead><tr><th class="t">Player</th><th class="t">Pos</th><th>Age</th><th>Ht</th><th class="grp">GP</th><th>GS</th><th>MIN</th><th class="grp">PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th><th class="grp">FG%</th><th>3P%</th><th>FT%</th><th class="grp">+/-</th><th class="grp">Salary</th><th>Thru</th></tr></thead><tbody>${rows}</tbody></table></div>`, `<span>Starters above the line · payroll $${roster.reduce((a, [p]) => a + (p.sal || 0), 0)}M of $${D.cap}M cap</span>`)}
      <div style="margin-top:var(--gap)">${shotProfile(tid, roster)}</div>
      <div id="units" data-tid="${tid}" style="margin-top:var(--gap)"></div>
      <div class="grid g-main" style="margin-top:var(--gap)"><div class="stack">${card('Results', `<div class="scroll"><table><thead><tr><th class="t">Game</th><th class="t">Opponent</th><th class="t">Result</th><th class="t">Top scorer</th></tr></thead><tbody>${games.slice(0, 10).join('')}</tbody></table></div>`, `<span>Last ${Math.min(10, gp)} of ${gp}</span>`)}${card('Next up', next || '<p class="note">Regular season complete.</p>')}${injuryCard(tid)}</div>
      <aside class="stack">${card('Team leaders', tl('Points', 'pts') + tl('Rebounds', 'reb') + tl('Assists', 'ast') + tl('Steals', 'stl') + tl('Blocks', 'blk'))}${card('Team profile', profile, '<span>Rank of 10</span>')}</aside></div>`;
    unitsCard(tid);
  }

  /* ---------- leaders / players ---------- */
  function leadersView() {
    const best = D.games.flatMap(allRows).sort((x, y) => gmsc(y[0]) - gmsc(x[0])).slice(0, 10);
    return `<div class="stack"><div class="grid g-4">${CATS.map(([lab, ab, f]) => card(lab, topN(f, 5).map(([pid, s, v], i) => lrow(pid, s, ab.endsWith('BPM') ? sgn(v, 1) : f1(v), i)).join(''), `<span>${ab}</span>`)).join('')}</div>
      ${card('Best single games', `<div class="scroll"><table><thead><tr><th class="t">#</th><th class="t">Player</th><th class="t">Game</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FG</th><th>3PT</th><th>FT</th><th>Game score</th></tr></thead><tbody>${best.map(([r, tid, g], i) => { const hm = g.home.tid === tid, opp = hm ? g.away.tid : g.home.tid;
        return `<tr><td class="t muted">${i + 1}</td><td class="t nm"><a href="#player-${r[0]}">${face(r[0], 26)}<span>${esc(P.get(r[0]).name)}</span></a></td><td class="t"><a href="#game-${g.gid}">${g.day}, ${team(tid).abbrev} ${hm ? 'vs' : '@'} ${team(opp).abbrev}</a></td><td>${Math.round(r[C.min])}</td><td><b>${r[C.pts]}</b></td><td>${r[C.orb] + r[C.drb]}</td><td>${r[C.ast]}</td><td>${r[C.stl]}</td><td>${r[C.blk]}</td><td>${r[C.fg]}-${r[C.fga]}</td><td>${r[C.tp]}-${r[C.tpa]}</td><td>${r[C.ft]}-${r[C.fta]}</td><td><b>${f1(gmsc(r))}</b></td></tr>`; }).join('')}</tbody></table></div><p class="note">Game score is one number for a whole box-score line: points, shooting efficiency, rebounds, assists, steals and blocks count for a player, missed shots, turnovers and fouls against him.</p>`)}</div>`;
  }
  const A = (i) => (s, p) => (p.adv ? p.adv[i] : -99);
  const PCOLS = [['gp', 'GP', (s) => s.gp, 0], ['min', 'MIN', (s) => per(s, 'min')], ['pts', 'PTS', (s) => per(s, 'pts')], ['reb', 'REB', (s) => per(s, 'reb')], ['ast', 'AST', (s) => per(s, 'ast')], ['stl', 'STL', (s) => per(s, 'stl')], ['blk', 'BLK', (s) => per(s, 'blk')], ['tov', 'TO', (s) => per(s, 'tov')],
    ['tpp', '3P%', (s) => (s.tpa ? 100 * s.tp / s.tpa : -1)], ['ftp', 'FT%', (s) => (s.fta ? 100 * s.ft / s.fta : -1)], ['obpm', 'OBPM', A(6), 2], ['dbpm', 'DBPM', A(7), 2], ['bpm', 'BPM', (s, p) => (p.adv ? p.adv[6] + p.adv[7] : -99), 2]];
  /* Award scores are the ones Basketball GM uses, which were regressed on real award voting:
     MVP = team win% + EWA/22 + VORP/32 + share of team wins/10; DPOY = team win% + DWS/3.1 + BLK/4.1 + STL/1.8;
     ROY = EWA/2.1 + VORP + PTS/2; MIP = change in (PTS + REB + AST). Season totals are scaled to an 82-game pace. */
  function awardsView() {
    const q = qualified().map(([pid, s]) => [pid, s, P.get(pid)]).filter((x) => x[2].adv), wp = (s) => rec[s.tid].w / gpT(s.tid), sc = (s) => 82 / gpT(s.tid);
    const lad = (title, note, xs, sub) => card(title, xs.slice(0, 5).map(([pid, s, p], i) => lrow(pid, s, '', i, `${team(s.tid).abbrev} ${recStr(s.tid)} · ${sub(s, p)}`)).join('') || '<p class="note">Nobody qualifies yet.</p>', `<span>${note}</span>`);
    const by = (f) => [...q].map((x) => [...x, f(x)]).sort((a, b) => b[3] - a[3]);
    const pra = (s) => `${f1(per(s, 'pts'))} pts, ${f1(per(s, 'reb'))} reb, ${f1(per(s, 'ast'))} ast`, dfn = (s) => `${f1(per(s, 'stl'))} stl, ${f1(per(s, 'blk'))} blk, ${f1(per(s, 'reb'))} reb`;
    const mvp = by(([, s, p]) => wp(s) + p.adv[4] * sc(s) / 22 + p.adv[5] * sc(s) / 32 + (p.adv[1] / Math.max(1, rec[s.tid].w)) / 10);
    const dpoy = by(([, s, p]) => wp(s) + p.adv[2] * sc(s) / 3.1 + per(s, 'blk') / 4.1 + per(s, 'stl') / 1.8);
    const roy = by(([, s, p]) => p.adv[4] * sc(s) / 2.1 + p.adv[5] * sc(s) + per(s, 'pts') / 2).filter((x) => x[2].rk);
    const squad = (title, xs, sub) => card(title, xs.length ? `<div class="dts squad">${xs.map(([pid, s, p]) => `<a class="dt" href="#player-${pid}">${face(pid, 56)}<b>${esc(p.name)}</b><span>${team(s.tid).abbrev} · ${p.pos}</span><small>${sub(s)}</small></a>`).join('')}</div>` : '<p class="note">Nobody qualifies yet.</p>', '<span>If the season ended today</span>');
    return `<div class="stack"><div class="grid g-3">
      ${lad('MVP', 'Most valuable player', mvp, pra)}${lad('DPOY', 'Defensive player of the year', dpoy, dfn)}${lad('ROY', 'Rookie of the year', roy, pra)}</div>
      ${squad('All-League First Team', mvp.slice(0, 5), pra)}${squad('All-League Second Team', mvp.slice(5, 10), pra)}${squad('All-League Third Team', mvp.slice(10, 15), pra)}
      <div class="grid g-2">${squad('All-Defensive Team', dpoy.slice(0, 5), dfn)}${squad('All-Rookie Team', roy.slice(0, 5), pra)}</div>
      <p class="note" style="padding:0">Awards and teams follow formulas fitted to decades of real award voting. MVP and All-League: team record plus value added. DPOY and All-Defensive: team record, defensive win shares, blocks and steals. ROY and All-Rookie: value added plus scoring.</p></div>`;
  }
  const PS = { key: 'pts', dir: -1, q: '', pos: '', view: 'leaders' };
  function playersPage(arg) {
    if (['leaders', 'awards', 'stats'].includes(arg)) PS.view = arg;
    const tabs = `<div class="tools au-tools"><div class="seg" role="group" aria-label="View">${[['leaders', 'Leaders'], ['awards', 'Awards'], ['stats', 'All players']].map(([k, lab]) => `<a href="#players-${k}" aria-current="${PS.view === k}">${lab}</a>`).join('')}</div></div>`;
    if (PS.view !== 'stats') { $app.innerHTML = `<div class="page-h"><h1>Players</h1><span>${PS.view === 'leaders' ? `Per game · at least ${Math.ceil(Math.max(3, lastDay * 0.4))} games played` : `Projected through Game ${lastDay}`}</span></div>${tabs}${PS.view === 'leaders' ? leadersView() : awardsView()}`; return; }
    const col = PCOLS.find((c) => c[0] === PS.key), q = PS.q.toLowerCase();
    const rows = [...stats.entries()].filter(([pid]) => { const p = P.get(pid); return (!PS.pos || p.pos === PS.pos) && (!q || (p.name + ' ' + (p.tid >= 0 ? team(p.tid).abbrev + ' ' + team(p.tid).name : '')).toLowerCase().includes(q)); }).sort((a, b) => (col[2](a[1], P.get(a[0])) - col[2](b[1], P.get(b[0]))) * PS.dir);
    $app.innerHTML = `<div class="page-h"><h1>Players</h1><span>Per game</span></div>${tabs}
      <div class="tools"><input class="q" id="pq" type="search" placeholder="Search players or teams" value="${esc(PS.q)}" aria-label="Search players"><div class="seg" role="group" aria-label="Position">${['', 'PG', 'SG', 'SF', 'PF', 'C'].map((x) => `<button type="button" data-pos="${x}" aria-pressed="${PS.pos === x}">${x || 'All'}</button>`).join('')}</div></div>
      ${card('Player stats', `<div class="scroll"><table id="pt"><thead><tr><th class="t">#</th><th class="t">Player</th><th class="t">Team</th><th class="t">Pos</th>${PCOLS.map(([k, lab]) => `<th data-k="${k}" class="${k === PS.key ? 'on' : ''}${k === 'obpm' || k === 'tpp' ? ' grp' : ''}">${lab}${k === PS.key ? (PS.dir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr></thead><tbody>${rows.map(([pid, s], i) => { const p = P.get(pid);
        return `<tr><td class="t muted">${i + 1}</td><td class="t nm"><a href="#player-${pid}">${face(pid, 26)}<span>${esc(p.name)}</span></a></td><td class="t">${p.tid >= 0 ? tlink(p.tid, team(p.tid).abbrev) : 'FA'}</td><td class="t"><span class="chip">${p.pos}</span></td>${PCOLS.map(([k, , f, d]) => { const v = f(s, p); return `<td class="${k === 'obpm' || k === 'tpp' ? 'grp' : ''}"${k === PS.key ? ' style="color:var(--ink);font-weight:600"' : ''}>${d === 2 ? (v <= -99 ? '—' : sgn(v, 1)) : v < 0 ? '—' : d === 0 ? v : f1(v)}</td>`; }).join('')}</tr>`; }).join('')}</tbody></table></div>`, '<span>Click a column to sort</span>')}`;
    const inp = document.getElementById('pq');
    inp.addEventListener('input', () => { PS.q = inp.value; playersPage(); const n = document.getElementById('pq'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); });
    document.querySelectorAll('[data-pos]').forEach((b) => b.addEventListener('click', () => { PS.pos = b.dataset.pos; playersPage(); }));
    document.getElementById('pt').addEventListener('click', (e) => { const th = e.target.closest('th[data-k]'); if (!th) return; PS.dir = PS.key === th.dataset.k ? -PS.dir : -1; PS.key = th.dataset.k; playersPage(); });
  }

  /* ---------- player ---------- */
  function player(pid) {
    const p = P.get(pid); if (!p) return notFound();
    const s = stats.get(pid), t = p.tid >= 0 ? team(p.tid) : null;
    const log = D.games.map((g) => { for (const [me, op, hm] of [[g.home, g.away, true], [g.away, g.home, false]]) { const r = me.box.find((x) => x[0] === pid); if (r) return { g, me, op, hm, r }; const d = me.dnp.find((x) => x[0] === pid); if (d) return { g, me, op, hm, dnp: d[1] }; } return null; }).filter(Boolean);
    const played = log.filter((x) => x.r);
    const agg = (xs) => xs.reduce((a, x) => add(a, x.r), blank());
    const statRow = (lab, a, tot) => (a.gp ? `<tr><td class="t" style="font-family:var(--f)">${lab}</td><td>${a.gp}</td><td>${tot ? Math.round(a.min) : f1(per(a, 'min'))}</td><td><b>${tot ? a.pts : f1(per(a, 'pts'))}</b></td><td>${tot ? a.reb : f1(per(a, 'reb'))}</td><td>${tot ? a.ast : f1(per(a, 'ast'))}</td><td>${tot ? a.stl : f1(per(a, 'stl'))}</td><td>${tot ? a.blk : f1(per(a, 'blk'))}</td><td>${tot ? a.tov : f1(per(a, 'tov'))}</td><td>${tot ? `${a.fg}-${a.fga}` : pct(a.fg, a.fga)}</td><td>${tot ? `${a.tp}-${a.tpa}` : pct(a.tp, a.tpa)}</td><td>${tot ? `${a.ft}-${a.fta}` : pct(a.ft, a.fta)}</td><td class="${a.pm > 0 ? 'up' : 'dn'}">${tot ? sgn(a.pm) : sgn(per(a, 'pm'), 1)}</td></tr>` : '');
    const sh = '<thead><tr><th class="t"></th><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th><th>FG</th><th>3P</th><th>FT</th><th>+/-</th></tr></thead>';
    const LD = Object.fromEntries([['min', (r) => r[C.min]], ['pts', (r) => r[C.pts]], ['reb', (r) => r[C.orb] + r[C.drb]], ['ast', (r) => r[C.ast]], ['stl', (r) => r[C.stl]], ['blk', (r) => r[C.blk]], ['tov', (r) => r[C.tov]], ['gm', gmsc]].map(([k, f]) => [k, [f, played.map((x) => f(x.r))]]));
    const lh = (k, r, low) => { const [f, arr] = LD[k], p = rankIn(arr, f(r)); return ` style="${tintOf(low ? 1 - p : p)}"`; };
    const HK = { min: (r) => Math.round(r[C.min]), pts: (r) => r[C.pts], reb: (r) => r[C.orb] + r[C.drb], ast: (r) => r[C.ast], stl: (r) => r[C.stl], blk: (r) => r[C.blk], tov: (r) => r[C.tov], fg: (r) => r[C.fg], tp: (r) => r[C.tp], ft: (r) => r[C.ft], pf: (r) => r[C.pf], pm: (r) => r[C.pm], gm: (r) => +gmsc(r).toFixed(1) };
    const MX = Object.fromEntries(Object.entries(HK).map(([k, f]) => [k, Math.max(...played.map((x) => f(x.r)))]));
    const hb = (k, r, txt) => (HK[k](r) === MX[k] && MX[k] > 0 ? `<b class="hi">${txt}</b>` : txt);   // season high (ties included)
    const logRows = [...log].reverse().map((x) => { const w = x.me.pts > x.op.pts, pre = `<td class="t"><a href="#game-${x.g.gid}">${x.g.day}</a></td><td class="t op">${x.hm ? 'vs' : '@'} ${tlink(x.op.tid, `${logo(x.op.tid, 16)}${team(x.op.tid).abbrev}`)}</td><td class="t ${w ? 'up' : 'dn'}">${w ? 'W' : 'L'} ${x.me.pts}-${x.op.pts}</td>`, r = x.r;
      return r ? `<tr>${pre}<td class="grp"${lh('min', r)}>${hb('min', r, Math.round(r[C.min]))}</td><td${lh('pts', r)}>${hb('pts', r, r[C.pts])}</td><td${lh('reb', r)}>${hb('reb', r, r[C.orb] + r[C.drb])}</td><td${lh('ast', r)}>${hb('ast', r, r[C.ast])}</td><td${lh('stl', r)}>${hb('stl', r, r[C.stl])}</td><td${lh('blk', r)}>${hb('blk', r, r[C.blk])}</td><td${lh('tov', r, 1)}>${hb('tov', r, r[C.tov])}</td><td class="grp">${hb('fg', r, `${r[C.fg]}-${r[C.fga]}`)}</td><td>${hb('tp', r, `${r[C.tp]}-${r[C.tpa]}`)}</td><td>${hb('ft', r, `${r[C.ft]}-${r[C.fta]}`)}</td><td>${hb('pf', r, r[C.pf])}</td><td class="grp ${r[C.pm] > 0 ? 'up' : r[C.pm] < 0 ? 'dn' : ''}">${hb('pm', r, sgn(r[C.pm]))}</td><td${lh('gm', r)}>${hb('gm', r, f1(gmsc(r)))}</td></tr>` : `<tr>${pre}<td colspan="13" class="grp muted" style="text-align:center;font-size:12px">DNP - ${esc(x.dnp.toUpperCase())}</td></tr>`; }).join('');
    const hi = [['Points', (r) => r[C.pts]], ['Rebounds', (r) => r[C.orb] + r[C.drb]], ['Assists', (r) => r[C.ast]], ['Steals', (r) => r[C.stl]], ['Blocks', (r) => r[C.blk]], ['Threes', (r) => r[C.tp]]]
      .map(([lab, f]) => { const b = played.reduce((a, x) => (!a || f(x.r) > f(a.r) ? x : a), null); return b ? `<a class="row r-sched" style="grid-template-columns:minmax(0,1fr) auto auto" href="#game-${b.g.gid}"><span>${lab}</span><span class="d">Game ${b.g.day} ${b.hm ? 'vs' : '@'} ${team(b.op.tid).abbrev}</span><span class="v" style="font:700 14px var(--m);min-width:38px;text-align:right">${f(b.r)}</span></a>` : ''; }).join('');
    const zones = s ? ZONES.map(([lab, m, a]) => `<tr><td class="t" style="font-family:var(--f)">${lab}</td><td>${s[m]}-${s[a]}</td><td><b>${pct(s[m], s[a])}</b></td><td>${(100 * s[a] / Math.max(1, s.fga)).toFixed(1)}%</td><td style="width:38%"><div class="hbar" style="grid-template-columns:1fr;padding:0;--c:${t ? t.accent : 'var(--gold)'}"><span class="b"><i style="width:${100 * s[a] / Math.max(1, s.fga)}%"></i></span></div></td></tr>`).join('') : '';
    const vs = [...new Set(played.map((x) => x.op.tid))].map((o) => [o, agg(played.filter((x) => x.op.tid === o))]).sort((a, b) => per(b[1], 'pts') - per(a[1], 'pts'));
    const pv = played.map((x) => x.r[C.pts]), mx = Math.max(1, ...pv), avg = s ? per(s, 'pts') : 0;
    const spark = pv.length > 1 ? `<svg class="spark" viewBox="0 0 ${pv.length * 20} 44" preserveAspectRatio="none">${pv.map((v, i) => `<rect x="${i * 20 + 3}" y="${44 - 40 * v / mx}" width="14" height="${40 * v / mx}" fill="${v >= avg ? (t ? t.accent : 'var(--gold)') : '#39414b'}"/>`).join('')}<line x1="0" x2="${pv.length * 20}" y1="${44 - 40 * avg / mx}" y2="${44 - 40 * avg / mx}" stroke="var(--ink)" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/></svg>` : '';
    const rk = (f) => { const r = rankOf(pid, f); return r ? `<small>${ord(r)}</small>` : '<small>&nbsp;</small>'; };
    const bio = [['Age', p.age], ['Size', `${htS(p.ht)}${p.wt ? `, ${p.wt} lbs` : ''}`], ['Contract', p.sal ? `$${p.sal}M / ${p.exp}` : null], ['Draft', p.smp ? `Round ${Math.ceil(p.smp / 10)} Pick ${((p.smp - 1) % 10) + 1}` : null]].filter((x) => x[1]);
    $app.innerHTML = `<section class="card hd" style="--c:${t ? t.accent : '#555'}${t ? `;--wm:url(${t.logo})` : ''}">${pface(pid, 104)}<div><h1>${esc(p.name)}</h1><div class="sub">${t ? tlink(t.tid, tname(t.tid)) : '<span>Free agent</span>'}<span>${p.pos}${p.num ? ` · #${esc(p.num)}` : ''}${p.rk ? ' · Rookie' : ''}</span>${p.inj ? `<span class="inj">${esc(p.inj[0])}, out ${p.inj[1]} games</span>` : ''}</div>
      <div class="bio">${bio.map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join('')}</div></div>
      ${s ? `<div class="nums2"><div class="nums"><div><b>${f1(per(s, 'pts'))}</b><span>PTS</span>${rk((x) => per(x, 'pts'))}</div><div><b>${f1(per(s, 'reb'))}</b><span>REB</span>${rk((x) => per(x, 'reb'))}</div><div><b>${f1(per(s, 'ast'))}</b><span>AST</span>${rk((x) => per(x, 'ast'))}</div><div><b>${f1(per(s, 'stl'))}</b><span>STL</span>${rk((x) => per(x, 'stl'))}</div><div><b>${f1(per(s, 'blk'))}</b><span>BLK</span>${rk((x) => per(x, 'blk'))}</div></div>
        <div class="nums sm"><div><b>${pct(s.fg, s.fga)}</b><span>FG%</span></div><div><b>${pct(s.tp, s.tpa)}</b><span>3P%</span></div><div><b>${pct(s.ft, s.fta)}</b><span>FT%</span></div>${p.adv ? `<div><b>${sgn(p.adv[6], 1)}</b><span>oBPM</span></div><div><b>${sgn(p.adv[7], 1)}</b><span>dBPM</span></div>` : ''}</div></div>` : ''}</section>
      ${s ? `<div class="grid g-main"><div class="stack">
        ${card('Season stats', `<div class="scroll"><table>${sh}<tbody>${statRow('Per game', s)}${statRow('Totals', s, true)}</tbody></table></div>${p.adv ? `<div class="kv"><div><b>${sgn(p.adv[6], 1)}</b><span>OBPM</span></div><div><b>${sgn(p.adv[7], 1)}</b><span>DBPM</span></div><div><b>${sgn(p.adv[6] + p.adv[7], 1)}</b><span>BPM</span></div><div><b>${p.adv[0]}</b><span>PER</span></div><div><b>${p.adv[1].toFixed(1)}</b><span>Win shares</span></div><div><b>${p.adv[3]}%</b><span>Usage</span></div></div>` : ''}`, `<span>${D.season} · ${s.gs} starts</span>`)}
        ${card('Game log', `<div class="scroll"><table><thead><tr><th class="t">Game</th><th class="t">Opp</th><th class="t">Result</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th><th>FG</th><th>3PT</th><th>FT</th><th>PF</th><th>+/-</th><th>GmSc</th></tr></thead><tbody>${logRows}</tbody></table></div>`, `<span>${played.length} played · ${log.length - played.length} missed</span>`)}</div>
      <aside class="stack">${card('Season highs', hi)}${card('Shot diet', `<table><thead><tr><th class="t">Zone</th><th>Made</th><th>FG%</th><th>Share</th><th></th></tr></thead><tbody>${zones}</tbody></table>`, '<span>Share of his shots</span>')}</aside></div>` : '<p class="muted">He has not played a game yet.</p>'}`;
  }

  const FS = { fa: '', dr: '' };
  const posSeg = (cur, key) => `<div class="tools"><div class="seg" role="group" aria-label="Position">${['', 'PG', 'SG', 'SF', 'PF', 'C'].map((x) => `<button type="button" data-fpos="${x}" data-fkey="${key}" aria-pressed="${cur === x}">${x || 'All'}</button>`).join('')}</div></div>`;
  const wirePos = (again) => document.querySelectorAll('[data-fpos]').forEach((b) => b.addEventListener('click', () => { FS[b.dataset.fkey] = b.dataset.fpos; again(); }));
  const fface = (p, n = 40) => lface({ n: p.name, espn: p.espn }, n);
  const posBars = (xs) => { const c = POSN.map((pos) => xs.filter((p) => p.pos === pos).length), mx = Math.max(1, ...c); return POSN.map((pos, i) => `<div class="hbar" style="grid-template-columns:40px minmax(0,1fr) 30px"><span class="t">${pos}</span><span class="b"><i style="width:${100 * c[i] / mx}%"></i></span><span class="v">${c[i]}</span></div>`).join(''); };
  const posTabs = (key) => `<div class="tools au-tools"><div class="seg" role="group" aria-label="Position">${['', ...POSN].map((x) => `<button type="button" data-fpos="${x}" data-fkey="${key}" aria-pressed="${FS[key] === x}">${x || 'All'}</button>`).join('')}</div></div>`;
  function freeAgents() {
    const xs = D.fa.filter((p) => !FS.fa || p.pos === FS.fa).sort((a, b) => a.bd - b.bd), best = (pos) => D.fa.filter((p) => p.pos === pos).sort((a, b) => a.bd - b.bd)[0];
    const rows = xs.map((p) => `<tr><td class="t rk">${p.bd}</td><td class="t nm"><span class="pl">${fface(p)}<span>${esc(p.name)}</span></span></td><td class="t"><span class="chip">${p.pos}</span></td><td>${p.age}</td><td>${htS(p.ht)}</td></tr>`).join('');
    const pay = T.map((t) => { const r = D.players.filter((p) => p.tid === t.tid); return [t, r.reduce((a, p) => a + (p.sal || 0), 0), r.length]; }).sort((a, b) => a[1] - b[1]);
    const room = pay.map(([t, m, n]) => `<a class="row r-news" href="#team-${t.abbrev}">${logo(t.tid, 28)}<span class="who"><b>${esc(t.name)}</b><span>$${m}M payroll · ${n} players</span></span><span class="v">$${Math.max(0, D.cap - m)}M</span></a>`).join('');
    const hurt = D.players.filter((p) => p.inj && p.tid >= 0 && p.inj[1] >= 3 && best(p.pos)).sort((a, b) => b.inj[1] - a.inj[1]).slice(0, 6)
      .map((p) => { const f = best(p.pos); return `<a class="row r-news" href="#team-${team(p.tid).abbrev}">${logo(p.tid, 28)}<span class="who"><b>${esc(short(p.name))} is out ${p.inj[1]} games</b><span>Best ${p.pos} available: ${esc(f.name)}</span></span>${fface(f, 32)}</a>`; }).join('');
    const tops = POSN.map((pos) => { const p = best(pos); return p ? `<div class="row r-news">${fface(p, 32)}<span class="who"><b>${esc(p.name)}</b><span>${p.age} · ${htS(p.ht)} · board rank ${p.bd}</span></span><span class="v">${pos}</span></div>` : ''; }).join('');
    const ages = [...D.fa].sort((a, b) => a.age - b.age);
    $app.innerHTML = `<div class="page-h"><h1>Free agents</h1><span>The ${D.fa.length} best unsigned players</span></div>${posTabs('fa')}
      <div class="grid g-main"><div class="stack">${card('Best available', `<div class="scroll"><table class="au-list"><thead><tr><th class="t">#</th><th class="t">Player</th><th class="t">Pos</th><th>Age</th><th>Ht</th></tr></thead><tbody>${rows}</tbody></table></div>`, `<span>${xs.length} of ${D.fa.length} · ordered by board rank</span>`)}</div>
      <aside class="stack">${card('Cap room', room, `<span>Under the $${D.cap}M cap</span>`)}${hurt ? card('Who could use one', hurt, '<span>Long injuries</span>') : ''}${card('Best at each position', tops)}
        ${card('The pool', `<div style="padding:8px 0">${posBars(D.fa)}</div><div class="bud"><div class="kv"><div><b>${f1(D.fa.reduce((a, p) => a + p.age, 0) / D.fa.length)}</b><span>Average age</span></div><div><b>${ages[0].age}</b><span>Youngest: ${esc(short(ages[0].name))}</span></div><div><b>${ages.at(-1).age}</b><span>Oldest: ${esc(short(ages.at(-1).name))}</span></div><div><b>${D.fa.filter((p) => p.age >= 33).length}</b><span>Aged 33 or older</span></div></div></div>`, '<span>By position</span>')}</aside></div>`;
    wirePos(freeAgents);
  }
  function draftPage() {
    const o = order().reverse(), ht2 = (p) => `${p.age} · ${htS(p.ht)}${p.col ? ` · ${esc(p.col)}` : ''}`;
    const pick = (tid, i) => { const p = D.draft[i]; return `<div class="pk"><span class="no">${i + 1}</span>${tlink(tid, logo(tid, 40))}<span class="who"><b>${esc(p.name)}</b><span>${p.pos} · ${ht2(p)}</span></span><span class="tm">${tlink(tid, esc(team(tid).name))}<small>${recStr(tid)}</small></span></div>`; };
    const xs = D.draft.map((p, i) => [p, i + 1]).filter(([p]) => !FS.dr || p.pos === FS.dr);
    const rows = xs.map(([p, n]) => `<tr><td class="t rk">${n}</td><td class="t nm"><span class="pl" style="min-height:34px">${esc(p.name)}</span></td><td class="t"><span class="chip">${p.pos}</span></td><td>${p.age}</td><td>${htS(p.ht)}</td><td class="t">${p.col ? esc(p.col) : '—'}</td><td class="t">${n <= 10 ? tlink(o[n - 1], `<span class="pl" style="gap:6px;font-size:13px">${logo(o[n - 1], 18)}${team(o[n - 1]).abbrev}</span>`) : ''}</td></tr>`).join('');
    const cols = {}; for (const p of D.draft) if (p.col) cols[p.col] = (cols[p.col] || 0) + 1;
    const top = Object.entries(cols).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8), mx = Math.max(1, ...top.map((x) => x[1]));
    const schools = top.map(([c, n]) => `<div class="hbar" style="grid-template-columns:130px minmax(0,1fr) 30px"><span class="t">${esc(c)}</span><span class="b"><i style="width:${100 * n / mx}%"></i></span><span class="v">${n}</span></div>`).join('');
    const ages = [...D.draft].sort((a, b) => a.age - b.age), tall = [...D.draft].sort((a, b) => b.ht - a.ht)[0];
    const race = o.slice(0, 5).map((tid, i) => `<a class="row r-news" href="#team-${team(tid).abbrev}">${logo(tid, 28)}<span class="who"><b>${esc(team(tid).name)}</b><span>${recStr(tid)}${streakTxt(tid) ? ` · ${streakTxt(tid)}` : ''}</span></span><span class="v">${ord(i + 1)}</span></a>`).join('');
    $app.innerHTML = `<div class="page-h"><h1>${D.draftYear} draft</h1><span>One round, ten picks</span></div>
      ${card('If the draft were today', `<div class="pks">${o.map(pick).join('')}</div><p class="note">Teams pick in reverse order of the standings (the lottery rules are not set yet), each taking the best prospect left on the league's scouting board.</p>`, '<span>Projected first round</span>')}
      <div style="margin-top:var(--gap)">${posTabs('dr')}</div>
      <div class="grid g-main"><div class="stack">${card('Scouting board', `<div class="scroll"><table class="au-list"><thead><tr><th class="t">#</th><th class="t">Prospect</th><th class="t">Pos</th><th>Age</th><th>Ht</th><th class="t">School</th><th class="t">Projected</th></tr></thead><tbody>${rows}</tbody></table></div>`, `<span>${xs.length} of ${D.draft.length} prospects</span>`)}</div>
      <aside class="stack">${card('Race for the first pick', race, '<span>Worst records</span>')}${card('Schools', `<div style="padding:8px 0">${schools}</div>`, '<span>Most prospects</span>')}
        ${card('The class', `<div style="padding:8px 0">${posBars(D.draft)}</div><div class="bud"><div class="kv"><div><b>${f1(D.draft.reduce((a, p) => a + p.age, 0) / D.draft.length)}</b><span>Average age</span></div><div><b>${ages[0].age}</b><span>Youngest: ${esc(short(ages[0].name))}</span></div><div><b>${htS(tall.ht)}</b><span>Tallest: ${esc(short(tall.name))}</span></div><div><b>${Object.keys(cols).length}</b><span>Schools</span></div></div></div>`, '<span>By position</span>')}</aside></div>`;
    wirePos(draftPage);
  }
  /* ---------- five-man units, loaded on demand for the team page ---------- */
  let LU = null;
  async function unitsCard(tid) {
    LU ??= await fetch('data/lineups.json').then((r) => r.json());
    const el = document.getElementById('units'); if (!el || +el.dataset.tid !== tid) return;
    const rows = LU[tid] || [], net = ([sec, pf, pa]) => (pf - pa) / sec * 2880, last = (pid) => esc(P.get(pid).name.split(' ').slice(1).join(' ') || P.get(pid).name);
    const units = [...rows].filter((r) => r[5] >= 120).sort((x, y) => y[5] - x[5]).slice(0, 5), mx = Math.max(1, ...units.map((r) => Math.abs(net(r.slice(5)))));
    el.innerHTML = card('Most-used units', units.map((r) => { const x = r.slice(5), ps = r.slice(0, 5).sort((p, q) => (stats.get(q)?.min || 0) - (stats.get(p)?.min || 0)), v = net(x);
      return `<div class="row r-unit"><span class="faces">${ps.map((pid) => face(pid, 48)).join('')}</span><span class="who"><b>${ps.map(last).join(' · ')}</b><span>${Math.round(x[0] / 60)} min · scores ${f1(x[1] / x[0] * 2880)} · allows ${f1(x[2] / x[0] * 2880)}</span></span><span class="dv"><i class="${v >= 0 ? 'p' : 'n'}" style="width:${50 * Math.abs(v) / mx}%"></i></span><span class="v ${v >= 0 ? 'up' : 'dn'}">${sgn(v, 1)}</span></div>`; }).join('') || '<p class="note">No five-man unit has played two minutes together yet.</p>', `<span>Scoring margin per 48 minutes · ${rows.length} units used</span>`);
  }
  /* ---------- auction: computed in the browser from the published bid sheet ---------- */
  let AU = null, auTimer = null; const AS = { q: '', pos: '', st: '', led: '', page: 0, sort: { k: 'rk', dir: 1 }, open: null, allBids: false };
  const POSN = ['PG', 'SG', 'SF', 'PF', 'C'];
  const STATS = [['g', 'GP', 0], ['mp', 'MIN', 1], ['pts', 'PTS', 1], ['reb', 'REB', 1], ['ast', 'AST', 1], ['stl', 'STL', 1], ['blk', 'BLK', 1], ['fg', 'FG%', 1], ['tp', '3P%', 1], ['ft', 'FT%', 1]];   // auction lots carry last season's real per-game line in this order
  function parseCsv(text) {
    const rows = []; let row = [], cur = '', q = false;
    for (let i = 0; i < text.length; i++) { const ch = text[i];
      if (q) { if (ch === '"' && text[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
      else if (ch === '"') q = true; else if (ch === ',') { row.push(cur); cur = ''; } else if (ch === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; } else if (ch !== '\r') cur += ch; }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    return rows;
  }
  async function loadAuction() {
    if (AU && Date.now() - AU.at < 60e3) return AU;
    const raw = await fetch('data/auction.json', { cache: 'no-cache' }).then((r) => r.json()), demo = !raw.csv;
    const text = await fetch(raw.csv || 'data/auction-demo.csv', { cache: 'no-store' }).then((r) => r.text());
    const start = raw.start ? Date.parse(raw.start) : (AU ? AU.cfg.start : Date.now() - 20 * 3600e3), cfg = { ...raw, start, close: raw.close ? Date.parse(raw.close) : start + raw.hours * 3600e3 };
    const key = (s) => String(s).normalize('NFC').toLowerCase().replace(/\s+/g, ' ').trim(), byName = new Map(cfg.lots.flatMap((l) => [[key(l.n), l.id], ...(l.alt ? [[key(l.alt), l.id]] : [])]));   // alt: the garbled spelling the form's list had for accented names until 11-20
    const abbr = (s) => { const u = String(s).trim().toUpperCase(); return (T.find((t) => t.abbrev === u || t.name.toUpperCase() === u || `${t.region} ${t.name}`.toUpperCase() === u) || { abbrev: u }).abbrev; };
    const rows = parseCsv(text), head = (rows.shift() || []).map((h) => h.toLowerCase()), ix = (k) => head.findIndex((h) => h.includes(k));
    const c = { t: ix('time'), team: ix('team'), p: ix('player'), s: ix('salary'), y: ix('year') };
    // Google Sheets stamps look like 11/20/2026 14:03:22 in the sheet's own time zone; read them with cfg.tz so every viewer, in any time zone, gets the same instant
    const when = (v) => { const m = /^(\d+)\/(\d+)\/(\d+) (\d+):(\d+):(\d+)$/.exec(String(v).trim()), z = (n) => String(n).padStart(2, '0'); return String(v).startsWith('h:') ? start + parseFloat(v.slice(2)) * 3600e3 : m ? Date.parse(`${m[3]}-${z(m[1])}-${z(m[2])}T${z(m[4])}:${z(m[5])}:${z(m[6])}${raw.tz || '-05:00'}`) : Date.parse(v); };
    const all = rows.filter((r) => r.length > Math.max(c.t, c.team, c.p, c.s, c.y) && r[c.team]).map((r) => ({ t: when(r[c.t]), team: abbr(r[c.team]), pid: byName.get(key(r[c.p])), name: r[c.p], sal: Number(String(r[c.s]).replace(/[$,mM\s]/g, '')), yrs: Number(String(r[c.y]).replace(/[^\d.]/g, '')) }));
    const aiT = raw.aiSince ? Date.parse(raw.aiSince) : 0, bids = all.filter((b) => !((raw.ai || []).includes(b.team) && b.t < aiT));   // superseded AI-team bids stay in the sheet but do not count
    AU = { cfg, demo, bids, state: SMPAuction.run(cfg, bids), at: Date.now(), byId: new Map(cfg.lots.map((l) => [l.id, l])) };
    return AU;
  }
  const lface = (l, size = 32) => { const ini = esc(l.n.split(' ').map((x) => x[0]).join('').slice(0, 2)); return `<span class="face" style="width:${size}px;height:${size}px">${l.espn ? `<img src="https://a.espncdn.com/i/headshots/nba/players/full/${l.espn}.png" alt="" loading="lazy" onerror="this.outerHTML='<span class=&quot;ini&quot;>${ini}</span>'">` : `<span class="ini">${ini}</span>`}</span>`; };
  const tidOf = (ab) => T.find((t) => t.abbrev === ab)?.tid;
  const ago = (t) => { const m = Math.max(0, Math.round((Date.now() - t) / 60e3)); return m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; };
  const deal = (b) => `$${b.sal}M × ${b.yrs}`;
  const clockText = (cfg) => { const ms = cfg.close - Date.now(); if (ms <= 0) return 'Closed'; const h = Math.floor(ms / 3600e3), m = Math.floor(ms % 3600e3 / 60e3), s = Math.floor(ms % 60e3 / 1e3); return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(s).padStart(2, '0')}s`; };
  const formUrl = (cfg, l, ab) => { const f = cfg.form; if (!f || !f.url) return null; const q = [['usp', 'pp_url'], [f.player && `entry.${f.player}`, l && l.n], [f.team && `entry.${f.team}`, ab && (() => { const t = T.find((x) => x.abbrev === ab); return t ? `${t.region} ${t.name}` : ab; })()]].filter((x) => x[0] && x[1]).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&'); return `${f.url}?${q}`; };
  function tick(cfg) { clearInterval(auTimer); auTimer = setInterval(() => { const el = document.getElementById('au-clock'); if (!el) return clearInterval(auTimer); el.textContent = clockText(cfg); }, 1000); }

  async function auctionPage(arg) {
    if (!AU) $app.innerHTML = '<p class="muted">Loading the auction…</p>';
    const { cfg, state, demo, byId } = await loadAuction();
    if (arg) return auctionTeam(arg);
    const closed = Date.now() >= cfg.close, q = AS.q.toLowerCase(), bidLink = formUrl(cfg), L = (l) => state.lots.get(l.id);
    const byName = [...T].sort((a, b) => a.region.localeCompare(b.region));
    const tiles = byName.map((t) => { const s = state.teams[t.abbrev];
      return `<a class="au-team" href="#auction-${t.abbrev}">${logo(t.tid, 38)}<span class="who"><b>${esc(t.name)}</b><span>${s.n}/${cfg.roster} players${(cfg.ai || []).includes(t.abbrev) ? ' · AI bids' : ''}</span></span><span class="amt"><b>$${s.left}M</b><span>left</span></span><span class="meter"><i style="width:${100 * s.spent / cfg.budget}%;background:${t.accent}"></i></span></a>`; }).join('');
    const feed = (xs) => xs.map(([l, b, sub]) => `<a class="row r-bid" href="#auction-${b.team}">${logo(tidOf(b.team), 22)}${lface(l, 30)}<span class="who"><b>${esc(l.n)}</b><span>${sub}</span></span><span class="v">${deal(b)}</span></a>`).join('') || '<p class="note">No bids yet.</p>';
    const recent = feed(state.log.filter((b) => b.ok).slice(-5).reverse().map((b) => [byId.get(b.pid), b, `${team(tidOf(b.team)).name} · ${ago(b.t)}`]));
    const biggest = feed([...state.lots.values()].filter((x) => x.lead).sort((a, b) => b.lead.score - a.lead.score).slice(0, 5).map((x) => [x, x.lead, `${team(tidOf(x.lead.team)).name} · ${x.history.length} bid${x.history.length === 1 ? '' : 's'}`]));
    const show = (l) => { const ld = L(l).lead; return (!q || l.n.toLowerCase().includes(q)) && (!AS.pos || l.pos === AS.pos) && (!AS.st || (AS.st === 'open' ? !ld : !!ld)) && (!AS.led || (ld && ld.team === AS.led)); };
    const detail = (l) => { const x = L(l), espn = l.espn ? `https://www.espn.com/nba/player/_/id/${l.espn}` : null, bid = formUrl(cfg, l);
      return `<div class="lot-d"><div class="hist">${x.history.length ? [...x.history].reverse().map((b, i) => `<div class="hb${i ? '' : ' top'}">${logo(tidOf(b.team), 18)}<span>${team(tidOf(b.team)).abbrev}</span><b>${deal(b)}</b><small>${ago(b.t)}</small></div>`).join('') : '<p class="cap">No bids yet. Any offer of $1M or more takes the lead.</p>'}</div>
        <div class="lot-a">${bid && !closed ? `<a class="btn go" href="${bid}" target="_blank" rel="noopener">Bid on ${esc(l.n.split(' ').slice(-1)[0])}</a>` : ''}${espn ? `<a class="btn" href="${espn}" target="_blank" rel="noopener">ESPN page ↗</a>` : ''}</div></div>`; };
    const offer = (ld) => (ld ? `<span class="px">${logo(tidOf(ld.team), 18)}<b>$${ld.sal}M</b><small>× ${ld.yrs}</small></span>` : '<span class="px none"><small>No bids</small></span>');
    const rows = cfg.lots.filter(show), SK = { rk: (l) => l.rk, n: (l) => l.n, pos: (l) => POSN.indexOf(l.pos), age: (l) => l.age, offer: (l) => (L(l).lead ? L(l).lead.score : 0), bids: (l) => L(l).history.length, last: (l) => (L(l).lead ? L(l).lead.t : 0) };
    STATS.forEach(([k], i) => { SK[k] = (l) => (l.s && l.s[i] != null ? l.s[i] : -1); });
    const sk = SK[AS.sort.k]; rows.sort((a, b) => { const x = sk(a), y = sk(b); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * AS.sort.dir || a.rk - b.rk; });
    const PHONE = new Set(['pts']), DISTS = STATS.map((_, i) => cfg.lots.filter((l) => l.s && l.s[i] != null).map((l) => l.s[i]));
    const PG = 50, pages = Math.max(1, Math.ceil(rows.length / PG)); AS.page = Math.min(AS.page, pages - 1);
    const th = (k, lab, cls = '') => `<th data-ak="${k}" class="${cls}${AS.sort.k === k ? ' on' : ''}">${lab}${AS.sort.k === k ? (AS.sort.dir < 0 ? ' ↓' : ' ↑') : ''}</th>`;
    const list = `<div class="scroll"><table class="au-list"><thead><tr>${th('rk', '#', 't')}${th('n', 'Player', 't')}${th('pos', 'Pos', 't hm')}${th('age', 'Age', 'hm')}<th class="hm">Ht</th>${STATS.map(([k, lab], i) => th(k, lab, (i ? '' : 'grp') + (PHONE.has(k) ? '' : ' hm'))).join('')}${th('offer', 'Best offer', 'grp')}${th('bids', 'Bids', 'hm')}${th('last', 'Last bid', 'hm')}<th class="grp"></th></tr></thead><tbody>${rows.slice(AS.page * PG, AS.page * PG + PG).map((l) => { const x = L(l), ld = x.lead, on = AS.open === l.id;
      return `<tr class="lr${on ? ' on' : ''}" data-lot="${l.id}"><td class="t rk">${l.rk}</td><td class="t nm"><span class="pl">${lface(l, 40)}${l.espn ? `<a href="https://www.espn.com/nba/player/_/id/${l.espn}" target="_blank" rel="noopener">${esc(l.n)}</a>` : `<span>${esc(l.n)}</span>`}<small class="pp">${l.pos}</small></span></td><td class="t hm"><span class="chip">${l.pos}</span></td><td class="hm">${l.age}</td><td class="hm">${htS(l.ht)}</td>${STATS.map(([k, , d], i) => { const has = l.s && l.s[i] != null; return `<td class="${i ? '' : 'grp'}${PHONE.has(k) ? '' : ' hm'}"${has ? ` style="${tintOf(rankIn(DISTS[i], l.s[i]))}"` : ''}>${has ? (d ? l.s[i].toFixed(1) : l.s[i]) : '<span class="faint">—</span>'}</td>`; }).join('')}<td class="grp">${offer(ld)}</td><td class="hm">${x.history.length || '—'}</td><td class="muted hm">${ld ? ago(ld.t) : '—'}</td><td class="grp t act">${bidLink && !closed ? `<a class="btn go sm" href="${formUrl(cfg, l)}" target="_blank" rel="noopener">Bid</a>` : `<span class="more2">${on ? 'Close' : 'Details'}</span>`}</td></tr>${on ? `<tr class="ld"><td colspan="19">${detail(l)}</td></tr>` : ''}`; }).join('') || '<tr><td class="t muted" colspan="19">Nobody matches those filters.</td></tr>'}</tbody></table></div>`;
    const led = cfg.lots.filter((l) => L(l).lead).length, money = Object.values(state.teams).reduce((a, s) => a + s.spent, 0);
    const seg = (key, opts) => `<div class="seg" role="group">${opts.map(([k, lab]) => `<button type="button" data-af="${key}" data-av="${k}" aria-pressed="${AS[key] === k}">${lab}</button>`).join('')}</div>`;
    $app.innerHTML = `<div class="au-head"><div><h1>Auction</h1><p class="lede2">Bidding closes <b>${new Date(cfg.close).toLocaleString('en-US', { weekday: 'long', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' })} Eastern</b>.</p></div>
        <div class="au-clock"><span class="label">${closed ? 'The auction is over' : 'Bidding closes in'}</span><b id="au-clock">${clockText(cfg)}</b><span class="cap">${led} of ${cfg.lots.length} players have a bid · $${money}M committed</span>${bidLink && !closed ? `<a class="btn go" href="${bidLink}" target="_blank" rel="noopener">Place a bid</a>` : ''}</div></div>
      ${card('Rules', `<ol class="rules-ol"><li>Every team has <b>$${cfg.budget}M</b> to sign <b>${cfg.roster} players</b>.</li><li>A bid is a salary in whole millions (<b>$1M or more</b>) and a length (<b>1 to 5 years</b>).</li><li>Longer deals count for more: value = salary × (1 + 0.25 per extra year). <b>$10M for 3 years beats $14M for 1.</b></li><li>Your leading bids plus <b>$1M for each empty roster spot</b> cannot pass $${cfg.budget}M. If you are outbid, that money is free again.</li></ol>`)}
      ${demo ? '<p class="au-demo">Demo bids. These are made up to show how the page works; real bids appear here once the bid form is connected.</p>' : ''}
      <div class="au-teams">${tiles}</div>
      <div class="grid g-2 au-body">${card('Latest bids', recent, `<span>${state.log.filter((b) => b.ok).length} accepted</span>`)}${card('Biggest offers', biggest, '<span>Salary × length</span>')}</div>
      <div class="au-body">
        <div class="tools au-tools"><input class="q" id="auq" type="search" placeholder="Find a player" value="${esc(AS.q)}" aria-label="Find a player">${seg('pos', [['', 'All'], ...POSN.map((p) => [p, p])])}${seg('st', [['', 'Everyone'], ['open', 'No bids yet'], ['bid', 'Has a bid']])}<span class="sp2"></span><div class="pgr"><button type="button" data-pg="${AS.page - 1}" aria-label="Previous page"${AS.page ? '' : ' disabled'}>‹</button><span><b>${rows.length ? AS.page * PG + 1 : 0}–${Math.min(rows.length, (AS.page + 1) * PG)}</b> of ${rows.length}</span><button type="button" data-pg="${AS.page + 1}" aria-label="Next page"${AS.page < pages - 1 ? '' : ' disabled'}>›</button></div></div>
        ${card('Best available', list, `<span>${rows.length} of ${cfg.lots.length} · ordered by ${{ rk: 'board rank', n: 'name', pos: 'position', age: 'age', offer: 'best offer', bids: 'bids', last: 'latest bid' }[AS.sort.k] || `last season's ${STATS.find((x) => x[0] === AS.sort.k)[1]}`}</span>`)}</div>`;
    tick(cfg);
    const again = (keepFocus) => { const y = scrollY; auctionPage().then(() => { scrollTo(0, y); if (keepFocus) { const n = document.getElementById('auq'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }); };
    const inp = document.getElementById('auq'); inp.addEventListener('input', () => { AS.q = inp.value; AS.page = 0; again(true); });
    document.querySelectorAll('[data-af]').forEach((b) => b.addEventListener('click', () => { AS[b.dataset.af] = b.dataset.av; AS.page = 0; again(); }));
    document.querySelectorAll('[data-pg]').forEach((b) => b.addEventListener('click', () => { AS.page = +b.dataset.pg; AS.open = null; again(); }));
    document.querySelectorAll('[data-ak]').forEach((h) => h.addEventListener('click', () => { const k = h.dataset.ak; AS.sort = { k, dir: AS.sort.k === k ? -AS.sort.dir : ['rk', 'n', 'pos', 'age'].includes(k) ? 1 : -1 }; AS.page = 0; again(); }));
    document.querySelectorAll('[data-lot]').forEach((b) => b.addEventListener('click', (e) => { if (e.target.closest('a')) return; AS.open = AS.open === b.dataset.lot ? null : b.dataset.lot; again(); }));
  }

  function auctionTeam(ab) {
    const { cfg, state, byId, demo } = AU, t = T.find((x) => x.abbrev === ab); if (!t) return notFound();
    const s = state.teams[ab], closed = Date.now() >= cfg.close, filled = closed ? SMPAuction.fill(cfg, state).filter((x) => x.team === ab) : [];
    const mine = [...s.players.map((id) => ({ l: byId.get(id), b: state.lots.get(id).lead })), ...filled.map((x) => ({ l: byId.get(x.pid), b: x, fill: true }))];
    const spent = mine.reduce((a, x) => a + x.b.sal, 0), open = cfg.roster - mine.length, free = cfg.budget - spent - open;
    const tile = (x, star) => `<a class="dt${star ? ' star' : ''}" ${x.l.espn ? `href="https://www.espn.com/nba/player/_/id/${x.l.espn}" target="_blank" rel="noopener"` : ''}>${lface(x.l, star ? 56 : 44)}<b>${esc(x.l.n)}</b><span>${deal(x.b)}</span>${x.fill ? '<small>assigned</small>' : ''}</a>`;
    const depth = POSN.map((pos) => { const xs = mine.filter((x) => x.l.pos === pos).sort((a, b) => b.b.sal - a.b.sal || a.l.rk - b.l.rk);
      return `<div class="dl"><span class="dp">${pos}</span><div class="dts">${xs.map((x, i) => tile(x, !i)).join('') || '<span class="dn2">Nobody yet</span>'}</div></div>`; }).join('');
    const seg = (w, c, lab) => (w > 0 ? `<i style="flex:${w};background:${c}" title="${lab}"></i>` : '');
    const top = [...mine].sort((a, b) => b.b.sal - a.b.sal);
    const budget = `<div class="bud"><div class="budbar">${top.map((x, i) => seg(x.b.sal, `color-mix(in srgb, ${t.accent} ${100 - i * 6}%, var(--surface))`, `${x.l.n} $${x.b.sal}M`)).join('')}${seg(open, 'var(--faint)', `$${open}M held for ${open} open spots`)}${seg(Math.max(0, free), 'var(--soft)', `$${Math.max(0, free)}M free`)}</div>
      <div class="kv"><div><b>$${spent}M</b><span>Committed</span></div><div><b>$${open}M</b><span>Held for ${open} open spot${open === 1 ? '' : 's'}</span></div><div><b>$${Math.max(0, free)}M</b><span>Free to bid</span></div></div></div>`;
    const status = (b) => (b.ok ? (state.lots.get(b.pid).lead.team === ab && state.lots.get(b.pid).lead.t === b.t ? ['Leading', 'up'] : ['Outbid', 'muted']) : [b.why, 'dn']);
    const all = state.log.filter((b) => b.team === ab).reverse(), shown = AS.allBids ? all : all.slice(0, 8);
    const bids = shown.map((b) => { const l = byId.get(b.pid), [txt, cls] = status(b); return `<div class="row r-mybid">${l ? lface(l, 30) : '<span class="face" style="width:30px;height:30px"></span>'}<span class="who"><b>${esc(l ? l.n : b.name || 'Unknown player')}</b><span class="${cls}">${esc(txt)}</span></span><span class="v">${Number.isFinite(b.sal) && Number.isFinite(b.yrs) ? deal(b) : '—'}</span><span class="n">${ago(b.t)}</span></div>`; }).join('') || '<p class="note">No bids yet.</p>';
    const bid = formUrl(cfg, null, ab);
    $app.innerHTML = `<section class="card hd" style="--c:${t.accent};--wm:url(${t.logo})">${logo(t.tid, 96)}<div><h1>${tname(t.tid)}</h1><div class="sub"><span>${closed ? 'Final auction roster' : 'The roster if every leading bid holds'}</span>${(cfg.ai || []).includes(ab) ? '<span>Bids placed by AI for an absent owner</span>' : ''}</div>
        <div class="sub" style="margin-top:10px"><a class="btn" href="#auction">← All players</a>${bid && !closed ? `<a class="btn go" href="${bid}" target="_blank" rel="noopener">Place a bid</a>` : ''}</div></div>
        <div class="nums"><div><b>${mine.length}/${cfg.roster}</b><span>Roster</span></div><div><b>$${spent}M</b><span>Committed</span></div><div><b>$${cfg.budget - spent}M</b><span>Left</span></div></div></section>
      ${demo ? '<p class="au-demo">Demo bids, made up to show how the page works.</p>' : ''}
      <div class="grid g-main"><div class="stack">${card('Depth chart', `<div class="depth">${depth}</div>`, '<span>Biggest contract first · click a player for his ESPN page</span>')}</div>
        <aside class="stack">${card('Budget', budget, `<span>$${cfg.budget}M</span>`)}${card('Bids', bids + (all.length > 8 ? `<button type="button" class="btn wide" id="morebids">${AS.allBids ? 'Show fewer' : `Show all ${all.length}`}</button>` : ''), `<span>${s.bids} placed · ${s.rejected} refused</span>`)}</aside></div>`;
    document.getElementById('morebids')?.addEventListener('click', () => { AS.allBids = !AS.allBids; const y = scrollY; auctionTeam(ab); scrollTo(0, y); });
  }

  const notFound = () => { $app.innerHTML = '<p class="muted">That page does not exist. <a href="#home">Back to the front page</a>.</p>'; };

  /* ---------- router ---------- */
  function route() {
    const h = location.hash.slice(1) || 'home', i = h.indexOf('-'); let kind = i < 0 ? h : h.slice(0, i), arg = i < 0 ? '' : h.slice(i + 1);
    if (D.preseason && kind !== 'auction') { kind = 'auction'; arg = ''; }   // nothing has been played yet: every page is the auction
    const nav = { home: 'home', scores: 'scores', game: 'scores', standings: 'standings', leaders: 'players', players: 'players', player: 'players', freeagents: 'freeagents', draft: 'draft', recap: 'home', auction: 'auction' }[kind];
    clearInterval(auTimer);
    document.querySelectorAll('[data-nav]').forEach((a) => (a.dataset.nav === nav ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    ({ home, scores: () => scores(+arg), game: () => game(+arg), standings, team: () => teamPage(arg), player: () => player(+arg), leaders: () => playersPage('leaders'), players: () => playersPage(arg), freeagents: freeAgents, draft: draftPage, recap: () => recapPage(+arg), auction: () => auctionPage(arg) }[kind] || notFound)();
    window.scrollTo(0, 0);
    const pl = kind === 'player' ? P.get(+arg) : null, gm = kind === 'game' ? byGid.get(+arg) : null;
    const tt = kind === 'team' || (kind === 'auction' && arg) ? T.find((t) => t.abbrev === arg) : pl && pl.tid >= 0 ? team(pl.tid) : null;
    const name = pl ? pl.name : tt ? `${tt.region} ${tt.name}${kind === 'auction' ? ' auction' : ''}` : gm ? `${team(gm.away.tid).abbrev} ${gm.away.pts}, ${team(gm.home.tid).abbrev} ${gm.home.pts}` : { scores: 'Scores', standings: 'Standings', players: 'Players', auction: 'Auction', freeagents: 'Free agents', draft: 'Draft' }[kind];
    document.title = name ? `${name} · SMP League` : 'SMP League';
    let fav = document.getElementById('fav'); if (!fav) { fav = document.head.appendChild(document.createElement('link')); fav.id = 'fav'; fav.rel = 'icon'; }
    fav.href = tt ? tt.logo : 'data:,';
  }

  Promise.all([fetch('data/league.json', { cache: 'no-cache' }).then((r) => r.json()), fetch('data/recaps.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}))]).then(([d, rc]) => {
    D = d; R = rc;
    if (D.preseason) { T = D.teams; P = new Map(); document.querySelectorAll('[data-nav]').forEach((a) => { a.hidden = a.dataset.nav !== 'auction'; }); } else derive();
    document.getElementById('when').textContent = D.preseason ? `${D.season} · preseason` : `${D.season} · through Game ${lastDay}`;
    document.getElementById('logos').innerHTML = [...T].sort((a, b) => a.region.localeCompare(b.region)).map((t) => `<a href="#${D.preseason ? 'auction' : 'team'}-${t.abbrev}" title="${tname(t.tid)}">${logo(t.tid, 22)}${t.abbrev}</a>`).join('');
    addEventListener('hashchange', route); route();
  }).catch((e) => { console.error(e); $app.innerHTML = '<p class="muted">The league data did not load. Reload the page.</p>'; });
})();
