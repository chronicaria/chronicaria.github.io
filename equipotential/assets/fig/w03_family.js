/* w03_family.js — Figure 2, made continuous.
 *
 * The paper prints three stills: sphere, oblate, tidal egg. They are one path
 * through a two-parameter family, and the interesting part is the path. Drag q
 * from 0 to 0.2963 and the sphere flattens while the two equatorial roots of
 * q(R) = 2/R^2 - 2/R^3 slide together and annihilate at R = 3/2.
 *
 * Everything here is closed form. There is no data file behind this figure and
 * no solver output in it; every printed number is computed in the browser and
 * marked as such.
 */

import * as G from '../core/geometry.js';
import { register, onResize } from '../core/bus.js';
import { control, tabs } from '../core/scrub.js';
import { createSurface } from '../core/surface.js';

const Q_PUB = 0.12, MU_PUB = 0.30, D_PUB = 3.0, EL_PUB = 24;

export default function mount(root) {
  const strip = root.querySelector('.plate-controls');
  const canvas = root.querySelector('canvas');
  const fold = root.querySelector('.fold');
  const read = root.querySelector('.readouts');

  const S = createSurface(canvas);
  let family = 'oblate', q = Q_PUB, mu = MU_PUB, D = D_PUB, mode = 'geff', beta = 0.08;
  let snapped = null;

  /* ── controls ─────────────────────────────────────────────────────── */

  const fam = tabs(strip, {
    label: 'Figure', value: family,
    options: [['oblate', 'Roche oblate'], ['tidal', 'Tidal egg']],
    onInput: (v) => { family = v; showFor(v); snapped = null; rebuild(); }
  });

  const qc = control(strip, {
    label: '<span class="lc">q</span> — centrifugal ratio', min: 0, max: G.Q_BREAK, step: 0.0005,
    value: q, published: Q_PUB, digits: 4,
    onInput: (v) => { q = v; snapped = null; rebuild(); }
  });

  const muc = control(strip, {
    label: '<span class="lc">μ</span> — companion mass ratio', min: 0, max: 1.2, step: 0.001,
    value: mu, published: MU_PUB, digits: 3,
    onInput: (v) => { mu = v; snapped = null; rebuild(); }
  });

  const dc = control(strip, {
    label: '<span class="lc">D</span> — separation', min: 1.6, max: 6, step: 0.01,
    value: D, published: D_PUB, digits: 2,
    onInput: (v) => { D = v; snapped = null; rebuild(); }
  });

  tabs(strip, {
    label: 'Colour', value: mode,
    options: [['geff', 'g_eff = ‖∇φ‖'], ['forcing', '(g_eff / g_pole)^β']],
    onInput: (v) => { mode = v; bc.hidden = v !== 'forcing'; S.setMode(v); h.dirty(); }
  });

  const bc = tabs(strip, {
    label: '<span class="lc">β</span> — darkening exponent', value: '0.08',
    options: [['0.08', '0.08 convective'], ['0.25', '0.25 radiative']],
    onInput: (v) => { beta = +v; S.setBeta(beta); h.dirty(); }
  });
  bc.hidden = true;

  const elev = control(strip, {
    label: 'Elevation', min: -80, max: 80, step: 1, value: EL_PUB, published: EL_PUB,
    digits: 0, unit: '°',
    onInput: (v) => { S.elevation = v * Math.PI / 180; h.dirty(); }
  });
  S.elevation = EL_PUB * Math.PI / 180;

  /* the bit-exact reduction, as a gesture rather than an appendix line */
  const snap = document.createElement('div');
  snap.className = 'ctl';
  snap.innerHTML = '<span class="label">The <span class="lc">μ → 0</span> limit</span>' +
    '<div class="tab-row"><button type="button" class="tab">set μ = 0, D = q<sup>−1/3</sup></button></div>';
  strip.appendChild(snap);
  snap.querySelector('button').addEventListener('click', () => {
    family = 'tidal';
    mu = 0;
    D = Math.pow(q > 1e-4 ? q : Q_PUB, -1 / 3);
    muc.value = mu; dc.value = D; fam.value = 'tidal';
    showFor('tidal');
    snapped = identityResidual(D);
    rebuild();
  });

  function showFor(v) {
    qc.hidden = v !== 'oblate';
    muc.hidden = dc.hidden = v !== 'tidal';
  }
  showFor(family);

  /* ── figure ───────────────────────────────────────────────────────── */

  const current = () => family === 'oblate'
    ? G.figure('oblate', { q: Math.min(q, G.Q_BREAK - 1e-9) })
    : G.figure('tidal', { mu, D });

  function rebuild() { S.setFigure(current()); S.setMode(mode); h.dirty(); }

  /**
   * max |phi_td|_{mu=0} - phi_ob|_{q=1/D^3}| sampled through the volume. The
   * construction is meant to reduce bit-exactly, so anything but 0.0 is a bug
   * and the widget says so out loud rather than rounding it away.
   */
  function identityResidual(sep) {
    const ls = G.tidal(0, sep), qe = 1 / (sep * sep * sep);
    let m = 0;
    for (let j = 1; j < 40; j++) {
      const th = Math.PI * j / 40, st = Math.sin(th), ct = Math.cos(th);
      for (let i = 0; i < 40; i++) {
        const ph = Math.PI * 2 * i / 40;
        for (const t of [0.6, 1.0, 1.4, 2.2]) {
          const x = t * st * Math.cos(ph), y = t * st * Math.sin(ph), z = t * ct;
          m = Math.max(m, Math.abs(G.phiTd(x, y, z, ls) - G.phiOb(x, y, z, qe)));
        }
      }
    }
    return m;
  }

  /* ── readouts ─────────────────────────────────────────────────────── */

  read.innerHTML =
    ['a', 'b', 'c', 'd'].map((k) =>
      `<div class="ro"><span class="ro-k" data-k="${k}k">—</span>` +
      `<span class="ro-v calc" data-k="${k}v">—</span></div>`).join('') +
    '<div class="ro ro--wide"><span class="ro-k">μ → 0 reduction</span>' +
    '<span class="ro-v calc" data-k="id">not yet exercised</span></div>';
  const cell = (k) => read.querySelector(`[data-k="${k}"]`);

  function put(i, k, v) {
    cell('abcd'[i] + 'k').textContent = k;
    cell('abcd'[i] + 'v').textContent = v;
  }

  function readouts() {
    let ratio;
    if (family === 'oblate') {
      const Re = G.equatorialRadius(Math.min(q, G.Q_BREAK));
      const g = G.gradOb(Re, 0, 0, q);
      ratio = Math.hypot(g[0], g[1], g[2]);            // g_pole is exactly 1 here
      put(0, 'R_e — equatorial radius', '≈ ' + Re.toFixed(5));
      put(1, 'f — flattening', '≈ ' + (1 - 1 / Re).toFixed(5));
    } else {
      const ls = G.tidal(mu, D), geo = G.tidalGeometry(ls);
      const t = G.radiusTd(1, 0, 0, ls);
      const g = G.gradTd(t, 0, 0, ls);
      ratio = Math.hypot(g[0], g[1], g[2]) / G.gPoleTidal(ls);
      put(0, 'x_sub — sub-companion radius', geo.overflow ? 'overflows the lobe' : '≈ ' + geo.xSub.toFixed(5));
      put(1, 'ℱ — Roche fill fraction', geo.overflow ? '> 1' : '≈ ' + geo.fill.toFixed(5));
    }
    put(2, 'g_eq / g_pole', '≈ ' + ratio.toFixed(6));
    const contrast = 1 - Math.pow(ratio, beta);
    put(3, `pole-to-equator forcing contrast, β = ${beta}`,
        '≈ ' + (Math.abs(contrast) < 1e-9 ? contrast.toExponential(2) : contrast.toFixed(6)));
    cell('id').textContent = snapped == null ? 'not yet exercised'
      : (snapped === 0 ? 'max |Δφ| = 0.0 — bit-exact' : `max |Δφ| = ${snapped.toExponential(3)} — NOT bit-exact`);
    cell('id').classList.toggle('bad', snapped != null && snapped !== 0);
  }

  /* ── the break-up fold ────────────────────────────────────────────── */

  const W = 108, H = 66, M = { l: 13, r: 5, t: 8, b: 13 };
  const R0 = 1, R1 = 3, QMAX = G.Q_BREAK * 1.2;
  const fx = (R) => M.l + (R - R0) / (R1 - R0) * (W - M.l - M.r);
  const fy = (v) => H - M.b - v / QMAX * (H - M.t - M.b);
  fold.setAttribute('viewBox', `0 0 ${W} ${H}`);

  let curveD = '';
  for (let i = 0; i <= 180; i++) {
    const R = R0 + (R1 - R0) * i / 180;
    curveD += (i ? 'L' : 'M') + fx(R).toFixed(2) + ' ' + fy(G.qOfR(R)).toFixed(2);
  }

  function drawFold() {
    const eff = family === 'oblate' ? q : (1 + mu) / (D * D * D);
    const roots = G.breakupRoots(Math.min(eff, G.Q_BREAK));
    const marks = !roots ? '' : [roots.inner, roots.outer].filter((R) => R >= R0 && R <= R1)
      .map((R) => `<circle cx="${fx(R).toFixed(2)}" cy="${fy(eff).toFixed(2)}" r="1.8"/>`).join('');
    fold.innerHTML =
      `<path class="fold-axis" d="M${M.l} ${M.t} L${M.l} ${H - M.b} L${W - M.r} ${H - M.b}"/>` +
      `<path class="fold-curve" d="${curveD}"/>` +
      `<line class="fold-break" x1="${M.l}" y1="${fy(G.Q_BREAK).toFixed(2)}" x2="${W - M.r}" y2="${fy(G.Q_BREAK).toFixed(2)}"/>` +
      `<line class="fold-q" x1="${M.l}" y1="${fy(eff).toFixed(2)}" x2="${W - M.r}" y2="${fy(eff).toFixed(2)}"/>` +
      `<g class="fold-root">${marks}</g>` +
      `<text class="fold-lab" x="${W - M.r}" y="${(fy(G.Q_BREAK) - 2.2).toFixed(2)}" text-anchor="end">q_break = 8/27</text>` +
      `<text class="fold-lab" x="${fx(1.5).toFixed(2)}" y="${H - 3.5}" text-anchor="middle">R = 3/2</text>` +
      `<text class="fold-lab" x="1.5" y="${M.t + 3}">q</text>` +
      `<text class="fold-lab" x="${W - M.r}" y="${H - 3.5}" text-anchor="end">R</text>`;
  }

  /* ── the colour scale ─────────────────────────────────────────────── */

  /* A coloured field with no key is not a figure. The ramp runs paper -> ink,
     so the largest value carries the most ink — which is the engraving
     convention and the opposite of "bright means bright", hence the label. */
  function drawScale() {
    const { lo, hi } = S.range;
    scale.innerHTML =
      `<span class="sc-k">${mode === 'forcing'
        ? '(g<sub>eff</sub> / g<sub>pole</sub>)<sup>β</sup> — more ink is more forcing'
        : 'g<sub>eff</sub> = ‖∇φ‖ — more ink is stronger gravity'}</span>` +
      `<span class="sc-v">${lo.toFixed(4)}</span><span class="sc-bar"></span>` +
      `<span class="sc-v">${hi.toFixed(4)}</span>`;
  }

  /* ── wiring ───────────────────────────────────────────────────────── */

  const scale = document.createElement('div');
  scale.className = 'scale';
  root.querySelector('.plate-frame').appendChild(scale);

  const h = register(root, () => { S.draw(); drawFold(); drawScale(); readouts(); });
  S.onChange(() => { elev.value = Math.round(S.elevation * 180 / Math.PI); h.dirty(); });
  onResize(canvas, h);
  rebuild();
}
