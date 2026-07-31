/* w05_classifier.js — Figure 4, panel A: the refinement-trend dichotomy.
 *
 * The classifier's whole content is a trend. At any single grid the resolved
 * field and the contaminated one look identical and their C values are just two
 * numbers on a page; only refinement separates them. So the grid is the control.
 *
 * The setup is the paper's own synthetic demonstration, recomputed here rather
 * than replayed: a uniform periodic n x n chart with spacing h = 1/n and cell
 * centres (i + 1/2)h, the resolved mode cos(2*pi*x) cos(2*pi*y), the grid-scale
 * checkerboard (-1)^(i+j) at unit rms, and
 *
 *     A = the 4-neighbour periodic average,   C = rms[(I - A) f].
 *
 * The four values the solver shipped are drawn on top as crosses. They are the
 * only numbers on this figure that were not computed in this browser, and the
 * distance between them and the live traces is printed rather than asserted.
 */

import { register } from '../core/bus.js';
import { control } from '../core/scrub.js';

const SWEEP = [16, 24, 32, 48, 64, 96, 128, 192, 256];
const A_PUB = 0.01, N_PUB = 64;

/* expansion/classifier_synthetic.csv — n, C_smooth, C_checker, C_contaminated.
 * Four rows, transcribed to full shipped precision; the colophon names the file. */
const SHIPPED = [
  [64, 2.4076366639e-3, 2.0000000000e+0, 2.0144396598e-2],
  [80, 1.5413331334e-3, 2.0000000000e+0, 2.0059304769e-2],
  [120, 6.8523262271e-4, 2.0000000000e+0, 2.0011735151e-2],
  [160, 3.8548187964e-4, 2.0000000000e+0, 2.0003714562e-2]
];

/** Build the three fields on an n x n cell-centred periodic chart. */
function fields(n, a) {
  const N2 = n * n, h = 1 / n;
  const smooth = new Float64Array(N2), chi = new Float64Array(N2), contam = new Float64Array(N2);
  for (let i = 0; i < n; i++) {
    const cx = Math.cos(2 * Math.PI * (i + 0.5) * h);
    for (let j = 0; j < n; j++) {
      const k = i * n + j;
      const s = cx * Math.cos(2 * Math.PI * (j + 0.5) * h);
      const c = (i + j) % 2 === 0 ? 1 : -1;
      smooth[k] = s; chi[k] = c; contam[k] = s + a * c;
    }
  }
  return { smooth, chi, contam };
}

/** C(F) = rms[(I - A) F], A the 4-neighbour periodic average. */
function classifier(F, n) {
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const im = ((i - 1 + n) % n) * n, ip = ((i + 1) % n) * n, i0 = i * n;
    for (let j = 0; j < n; j++) {
      const jm = (j - 1 + n) % n, jp = (j + 1) % n;
      const r = F[i0 + j] - 0.25 * (F[im + j] + F[ip + j] + F[i0 + jm] + F[i0 + jp]);
      acc += r * r;
    }
  }
  return Math.sqrt(acc / (n * n));
}

/** Least-squares slope of log C against log h. */
function slope(hs, cs) {
  const n = hs.length;
  const lx = hs.map(Math.log), ly = cs.map(Math.log);
  const mx = lx.reduce((a, b) => a + b) / n, my = ly.reduce((a, b) => a + b) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { num += (lx[i] - mx) * (ly[i] - my); den += (lx[i] - mx) ** 2; }
  return num / den;
}

export default function mount(root) {
  const strip = root.querySelector('.plate-controls');
  const [cvA, cvB] = root.querySelectorAll('canvas');
  const chart = root.querySelector('.chart');
  const read = root.querySelector('.readouts');

  let n = N_PUB, a = A_PUB;
  let trace = null;

  control(strip, {
    label: '<span class="lc">N</span> — chart resolution', min: 16, max: 256, step: 1, value: n,
    published: N_PUB, digits: 0, onInput: (v) => { n = v; h.dirty(); }
  });

  control(strip, {
    label: '<span class="lc">a</span> — checkerboard contamination', min: 0, max: 0.05, step: 0.0005,
    value: a, published: A_PUB, digits: 4,
    onInput: (v) => { a = v; sweep(); h.dirty(); }
  });

  /* ── the sweep ────────────────────────────────────────────────────── */

  function sweep() {
    const smooth = [], checker = [], contam = [];
    for (const m of SWEEP) {
      const f = fields(m, a);
      smooth.push(classifier(f.smooth, m));
      checker.push(classifier(f.chi, m));
      contam.push(classifier(f.contam, m));
    }
    // The same computation at the four grids the solver shipped, so the page
    // can state its own agreement instead of claiming it.
    let worst = 0;
    for (const [m, cs, cc, ct] of SHIPPED) {
      const f = fields(m, A_PUB);
      const mine = [classifier(f.smooth, m), classifier(f.chi, m), classifier(f.contam, m)];
      [cs, cc, ct].forEach((ref, i) => {
        worst = Math.max(worst, Math.abs(mine[i] - ref) / Math.abs(ref));
      });
    }
    const hs = SWEEP.map((m) => 1 / m);
    trace = {
      smooth, checker, contam, worst,
      fitAll: slope(hs, smooth),
      fitPaper: slope(SHIPPED.map(([m]) => 1 / m), SHIPPED.map(([, cs]) => cs)),
      floor: contam[contam.length - 1]
    };
  }

  /* ── heatmaps ─────────────────────────────────────────────────────── */

  function heat(canvas, F, m) {
    canvas.width = m; canvas.height = m;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(m, m);
    let lo = Infinity, hi = -Infinity;
    for (let k = 0; k < F.length; k++) { if (F[k] < lo) lo = F[k]; if (F[k] > hi) hi = F[k]; }
    const span = hi - lo > 1e-12 ? hi - lo : 1;
    const cs = getComputedStyle(document.documentElement);
    const lo3 = hex(cs.getPropertyValue('--ramp-lo').trim());
    const hi3 = hex(cs.getPropertyValue('--ramp-hi').trim());
    for (let i = 0; i < m; i++) {
      for (let j = 0; j < m; j++) {
        const t = (F[i * m + j] - lo) / span, s = 1 - t;
        const o = (j * m + i) * 4;
        img.data[o] = lo3[0] * s + hi3[0] * t;
        img.data[o + 1] = lo3[1] * s + hi3[1] * t;
        img.data[o + 2] = lo3[2] * s + hi3[2] * t;
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }

  function hex(c) {
    const s = c.length === 4 ? c.slice(1).split('').map((x) => x + x).join('') : c.slice(1);
    return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16));
  }

  /* ── the log-log plot ─────────────────────────────────────────────── */

  // The viewBox is sized to roughly the rendered width, so one user unit is one
  // CSS pixel and the stroke widths and type sizes in paper.css mean what they
  // say. A small viewBox stretched to full width magnifies every one of them.
  const CW = 720, CH = 400, M = { l: 62, r: 18, t: 20, b: 46 };
  const X = (m) => M.l + (Math.log(m) - Math.log(16)) / (Math.log(256) - Math.log(16)) * (CW - M.l - M.r);
  const Y = (c) => {
    const t = (Math.log10(Math.max(c, 1e-6)) - (-5)) / (0.75 - (-5));  // headroom over 2.000
    return CH - M.b - t * (CH - M.t - M.b);
  };

  const GLYPH = {
    circle: (x, y) => `<circle cx="${x}" cy="${y}" r="3.4" fill="none"/>`,
    disc: (x, y) => `<circle cx="${x}" cy="${y}" r="3.2"/>`,
    diamond: (x, y) => `<path d="M${x} ${y - 4}L${x + 4} ${y}L${x} ${y + 4}L${x - 4} ${y}Z"/>`,
    cross: (x, y) => `<path d="M${x - 5} ${y - 5}L${x + 5} ${y + 5}M${x - 5} ${y + 5}L${x + 5} ${y - 5}" fill="none"/>`
  };

  const line = (vals, cls, glyph) => {
    const d = SWEEP.map((m, i) => (i ? 'L' : 'M') + X(m).toFixed(2) + ' ' + Y(vals[i]).toFixed(2)).join('');
    return `<path class="tr ${cls}" d="${d}"/>` +
      `<g class="tr-m ${cls}">${SWEEP.map((m, i) => GLYPH[glyph](X(m).toFixed(2), Y(vals[i]).toFixed(2))).join('')}</g>`;
  };

  function drawChart() {
    const t = trace;
    let ticks = '';
    for (let e = -5; e <= 0; e++) {
      const y = Y(Math.pow(10, e)).toFixed(2);
      ticks += `<line class="ax-grid" x1="${M.l}" y1="${y}" x2="${CW - M.r}" y2="${y}"/>` +
        `<text class="ax-lab" x="${M.l - 8}" y="${+y + 4}" text-anchor="end">10${sup(e)}</text>`;
    }
    for (const m of [16, 32, 64, 128, 256]) {
      const x = X(m).toFixed(2);
      ticks += `<line class="ax-tick" x1="${x}" y1="${CH - M.b}" x2="${x}" y2="${CH - M.b + 5}"/>` +
        `<text class="ax-lab" x="${x}" y="${CH - M.b + 18}" text-anchor="middle">${m}</text>`;
    }

    // A slope -2 guide, anchored under the resolved trace.
    const g0 = t.smooth[0] * 0.34, g1 = g0 * Math.pow(16 / 256, 2);
    const guide = `<path class="guide" d="M${X(16).toFixed(2)} ${Y(g0).toFixed(2)}L${X(256).toFixed(2)} ${Y(g1).toFixed(2)}"/>` +
      `<text class="ax-lab guide-lab" x="${X(70).toFixed(2)}" y="${(Y(g0 * Math.pow(16 / 70, 2)) + 16).toFixed(2)}">slope −2</text>`;

    const shipped = `<g class="tr-m shipped">` + SHIPPED.map(([m, cs, cc, ct]) =>
      GLYPH.cross(X(m).toFixed(2), Y(cs).toFixed(2)) +
      GLYPH.cross(X(m).toFixed(2), Y(cc).toFixed(2)) +
      GLYPH.cross(X(m).toFixed(2), Y(ct).toFixed(2))).join('') + '</g>';

    chart.setAttribute('viewBox', `0 0 ${CW} ${CH}`);
    chart.innerHTML = ticks + guide +
      line(t.checker, 'c-checker', 'diamond') +
      line(t.contam, 'c-contam', 'disc') +
      line(t.smooth, 'c-smooth', 'circle') +
      shipped +
      `<line class="ax-tick" x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${CH - M.b}"/>` +
      `<line class="ax-tick" x1="${M.l}" y1="${CH - M.b}" x2="${CW - M.r}" y2="${CH - M.b}"/>` +
      `<text class="ax-title" x="${(CW / 2).toFixed(0)}" y="${CH - 6}" text-anchor="middle">N</text>` +
      `<text class="ax-title" x="8" y="${M.t + 10}">𝒞</text>`;
  }

  const sup = (e) => String(e).replace('-', '⁻').replace(/\d/g, (d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[+d]);

  /* ── readouts ─────────────────────────────────────────────────────── */

  read.innerHTML = [
    ['𝒞 at the shown N — resolved', 'cs'],
    ['𝒞 at the shown N — contaminated', 'cc'],
    ['𝒞 — pure checkerboard, every N', 'ck'],
    ['fitted slope of the resolved trace', 'fit'],
    ['contaminated floor at N = 256', 'fl'],
    ['agreement with the four shipped rows', 'agr']
  ].map(([l, k]) => `<div class="ro"><span class="ro-k">${l}</span>` +
    `<span class="ro-v calc" data-k="${k}">—</span></div>`).join('');
  const cell = (k) => read.querySelector(`[data-k="${k}"]`);

  /* ── paint ────────────────────────────────────────────────────────── */

  function draw() {
    if (!trace) sweep();
    const f = fields(n, a);
    heat(cvA, f.smooth, n);
    heat(cvB, f.contam, n);
    drawChart();
    cell('cs').textContent = '≈ ' + classifier(f.smooth, n).toExponential(4);
    cell('cc').textContent = '≈ ' + classifier(f.contam, n).toExponential(4);
    cell('ck').textContent = classifier(f.chi, n).toFixed(12);
    cell('fit').textContent = '≈ ' + trace.fitAll.toFixed(4) +
      `  (over the paper's four grids, ${trace.fitPaper.toFixed(4)})`;
    cell('fl').textContent = '≈ ' + trace.floor.toFixed(6) + `  — the exact asymptote is 2a = ${(2 * a).toFixed(4)}`;
    cell('agr').textContent = trace.worst === 0
      ? 'exact to the last bit'
      : `max relative difference ${trace.worst.toExponential(2)}`;
  }

  const h = register(root, draw);
  sweep();
}
