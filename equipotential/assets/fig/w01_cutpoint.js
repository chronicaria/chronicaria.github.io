/* w01_cutpoint.js — Figure 3, replaced by the algorithm that made it.
 *
 * The paper's only hand-drawn figure. Here it is the actual construction, run
 * on a meridional slice: node signs, a sweep along grid edges, a safeguarded
 * Newton root on every sign-changing one, the eta = 0.45 admissibility filter
 * throwing away grazing cuts, primaries absorbing secondaries, and the stencil
 * switching from centred to one-sided where an arm is missing.
 *
 * The grid is frozen across the whole q range on purpose. Drag q and the cut
 * points slide along the edges while not one grid line moves: that is what "no
 * remeshing" means, and it is the one thing a still cannot show. (The solver
 * sizes its own box per figure; this widget does not, so that the box can be
 * seen standing still.)
 */

import * as G from '../core/geometry.js';
import { register, onResize, palette } from '../core/bus.js';
import { control, tabs } from '../core/scrub.js';

const ETA = 0.45;                 // admissibility: |n_nu| / ||n|| must clear it
const TOL = 1e-13;
const W = 1.62;                   // half-width, frozen: 1.08 * R_e at break-up
const N_PUB = 40, Q_PUB = 0.12;

const STAGES = [
  ['signs', 'node signs, χ = [φ < 0]'],
  ['xedge', 'sweep the x-edges'],
  ['zedge', 'sweep the z-edges'],
  ['filter', 'reject grazing cuts, η = 0.45'],
  ['classify', 'primaries absorb secondaries'],
  ['stencil', 'the stencil: centred, or one-sided']
];
const FRAMES = [0, 0, 0, 26, 26, 40];   // the first three scale with N

export default function mount(root) {
  const strip = root.querySelector('.plate-controls');
  const canvas = root.querySelector('canvas');
  const read = root.querySelector('.readouts');
  const cap = root.querySelector('.stage-label');

  let N = N_PUB, q = Q_PUB, mu = 0.30, D = 3.0, family = 'oblate';
  let showRejects = true, showSecondary = true, showStencil = true;
  let prog = 0, playing = false, built = null;
  let phi2, grad2;

  // Static backdrop layers. The grid and the node signs do not change from
  // frame to frame, and redrawing 40k node marks every frame is the one thing
  // that would make this widget slow, so they are painted once per rebuild.
  const bg = document.createElement('canvas');
  const nodes = document.createElement('canvas');
  let view = null;

  /* ── the figure, restricted to the y = 0 meridional slice ─────────── */

  function setFigure() {
    if (family === 'oblate') {
      phi2 = (x, z) => G.phiOb(x, 0, z, q);
      grad2 = (x, z, o) => G.gradOb(x, 0, z, q, o);
    } else {
      const ls = G.tidal(mu, D);
      phi2 = (x, z) => G.phiTd(x, 0, z, ls);
      grad2 = (x, z, o) => G.gradTd(x, 0, z, ls, o);
    }
  }

  /**
   * Safeguarded Newton on a sign-changing grid interval, with bracket
   * tightening and a bisection fallback whenever a step leaves (a,b) or is not
   * finite. The iterates are kept so the animation can show it converging
   * rather than assert that it does.
   */
  function rootOnInterval(fixed, axis, lo, hi) {
    const at = axis === 0 ? (t) => phi2(t, fixed) : (t) => phi2(fixed, t);
    const g = [0, 0, 0];
    const dv = axis === 0
      ? (t) => grad2(t, fixed, g)[0]
      : (t) => grad2(fixed, t, g)[2];

    let fa = at(lo), fb = at(hi);
    if (Math.abs(fa) <= TOL) return { root: lo, trail: [lo], iters: 0 };
    if (Math.abs(fb) <= TOL) return { root: hi, trail: [hi], iters: 0 };

    let a = lo, b = hi;
    let x = (lo * Math.abs(fb) + hi * Math.abs(fa)) / (Math.abs(fa) + Math.abs(fb));
    if (!isFinite(x) || x <= a || x >= b) x = 0.5 * (a + b);
    const trail = [x];
    for (let it = 1; it <= 64; it++) {
      const fx = at(x);
      if (Math.abs(fx) <= TOL || Math.abs(b - a) <= TOL) return { root: x, trail, iters: it };
      if (fa * fx <= 0) { b = x; fb = fx; } else { a = x; fa = fx; }
      const d = dv(x);
      let xn = Math.abs(d) > 1e-14 ? x - fx / d : NaN;
      if (!isFinite(xn) || xn <= a || xn >= b) xn = 0.5 * (a + b);
      x = xn;
      if (trail.length < 8) trail.push(x);
    }
    return { root: 0.5 * (a + b), trail, iters: 64 };
  }

  /* ── the construction ─────────────────────────────────────────────── */

  function build() {
    setFigure();
    const h = 2 * W / N;
    const ax = (i) => -W + i * h;
    const chi = new Uint8Array((N + 1) * (N + 1));
    const at = (i, j) => chi[j * (N + 1) + i];
    for (let j = 0; j <= N; j++) {
      for (let i = 0; i <= N; i++) chi[j * (N + 1) + i] = phi2(ax(i), ax(j)) < 0 ? 1 : 0;
    }

    // Steps 2-3. The two sweeps run in a fixed order, x-edges then z-edges;
    // that order sets the primary tie-break downstream, so it is load-bearing.
    const cuts = [];
    const g = [0, 0, 0];
    const push = (type, i, j) => {
      const lo = type === 0 ? ax(i) : ax(j), hi = lo + h;
      const fixed = type === 0 ? ax(j) : ax(i);
      const r = rootOnInterval(fixed, type, lo, hi);
      const x = type === 0 ? r.root : fixed;
      const z = type === 0 ? fixed : r.root;
      grad2(x, z, g);
      const gn = Math.hypot(g[0], g[2]);
      const cos = gn <= 1e-300 ? 0 : Math.abs(type === 0 ? g[0] : g[2]) / gn;
      cuts.push({
        type, bi: i, bj: j, x, z, theta: Math.min(1, Math.max(0, (r.root - lo) / h)),
        cos, ok: cos >= ETA, trail: r.trail, iters: r.iters,
        ci: i, cj: j, dist: 0, primary: false, assoc: -1, kp: -1, km: -1,
        c0: 0, cp: 0, cm: 0, idx: cuts.length
      });
    };
    for (let i = 0; i < N; i++) for (let j = 0; j <= N; j++) if (at(i, j) !== at(i + 1, j)) push(0, i, j);
    for (let i = 0; i <= N; i++) for (let j = 0; j < N; j++) if (at(i, j) !== at(i, j + 1)) push(1, i, j);

    const kept = cuts.filter((c) => c.ok);

    // Step 4: bucket each cut at its nearest node; the closest in a bucket is
    // the primary and the rest become secondaries that interpolate from it.
    const bucket = new Map();
    for (const c of kept) {
      if (c.theta <= 0.5) c.dist = c.theta * h;
      else { if (c.type === 0) c.ci++; else c.cj++; c.dist = (1 - c.theta) * h; }
      const key = c.cj * (N + 2) + c.ci;
      if (!bucket.has(key)) bucket.set(key, []);
      bucket.get(key).push(c);
    }
    for (const list of bucket.values()) {
      let best = list[0];
      for (const c of list) if (c.dist < best.dist) best = c;
      best.primary = true;
      for (const c of list) c.assoc = best.idx;
    }

    // Step 5: neighbours, by scanning m in -2..2 transversally; first hit wins.
    const byEdge = new Map();
    const key = (t, i, j) => (t * (N + 3) + j) * (N + 3) + i;
    for (const c of kept) byEdge.set(key(c.type, c.bi, c.bj), c);
    const look = (t, i, j) =>
      (i < 0 || j < 0 || i > N || j > N) ? null : byEdge.get(key(t, i, j)) || null;
    const arm = (c, dA) => {
      for (let m = -2; m <= 2; m++) {
        const n = c.type === 0 ? look(0, c.bi + m, c.bj + dA) : look(1, c.bi + dA, c.bj + m);
        if (n) return n.idx;
      }
      return -1;
    };
    const prim = kept.filter((c) => c.primary);
    for (const c of prim) { c.kp = arm(c, 1); c.km = arm(c, -1); }

    // Step 6: the quadratic interpolation weights on every secondary. They sum
    // to exactly 1, which the readout prints because that sum is the check.
    const sec = kept.filter((c) => !c.primary);
    for (const c of sec) {
      let t = c.theta;
      if ((c.type === 0 && c.ci !== c.bi) || (c.type === 1 && c.cj !== c.bj)) t -= 1;
      c.c0 = 1 - t * t; c.cp = 0.5 * (t + t * t); c.cm = 0.5 * (-t + t * t);
    }

    built = {
      h, ax, chi, cuts, kept, prim, sec,
      oneSided: prim.filter((c) => c.kp < 0 || c.km < 0).length,
      nodeCount: (N + 1) * (N + 1), rejected: cuts.length - kept.length
    };
  }

  /* ── animation clock ──────────────────────────────────────────────── */

  const frames = () => [N + 1, N, N + 1, FRAMES[3], FRAMES[4], FRAMES[5]];
  const total = () => frames().reduce((a, b) => a + b, 0);

  function stageOf(p) {
    const f = frames();
    let acc = 0;
    for (let s = 0; s < f.length; s++) {
      if (p < acc + f[s]) return { s, t: (p - acc) / f[s], frame: p - acc };
      acc += f[s];
    }
    return { s: 5, t: 1, frame: f[5] };
  }
  const stageIndex = (k) => STAGES.findIndex(([n]) => n === k);

  /* ── controls ─────────────────────────────────────────────────────── */

  tabs(strip, {
    label: 'Figure', value: family,
    options: [['oblate', 'Roche oblate'], ['tidal', 'Tidal egg']],
    onInput: (v) => { family = v; qc.hidden = v !== 'oblate'; muc.hidden = dc.hidden = v !== 'tidal'; rebuild(); }
  });

  control(strip, {
    label: '<span class="lc">N</span> — grid resolution', min: 16, max: 200, step: 2, value: N,
    published: N_PUB, digits: 0,
    onInput: (v) => { N = v; prog = Math.min(prog, total()); rebuild(); }
  });

  const qc = control(strip, {
    label: '<span class="lc">q</span> — centrifugal ratio', min: 0, max: G.Q_BREAK, step: 0.0005,
    value: q, published: Q_PUB, digits: 4, onInput: (v) => { q = v; rebuild(); }
  });
  const muc = control(strip, {
    label: '<span class="lc">μ</span> — companion mass ratio', min: 0, max: 1.0, step: 0.001, value: mu,
    published: 0.30, digits: 3, onInput: (v) => { mu = v; rebuild(); }
  });
  const dc = control(strip, {
    label: '<span class="lc">D</span> — separation', min: 1.8, max: 6, step: 0.01, value: D,
    published: 3.0, digits: 2, onInput: (v) => { D = v; rebuild(); }
  });
  muc.hidden = dc.hidden = true;

  const scrubc = control(strip, {
    label: 'Construction step', min: 0, max: total(), step: 1, value: 0,
    format: (v) => `${STAGES[stageOf(v).s][0]} · ${Math.round(v)}/${total()}`,
    onInput: (v) => { prog = v; stop(); h.dirty(); }
  });

  const toggles = document.createElement('div');
  toggles.className = 'ctl';
  toggles.innerHTML = '<span class="label">Layers</span><div class="tab-row">' +
    '<button type="button" class="tab" data-k="rej" aria-pressed="true">rejected cuts</button>' +
    '<button type="button" class="tab" data-k="sec" aria-pressed="true">secondaries</button>' +
    '<button type="button" class="tab" data-k="sten" aria-pressed="true">stencil</button>' +
    '<button type="button" class="tab" data-k="play">▶ replay</button></div>';
  strip.appendChild(toggles);
  const play = toggles.querySelector('[data-k="play"]');

  function stop() { playing = false; play.textContent = '▶ replay'; h.animate(false); }

  toggles.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.k === 'play') {
      if (playing) { stop(); return; }
      prog = 0; playing = true; play.textContent = '❙❙ pause'; h.animate(true);
      return;
    }
    const on = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(on));
    if (b.dataset.k === 'rej') showRejects = on;
    if (b.dataset.k === 'sec') showSecondary = on;
    if (b.dataset.k === 'sten') showStencil = on;
    h.dirty();
  });

  /* ── readouts ─────────────────────────────────────────────────────── */

  read.innerHTML = [
    ['nodes evaluated, (N+1)²', 'nodes'],
    ['sign-changing edges', 'edges'],
    ['rejected by η = 0.45', 'rej'],
    ['primaries', 'prim'],
    ['secondaries', 'sec'],
    ['one-sided stencils', 'os'],
    ['secondary weights, c₀ + c₊ + c₋', 'sum']
  ].map(([l, k]) => `<div class="ro"><span class="ro-k">${l}</span>` +
    `<span class="ro-v calc" data-k="${k}">—</span></div>`).join('');
  const cell = (k) => read.querySelector(`[data-k="${k}"]`);

  function readouts() {
    const b = built;
    cell('nodes').textContent = b.nodeCount.toLocaleString();
    cell('edges').textContent = b.cuts.length.toLocaleString();
    cell('rej').textContent = b.rejected.toLocaleString();
    cell('prim').textContent = b.prim.length.toLocaleString();
    cell('sec').textContent = b.sec.length.toLocaleString();
    cell('os').textContent = b.oneSided.toLocaleString();
    cell('sum').textContent = b.sec.length
      ? (b.sec[0].c0 + b.sec[0].cp + b.sec[0].cm).toPrecision(17)
      : 'no secondaries at this N';
  }

  /* ── the static backdrop ──────────────────────────────────────────── */

  function measure() {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    const pad = 14;
    const s = (Math.min(w, h) - 2 * pad) / (2 * W);
    view = { w, h, dpr, s, ox: w / 2, oy: h / 2 };
    for (const c of [canvas, bg, nodes]) {
      if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr; }
    }
    return view;
  }

  const X = (x) => view.ox + x * view.s;
  const Z = (z) => view.oy - z * view.s;

  let bgTheme = null;

  function paintBackdrop() {
    const p = palette(), b = built, v = view;
    bgTheme = document.documentElement.dataset.theme || '';
    const gctx = bg.getContext('2d');
    gctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
    gctx.clearRect(0, 0, v.w, v.h);
    gctx.fillStyle = p.panel; gctx.fillRect(0, 0, v.w, v.h);

    gctx.strokeStyle = p.rule; gctx.lineWidth = 0.9;
    gctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const t = b.ax(i);
      gctx.moveTo(X(t), Z(-W)); gctx.lineTo(X(t), Z(W));
      gctx.moveTo(X(-W), Z(t)); gctx.lineTo(X(W), Z(t));
    }
    gctx.stroke();

    gctx.strokeStyle = p['rule-strong']; gctx.lineWidth = 1;
    gctx.beginPath();
    const ls = family === 'tidal' ? G.tidal(mu, D) : null;
    for (let k = 0; k <= 280; k++) {
      const th = Math.PI * 2 * k / 280;
      const ux = Math.sin(th), uz = Math.cos(th);
      const t = ls ? G.radiusTd(ux, 0, uz, ls) : G.radiusOb(Math.abs(ux), q);
      if (k) gctx.lineTo(X(t * ux), Z(t * uz)); else gctx.moveTo(X(t * ux), Z(t * uz));
    }
    gctx.closePath(); gctx.stroke();

    const nctx = nodes.getContext('2d');
    nctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
    nctx.clearRect(0, 0, v.w, v.h);
    // The sign field is a stipple, not a fill: it has to be readable without
    // out-shouting the cut points, which are what the figure is about.
    const px = Math.max(0.9, Math.min(1.9, v.s * b.h * 0.11));
    nctx.fillStyle = p.prussian;
    for (let j = 0; j <= N; j++) {
      for (let i = 0; i <= N; i++) {
        if (!b.chi[j * (N + 1) + i]) continue;
        nctx.fillRect(X(b.ax(i)) - px, Z(b.ax(j)) - px, 2 * px, 2 * px);
      }
    }
    nctx.fillStyle = p.gray;
    nctx.globalAlpha = 0.55;
    for (let j = 0; j <= N; j++) {
      for (let i = 0; i <= N; i++) {
        if (b.chi[j * (N + 1) + i]) continue;
        nctx.fillRect(X(b.ax(i)) - px * 0.6, Z(b.ax(j)) - px * 0.6, px * 1.2, px * 1.2);
      }
    }
    nctx.globalAlpha = 1;
  }

  /* ── paint ────────────────────────────────────────────────────────── */

  function draw(dt) {
    if (!built) return;
    if (playing && dt) {
      prog += dt * (total() / 9);            // ~9 s for the whole construction
      if (prog >= total()) { prog = total(); stop(); }
      scrubc.value = Math.round(prog);
    }
    // The backdrop is cached, so a theme flip has to invalidate it explicitly.
    if (!view || bgTheme !== (document.documentElement.dataset.theme || '')) {
      measure(); paintBackdrop();
    }

    const b = built, p = palette(), v = view;
    const ctx = canvas.getContext('2d', { alpha: false });
    ctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
    ctx.drawImage(bg, 0, 0, v.w, v.h);

    const st = stageOf(prog);
    const inS = (k) => st.s === stageIndex(k);
    const past = (k) => st.s > stageIndex(k);

    /* step 1 — the node signs, revealed row by row from the south */
    if (inS('signs')) {
      const yTop = Z(b.ax(Math.min(N, st.frame)));
      ctx.save(); ctx.beginPath(); ctx.rect(0, yTop, v.w, v.h - yTop); ctx.clip();
      ctx.drawImage(nodes, 0, 0, v.w, v.h);
      ctx.restore();
      caption(ctx, p, v, 'one evaluation of φ per node — the only place the level set is sampled');
      return finish();
    }
    ctx.drawImage(nodes, 0, 0, v.w, v.h);

    const upToX = inS('xedge') ? st.frame : N;
    const upToZ = inS('zedge') ? st.frame : (past('zedge') ? N + 1 : -1);
    const filtering = past('zedge');
    const classified = past('filter');
    const rc = Math.max(1.5, Math.min(2.8, v.s * b.h * 0.18));

    for (const c of b.cuts) {
      if (c.type === 0 ? c.bi >= upToX : (upToZ < 0 || c.bi >= upToZ)) continue;

      if (!c.ok) {
        if (!filtering || !showRejects) continue;
        cone(ctx, p, X(c.x), Z(c.z), c.type === 0, rc * 3.6, inS('filter') ? st.t : 1);
        ctx.fillStyle = p.ghost;
        ctx.beginPath(); ctx.arc(X(c.x), Z(c.z), rc * 0.8, 0, Math.PI * 2); ctx.fill();
        continue;
      }
      if (classified && !c.primary) {
        if (!showSecondary) continue;
        const a = b.cuts[c.assoc];
        ctx.strokeStyle = p.rule; ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(X(c.x), Z(c.z)); ctx.lineTo(X(a.x), Z(a.z)); ctx.stroke();
        ctx.strokeStyle = p.prussian; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(X(c.x), Z(c.z), rc * 0.85, 0, Math.PI * 2); ctx.stroke();
        continue;
      }
      ctx.fillStyle = p.prussian;
      ctx.fillRect(X(c.x) - rc, Z(c.z) - rc, 2 * rc, 2 * rc);
    }

    /* the safeguarded Newton, caught mid-convergence on the sweep frontier */
    if (inS('xedge') || inS('zedge')) {
      const col = inS('xedge') ? 0 : 1;
      const front = b.cuts.filter((c) => c.type === col && c.bi === st.frame);
      ctx.strokeStyle = p.royal; ctx.lineWidth = 1;
      for (const c of front) {
        for (let k = 0; k < c.trail.length; k++) {
          const t = c.trail[k];
          const x = col === 0 ? t : b.ax(c.bi), z = col === 0 ? b.ax(c.bj) : t;
          ctx.beginPath();
          ctx.arc(X(x), Z(z), Math.max(1, 3.4 - 0.35 * k), 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      caption(ctx, p, v, `${col === 0 ? 'x' : 'z'}-edges · secant start, then safeguarded Newton — ` +
        `${front.length ? front[0].iters : 0} iterations to |φ| ≤ 1×10⁻¹³`);
      return finish();
    }
    if (inS('filter')) {
      caption(ctx, p, v, `η = 0.45 · a cut survives only if its normal lies within ` +
        `${(Math.acos(ETA) * 180 / Math.PI).toFixed(1)}° of the edge it sits on — ${b.rejected} rejected`);
      return finish();
    }
    if (inS('classify')) {
      caption(ctx, p, v, 'one primary per grid node · every other cut in that bucket becomes ' +
        'a secondary and interpolates from it');
      return finish();
    }

    /* step 6 — the stencil arms, and where they run out */
    if (showStencil) {
      const upTo = Math.floor(b.prim.length * Math.min(1, st.t * 1.15));
      for (let k = 0; k < upTo; k++) {
        const c = b.prim[k];
        const one = c.kp < 0 || c.km < 0;
        ctx.strokeStyle = one ? p.ink : p.royal;
        ctx.lineWidth = one ? 1.5 : 0.9;
        for (const nk of [c.kp, c.km]) {
          if (nk < 0) continue;
          const n = b.cuts[nk];
          ctx.beginPath(); ctx.moveTo(X(c.x), Z(c.z)); ctx.lineTo(X(n.x), Z(n.z)); ctx.stroke();
        }
        if (one) {
          ctx.beginPath(); ctx.arc(X(c.x), Z(c.z), rc * 2.1, 0, Math.PI * 2); ctx.stroke();
        }
      }
    }
    caption(ctx, p, v, `centred where both arms exist · one-sided at ${b.oneSided} of ` +
      `${b.prim.length} primaries, ringed`);
    return finish();

    function finish() {
      cap.textContent = `${st.s + 1} · ${STAGES[st.s][1]}`;
      readouts();
    }
  }

  function cone(ctx, p, x, y, isX, r, alpha) {
    const half = Math.acos(ETA);
    ctx.save();
    ctx.globalAlpha = 0.55 * alpha;
    ctx.fillStyle = p['accent-soft'];
    for (const dir of isX ? [0, Math.PI] : [-Math.PI / 2, Math.PI / 2]) {
      ctx.beginPath(); ctx.moveTo(x, y);
      ctx.arc(x, y, r, dir - half, dir + half); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  function caption(ctx, p, v, text) {
    ctx.font = `${v.w < 520 ? 9 : 11}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    ctx.textAlign = 'left';
    // Drop trailing clauses rather than let the line run off the canvas.
    let s = text;
    while (ctx.measureText(s).width > v.w - 20 && s.includes(' · ')) {
      s = s.slice(0, s.lastIndexOf(' · '));
    }
    ctx.fillStyle = p.panel;                    // a strip, so the stipple behind
    ctx.fillRect(0, v.h - 22, v.w, 22);         // it never eats the words
    ctx.fillStyle = p.gray;
    ctx.fillText(s, 10, v.h - 8);
  }

  /* ── wiring ───────────────────────────────────────────────────────── */

  function rebuild() {
    build();
    measure();
    paintBackdrop();
    scrubc.input.max = total();
    h.dirty();
  }

  const h = register(root, draw, () => {
    // The representative frame — for print, reduced motion and the first paint
    // — is the finished construction, never a blank box.
    prog = total(); stop(); scrubc.value = prog;
    if (built) { measure(); paintBackdrop(); draw(0); }
  });

  onResize(canvas, { dirty: () => { measure(); paintBackdrop(); h.dirty(); } });
  rebuild();
  prog = total();
  scrubc.value = prog;

  // Autoplay once when the plate first comes into view, then leave it scrubbed.
  let armed = true;
  new IntersectionObserver((es) => {
    for (const e of es) {
      if (!e.isIntersecting || !armed) continue;
      armed = false;
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      prog = 0; playing = true; play.textContent = '❙❙ pause'; h.animate(true);
    }
  }, { threshold: 0.35 }).observe(root);
}
