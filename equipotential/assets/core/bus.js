/* bus.js — one scheduler, one palette cache, for every widget on the page.
 *
 * Twelve widgets each running their own requestAnimationFrame loop would burn
 * 720 early-returning callbacks a second. Instead every widget registers
 * {el, draw, still} and marks itself dirty; the single loop below iterates only
 * the widgets that are both visible and dirty, and cancels itself entirely when
 * nothing is dirty.
 *
 * It also owns the three things that must be handled once rather than twelve
 * times: theme changes (canvas cannot inherit a CSS variable), reduced motion
 * (the site's global prefers-reduced-motion rule kills CSS animation and
 * cannot touch a canvas loop), and printing.
 */

const widgets = [];
let frame = 0;

/* ── palette ──────────────────────────────────────────────────────────── */

const TOKENS = [
  '--paper', '--ink', '--prussian', '--royal', '--gray', '--rule',
  '--rule-strong', '--accent-soft', '--panel', '--ghost', '--lit',
  '--hatch', '--tick', '--ramp-lo', '--ramp-hi'
];

let cache = null;

/** Cached computed values of the design tokens. Cleared on a theme change. */
export function palette() {
  if (cache) return cache;
  const cs = getComputedStyle(document.documentElement);
  cache = {};
  for (const t of TOKENS) cache[t.slice(2)] = cs.getPropertyValue(t).trim();
  return cache;
}

/** Linear interpolation along the monochrome magnitude ramp, t in [0,1]. */
export function ramp(t) {
  const p = palette();
  if (!p._lo) { p._lo = rgb(p['ramp-lo']); p._hi = rgb(p['ramp-hi']); }
  const u = t < 0 ? 0 : t > 1 ? 1 : t, s = 1 - u;
  return `rgb(${Math.round(p._lo[0] * s + p._hi[0] * u)},` +
             `${Math.round(p._lo[1] * s + p._hi[1] * u)},` +
             `${Math.round(p._lo[2] * s + p._hi[2] * u)})`;
}

function rgb(css) {
  if (css.startsWith('#')) {
    const h = css.length === 4
      ? css.slice(1).split('').map((c) => c + c).join('')
      : css.slice(1);
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  return (css.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
}

/* ── motion state ─────────────────────────────────────────────────────── */

const mq = matchMedia('(prefers-reduced-motion: reduce)');
export let reduced = mq.matches;

mq.addEventListener('change', (e) => {
  reduced = e.matches;
  if (reduced) stillAll(); else resume();
});

/* ── registration ─────────────────────────────────────────────────────── */

const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    const w = widgets.find((x) => x.el === e.target);
    if (!w) continue;
    w.visible = e.isIntersecting;
    if (w.visible && w.isDirty) schedule();
  }
}, { rootMargin: '100px' });

/**
 * Register a widget. `draw(dt)` paints one frame; `still()` paints the single
 * representative frame used for print, reduced motion and no-JS recovery — it
 * defaults to one call of draw().
 *
 * Returns a handle whose .dirty() asks for a repaint.
 */
export function register(el, draw, still) {
  const w = {
    el, draw, still: still || (() => draw(0)),
    visible: false, isDirty: true, animating: false
  };
  widgets.push(w);
  io.observe(el);
  const h = {
    dirty() { w.isDirty = true; if (w.visible) schedule(); return h; },
    animate(on) { w.animating = !!on && !reduced; if (w.animating) h.dirty(); return h; },
    get animating() { return w.animating; },
    still() { w.animating = false; w.still(); return h; }
  };
  w.handle = h;
  return h;
}

/* ── the one loop ─────────────────────────────────────────────────────── */

let last = 0;

function schedule() {
  if (frame || document.hidden) return;
  frame = requestAnimationFrame(tick);
}

function tick(now) {
  frame = 0;
  const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
  last = now;
  let more = false;
  for (const w of widgets) {
    if (!w.visible) continue;
    if (w.isDirty || w.animating) {
      w.isDirty = false;
      try { w.draw(dt); } catch (err) { console.error(err); w.animating = false; }
    }
    if (w.animating || w.isDirty) more = true;
  }
  if (more) schedule(); else last = 0;
}

/* ── theme, print, visibility ─────────────────────────────────────────── */

new MutationObserver(() => {
  cache = null;
  for (const w of widgets) w.isDirty = true;
  schedule();
}).observe(document.documentElement, { attributeFilter: ['data-theme'] });

document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });

/** Paint every widget's representative frame and stop animating. */
export function stillAll() {
  for (const w of widgets) {
    w.animating = false;
    try { w.still(); } catch (err) { console.error(err); }
  }
}

/** Resume whatever was animating before reduced motion or a print. */
export function resume() {
  for (const w of widgets) w.isDirty = true;
  schedule();
}

// Print what the reader explored, not what the paper published: every widget
// renders its CURRENT state, so the q they dragged to is the q on the paper.
addEventListener('beforeprint', stillAll);
addEventListener('afterprint', resume);

/* ── a page-level channel, for the opt-in cross-figure link ───────────── */

const subs = new Map();
export function on(k, fn) {
  if (!subs.has(k)) subs.set(k, []);
  subs.get(k).push(fn);
}
export function emit(k, v) {
  for (const fn of subs.get(k) || []) fn(v);
}

/* ── canvas sizing, read once per resize and never inside draw() ──────── */

/**
 * Size a canvas to its CSS box at the current devicePixelRatio and return the
 * 2-D context with the transform already applied. getBoundingClientRect is a
 * layout read, so it happens here — in a debounced ResizeObserver — and never
 * inside a draw call.
 */
export function fit(canvas, opts) {
  const r = canvas.getBoundingClientRect();
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr; canvas.height = h * dpr;
  }
  const ctx = canvas.getContext('2d', opts || { alpha: false });
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

/** Repaint `handle` on resize, debounced to one frame. */
export function onResize(el, handle) {
  let t = 0;
  new ResizeObserver(() => {
    clearTimeout(t);
    t = setTimeout(() => handle.dirty(), 80);
  }).observe(el);
}
