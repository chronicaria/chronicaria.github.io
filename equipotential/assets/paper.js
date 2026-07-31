/* paper.js — the page's only module entry.
 *
 * Boots the theme toggle, the inline scrubbable numbers, the keyboard map and
 * the widget registry. Widgets are imported lazily, one per plate, so a reader
 * who never scrolls to Figure 4 never fetches it.
 *
 * This page deliberately does not load the site's site.js or ui.js: site.js
 * binds bare 1-5 to page navigation, which would collide with the section keys
 * below. The year stamp and the theme toggle are reimplemented here instead.
 */

import { stillAll, resume } from './core/bus.js';
import { scrub } from './core/scrub.js';

const WIDGETS = {
  w01_cutpoint: () => import('./fig/w01_cutpoint.js'),
  w03_family: () => import('./fig/w03_family.js'),
  w05_classifier: () => import('./fig/w05_classifier.js')
};

/* ── widgets ──────────────────────────────────────────────────────────── */

for (const el of document.querySelectorAll('[data-widget]')) {
  const load = WIDGETS[el.dataset.widget];
  if (!load) continue;
  load()
    .then((m) => m.default(el))
    .catch((err) => {
      // A widget that fails to boot leaves its build-time still in place
      // rather than an empty bordered box.
      console.error(el.dataset.widget, err);
      el.querySelectorAll('canvas').forEach((c) => { c.style.display = 'none'; });
      el.querySelectorAll('.still').forEach((s) => { s.style.display = 'block'; });
    });
}

/* ── inline scrubbable numbers ────────────────────────────────────────── */

for (const span of document.querySelectorAll('.scrub[data-var]')) {
  const targets = document.querySelectorAll(`[data-echo="${span.dataset.var}"]`);
  scrub(span, (v) => {
    for (const t of targets) t.textContent = v.toFixed(+span.dataset.digits || 3);
  });
}

/* ── theme ────────────────────────────────────────────────────────────── */

const KEY = 'equipotential-theme';
const btn = document.querySelector('.theme-toggle');

function paintToggle() {
  const dark = document.documentElement.dataset.theme === 'dark';
  btn.textContent = dark ? '◐ morning' : '◐ evening';
  btn.setAttribute('aria-label', dark ? 'Switch to the morning edition' : 'Switch to the evening edition');
}

if (btn) {
  btn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
    paintToggle();
  });
  paintToggle();
}

const yr = document.querySelector('[data-year]');
if (yr) yr.textContent = String(new Date().getFullYear());

/* ── keyboard ─────────────────────────────────────────────────────────── */

addEventListener('keydown', (e) => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === '?') {
    const d = document.getElementById('keys');
    if (d) { d.open = !d.open; d.scrollIntoView({ block: 'center' }); }
    return;
  }
  if (e.key === 's' || e.key === 'S') { stillAll(); return; }
  if (e.key === 'r' || e.key === 'R') { resume(); }
});
