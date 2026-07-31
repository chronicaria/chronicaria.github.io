/* scrub.js — the two control idioms this page uses, and nothing else.
 *
 *   control(host, spec)  a labelled range in a plate's control strip, carrying
 *                        a prussian tick at the value the paper published and a
 *                        per-control reset back to it.
 *   tabs(host, spec)     the site's segmented mode tabs.
 *   scrub(span)          a draggable inline number in running prose, always
 *                        paired with a real <input type=range> that appears on
 *                        focus. A drag-only control is inaccessible.
 */

const fmt = (v, d) => v.toFixed(d == null ? 3 : d);

/**
 * @param {Element} host  the .plate-controls strip
 * @param {object} spec   {label, min, max, step, value, published, digits,
 *                         unit, format, onInput}
 */
export function control(host, spec) {
  const wrap = document.createElement('div');
  wrap.className = 'ctl';
  const id = 'c' + Math.random().toString(36).slice(2, 8);
  const show = spec.format || ((v) => fmt(v, spec.digits));

  wrap.innerHTML =
    `<label for="${id}">${spec.label}</label>` +
    `<div class="ctl-row"><input id="${id}" type="range" min="${spec.min}" max="${spec.max}" ` +
      `step="${spec.step}" value="${spec.value}"></div>` +
    `<div class="ctl-foot"><span class="ctl-val" aria-hidden="true"></span>` +
      `<button type="button" class="reset" title="restore the published value">↺</button></div>`;
  host.appendChild(wrap);

  const input = wrap.querySelector('input');
  const out = wrap.querySelector('.ctl-val');
  const row = wrap.querySelector('.ctl-row');

  if (spec.published != null) {
    const mark = document.createElement('span');
    mark.className = 'mark';
    const f = (spec.published - spec.min) / (spec.max - spec.min);
    // The thumb is 14px wide, so the usable track is inset by half of it at
    // each end; without that the tick drifts from the value it marks.
    mark.style.left = `calc(7px + ${f} * (100% - 14px))`;
    row.appendChild(mark);
  } else {
    wrap.querySelector('.reset').hidden = true;
  }

  const api = {
    get value() { return +input.value; },
    set value(v) { input.value = v; paint(); },
    set hidden(v) { wrap.hidden = v; },
    input, wrap
  };

  function paint() {
    out.textContent = show(+input.value) + (spec.unit || '');
    input.setAttribute('aria-valuetext', out.textContent);
  }

  input.addEventListener('input', () => { paint(); spec.onInput(+input.value); });
  wrap.querySelector('.reset').addEventListener('click', () => {
    input.value = spec.published; paint(); spec.onInput(+input.value);
  });
  paint();
  return api;
}

/** Segmented mode tabs; `options` is [[value, label], …]. */
export function tabs(host, spec) {
  const wrap = document.createElement('div');
  wrap.className = 'ctl ctl--tabs';
  // Labels carry markup (Greek is wrapped so uppercasing cannot corrupt it),
  // and markup inside an attribute value closes the attribute early.
  const plain = spec.label.replace(/<[^>]*>/g, '');
  wrap.innerHTML = `<span class="label">${spec.label}</span>` +
    `<div class="tab-row" role="group" aria-label="${plain}"></div>`;
  host.appendChild(wrap);
  const row = wrap.querySelector('.tab-row');
  let cur = spec.value;

  for (const [v, label] of spec.options) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'tab';
    b.textContent = label;
    b.dataset.v = v;
    b.setAttribute('aria-pressed', String(v === cur));
    b.addEventListener('click', () => {
      cur = v;
      for (const o of row.children) o.setAttribute('aria-pressed', String(o.dataset.v === String(v)));
      spec.onInput(v);
    });
    row.appendChild(b);
  }
  return {
    get value() { return cur; },
    /** Set without firing onInput, for when another control moved this one. */
    set value(v) {
      cur = v;
      for (const o of row.children) o.setAttribute('aria-pressed', String(o.dataset.v === String(v)));
    },
    set hidden(v) { wrap.hidden = v; },
    wrap
  };
}

/**
 * Make an inline `<span class="scrub">` draggable. The span carries
 * data-min/max/step/digits and a data-label; the paired range lives beside it,
 * hidden until it or the span takes focus.
 */
export function scrub(span, onInput) {
  const min = +span.dataset.min, max = +span.dataset.max;
  const step = +span.dataset.step || 0.001;
  const digits = span.dataset.digits == null ? 3 : +span.dataset.digits;
  const prefix = span.dataset.prefix || '';
  let value = +span.dataset.value;

  const range = document.createElement('input');
  range.type = 'range';
  range.className = 'scrub-range';
  range.min = min; range.max = max; range.step = step; range.value = value;
  range.setAttribute('aria-label', span.dataset.label || 'value');
  span.after(range);

  span.tabIndex = 0;
  span.setAttribute('role', 'button');
  span.setAttribute('aria-label', `${span.dataset.label || 'value'} — drag, or use the slider that appears on focus`);

  const paint = () => {
    span.textContent = prefix + value.toFixed(digits);
    range.value = value;
    onInput(value);
  };

  const setv = (v) => {
    value = Math.min(max, Math.max(min, Math.round(v / step) * step));
    paint();
  };

  span.addEventListener('pointerdown', (e) => {
    span.setPointerCapture(e.pointerId);
    span.dataset.dragging = '1';
    e.preventDefault();
  });
  span.addEventListener('pointermove', (e) => {
    if (!span.dataset.dragging) return;
    setv(value + e.movementX * (max - min) / 240);
  });
  const end = (e) => {
    delete span.dataset.dragging;
    if (span.hasPointerCapture(e.pointerId)) span.releasePointerCapture(e.pointerId);
  };
  span.addEventListener('pointerup', end);
  span.addEventListener('pointercancel', end);
  span.addEventListener('keydown', (e) => {
    const d = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key];
    if (!d) return;
    e.preventDefault();
    setv(value + d * step * (e.shiftKey ? 10 : 1));
  });
  range.addEventListener('input', () => setv(+range.value));

  paint();
  return { get value() { return value; }, set value(v) { setv(v); } };
}
