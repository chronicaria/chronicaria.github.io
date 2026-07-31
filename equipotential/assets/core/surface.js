/* surface.js — the figure, drawn as a plotted mesh.
 *
 * A parametric quad mesh on the level set, painted back to front on a 2-D
 * canvas. Painter's algorithm is exact here rather than an approximation:
 * an equipotential figure of a body in hydrostatic equilibrium is star-shaped
 * about the primary, so a back-to-front centroid-depth order never produces an
 * ambiguous overlap.
 *
 * Flat per-quad fill, not a smooth gradient. canvas2D has no UV mapping, and
 * per-triangle clip/transform/drawImage would cost 50-150 ms a frame; faceting
 * is also the right visual vocabulary — flat quads read as a plotted mesh.
 * Form comes from the graticule; magnitude from the ramp; and the ramp is
 * backed by iso-contour hairlines so the field is never carried by hue alone.
 */

import { fit, palette, ramp } from './bus.js';

const TAU = Math.PI * 2;
const LEVELS = 8;

export function createSurface(canvas, opts) {
  const coarse = matchMedia('(pointer: coarse)').matches;
  // ponytail: fixed mesh density. ~3200 quads is ~4 ms of fill+stroke, inside
  // the 30 fps mesh budget. Raise NLON/NLAT if a display ever justifies it.
  const NLON = coarse ? 56 : 80;
  const NLAT = coarse ? 28 : 40;
  const NV = NLON * (NLAT + 1);

  const px = new Float64Array(NV), py = new Float64Array(NV), pz = new Float64Array(NV);
  const sc = new Float64Array(NV);                 // the coloured scalar
  const sx = new Float64Array(NV), sy = new Float64Array(NV);
  const NQ = NLON * NLAT;
  const depth = new Float64Array(NQ);
  const order = new Int32Array(NQ);
  const grad = [0, 0, 0];

  let fig = null, mode = 'geff', beta = 0.08;
  let az = opts && opts.azimuth != null ? opts.azimuth : -0.9;
  let el = opts && opts.elevation != null ? opts.elevation : 0.42;
  let lo = 0, hi = 1, maxR = 1, onChange = () => {};

  /* ── mesh ──────────────────────────────────────────────────────────── */

  function build() {
    lo = Infinity; hi = -Infinity; maxR = 0;
    for (let j = 0; j <= NLAT; j++) {
      const th = Math.PI * j / NLAT;
      const st = Math.sin(th), ct = Math.cos(th);
      for (let i = 0; i < NLON; i++) {
        const ph = TAU * i / NLON;
        const ux = st * Math.cos(ph), uy = st * Math.sin(ph), uz = ct;
        const t = fig.radius(ux, uy, uz);
        const k = j * NLON + i;
        const x = t * ux, y = t * uy, z = t * uz;
        px[k] = x; py[k] = y; pz[k] = z;
        if (t > maxR) maxR = t;
        fig.grad(x, y, z, grad);
        const g = Math.hypot(grad[0], grad[1], grad[2]);
        const v = mode === 'forcing' ? Math.pow(g / fig.gPole, beta) : g;
        sc[k] = v;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
  }

  /* ── paint ─────────────────────────────────────────────────────────── */

  function draw() {
    if (!fig) return;
    const { ctx, w, h } = fit(canvas);
    const p = palette();
    ctx.fillStyle = p.panel;
    ctx.fillRect(0, 0, w, h);

    const ce = Math.cos(el), se = Math.sin(el), ca = Math.cos(az), sa = Math.sin(az);
    const dx = ce * ca, dy = ce * sa, dz = se;          // toward the camera
    const rx = -sa, ry = ca;                             // screen right
    const ux = -se * ca, uy = -se * sa, uz = ce;         // screen up
    const s = 0.44 * Math.min(w, h) / maxR;
    const cx = w / 2, cy = h / 2;

    for (let k = 0; k < NV; k++) {
      sx[k] = cx + s * (px[k] * rx + py[k] * ry);
      sy[k] = cy - s * (px[k] * ux + py[k] * uy + pz[k] * uz);
    }

    for (let j = 0; j < NLAT; j++) {
      for (let i = 0; i < NLON; i++) {
        const q = j * NLON + i;
        const a = j * NLON + i, b = j * NLON + (i + 1) % NLON;
        const c = (j + 1) * NLON + (i + 1) % NLON, d = (j + 1) * NLON + i;
        depth[q] = (px[a] + px[b] + px[c] + px[d]) * dx
                 + (py[a] + py[b] + py[c] + py[d]) * dy
                 + (pz[a] + pz[b] + pz[c] + pz[d]) * dz;
        order[q] = q;
      }
    }
    // ponytail: a per-frame sort of ~3200 indices is well under 1 ms. The
    // analytic index permutation from camera azimuth is the upgrade if a
    // profile ever says this matters.
    const ord = order.sort((m, n) => depth[m] - depth[n]);

    const span = hi - lo > 1e-12 ? hi - lo : 1;
    ctx.lineJoin = 'round';
    ctx.lineWidth = 1;
    for (const q of ord) {
      const j = (q / NLON) | 0, i = q - j * NLON;
      const a = j * NLON + i, b = j * NLON + (i + 1) % NLON;
      const c = (j + 1) * NLON + (i + 1) % NLON, d = (j + 1) * NLON + i;
      const col = ramp(((sc[a] + sc[b] + sc[c] + sc[d]) / 4 - lo) / span);
      ctx.beginPath();
      ctx.moveTo(sx[a], sy[a]); ctx.lineTo(sx[b], sy[b]);
      ctx.lineTo(sx[c], sy[c]); ctx.lineTo(sx[d], sy[d]);
      ctx.closePath();
      ctx.fillStyle = col; ctx.strokeStyle = col;   // stroke kills the AA seams
      ctx.fill(); ctx.stroke();
    }

    graticule(ctx, ord, p);
    isoContours(ctx, ord, p, span);
  }

  /** Every 8th meridian and 5th parallel, so the form reads without shading. */
  function graticule(ctx, ord, p) {
    ctx.strokeStyle = p.rule;
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    for (const q of ord) {
      const j = (q / NLON) | 0, i = q - j * NLON;
      const a = j * NLON + i, d = (j + 1) * NLON + i, b = j * NLON + (i + 1) % NLON;
      if (i % 8 === 0) { ctx.moveTo(sx[a], sy[a]); ctx.lineTo(sx[d], sy[d]); }
      if (j % 5 === 0) { ctx.moveTo(sx[a], sy[a]); ctx.lineTo(sx[b], sy[b]); }
    }
    ctx.stroke();
  }

  /**
   * Eight iso-contours of the coloured field, by marching squares on each quad.
   * This is the redundant non-hue channel the site's colour doctrine requires,
   * and it is the broadsheet's own device for a scalar field.
   */
  function isoContours(ctx, ord, p, span) {
    if (span <= 1e-9) return;
    ctx.strokeStyle = p.hatch;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    const xs = [0, 0, 0, 0], ys = [0, 0, 0, 0];
    for (const q of ord) {
      const j = (q / NLON) | 0, i = q - j * NLON;
      const v = [j * NLON + i, j * NLON + (i + 1) % NLON,
                 (j + 1) * NLON + (i + 1) % NLON, (j + 1) * NLON + i];
      let mn = Infinity, mx = -Infinity;
      for (const k of v) { if (sc[k] < mn) mn = sc[k]; if (sc[k] > mx) mx = sc[k]; }
      for (let L = 1; L <= LEVELS; L++) {
        const lev = lo + span * L / (LEVELS + 1);
        if (lev <= mn || lev >= mx) continue;
        let n = 0;
        for (let e = 0; e < 4 && n < 4; e++) {
          const k0 = v[e], k1 = v[(e + 1) & 3];
          const s0 = sc[k0], s1 = sc[k1];
          if ((s0 < lev) === (s1 < lev)) continue;
          const f = (lev - s0) / (s1 - s0);
          xs[n] = sx[k0] + f * (sx[k1] - sx[k0]);
          ys[n] = sy[k0] + f * (sy[k1] - sy[k0]);
          n++;
        }
        if (n >= 2) { ctx.moveTo(xs[0], ys[0]); ctx.lineTo(xs[1], ys[1]); }
        if (n === 4) { ctx.moveTo(xs[2], ys[2]); ctx.lineTo(xs[3], ys[3]); }
      }
    }
    ctx.stroke();
  }

  /* ── orbit ─────────────────────────────────────────────────────────── */

  const active = new Map();
  let lastX = 0, lastY = 0;

  canvas.addEventListener('pointerdown', (e) => {
    active.set(e.pointerId, true);
    canvas.setPointerCapture(e.pointerId);
    lastX = e.clientX; lastY = e.clientY;
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!active.has(e.pointerId)) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    // One finger on touch rotates azimuth only — the one gesture that cannot be
    // confused with a page scroll, and the axis that matters for a figure of
    // revolution. Two fingers, or a mouse, orbit freely.
    const full = e.pointerType !== 'touch' || active.size === 2;
    if (full && e.pointerType === 'touch') e.preventDefault();
    az -= dx * 0.008;
    if (full) el = Math.max(-1.45, Math.min(1.45, el + dy * 0.008));
    onChange();
  });
  const release = (e) => {
    active.delete(e.pointerId);
    if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);

  return {
    setFigure(f) { fig = f; build(); },
    setMode(m) { mode = m; if (fig) build(); },
    setBeta(b) { beta = b; if (fig && mode === 'forcing') build(); },
    setView(a, e) { az = a; el = e; },
    onChange(fn) { onChange = fn; },
    get azimuth() { return az; },
    set azimuth(v) { az = v; },
    get elevation() { return el; },
    set elevation(v) { el = v; },
    get range() { return { lo, hi }; },
    draw
  };
}
