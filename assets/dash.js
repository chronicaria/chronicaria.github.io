// Stand-in for the Dashboard type's `dash` API: renders page/index.html locally (dev.html) and on the public site (site/build.py).
// Loads each dataset from the folder in ?data= (default ../mock): <id>.csv, or <id>.json for logos.
// Cells arrive as text, as the type delivers a CSV. Not uploaded to the store.
(() => {
  const q = new URLSearchParams(location.search);
  const base = (q.get('data') || window.NB_DATA || '../mock').replace(/\/$/, '');  // the public site sets NB_DATA = 'data'
  const FILES = { logos: 'logos.json' };
  const sets = {};      // id -> {status, data, columns, message, refreshing, meta}
  const calcs = {};     // id -> {inputs, fn}
  const subs = [];
  let params = {};
  let queued = false;

  const parseCSV = (text) => {
    const rows = []; let row = [], cell = '', i = 0, quoted = false;
    for (; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') quoted = false;
        else cell += c;
      } else if (c === '"') quoted = true;
      else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += c;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    const cols = rows.shift() || [];
    return { columns: cols, data: rows.filter((r) => r.length > 1 || r[0] !== '').map((r) => Object.fromEntries(cols.map((c, k) => [c, r[k] ?? ''])) ) };
  };

  const notify = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; subs.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }); });
  };

  const load = (id) => {
    sets[id] = { status: 'loading', data: [], columns: [], message: '', refreshing: false, meta: [] };
    const file = FILES[id] || `${id}.csv`;
    fetch(`${base}/${file}`).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${file}`);
      return r.text();
    }).then((text) => {
      if (file.endsWith('.json')) {
        const data = JSON.parse(text);
        sets[id] = { status: 'ok', data, columns: data.length ? Object.keys(data[0]) : [], message: '', refreshing: false, meta: [] };
      } else {
        const { columns, data } = parseCSV(text);
        sets[id] = { status: 'ok', data, columns, message: '', refreshing: false, meta: [] };
      }
      notify();
    }).catch((e) => { sets[id] = { status: /^404 /.test(e.message) ? 'missing' : 'error', data: [], columns: [], message: String(e), refreshing: false, meta: [] }; notify(); });
  };

  const data = (id) => {
    if (calcs[id]) {
      const c = calcs[id];
      const ins = c.inputs.map((i) => data(i));
      const bad = ins.find((d) => d.status !== 'ok');
      if (bad) return { status: bad.status, data: [], columns: [], message: bad.message, refreshing: false, meta: [] };
      try {
        const out = c.fn(...ins.map((d) => d.data));
        return { status: 'ok', data: out, columns: Array.isArray(out) && out.length ? Object.keys(out[0]) : [], message: '', refreshing: false, meta: [] };
      } catch (e) { console.error('calc', id, e); return { status: 'error', data: [], columns: [], message: String(e), refreshing: false, meta: [] }; }
    }
    if (!sets[id]) load(id);
    const s = sets[id];
    return { ...s, rows: s.data, value: s.data };
  };

  window.dash = {
    data,
    onData(fn) { subs.push(fn); try { fn(); } catch (e) { console.error(e); } },
    calc(id, spec) { calcs[id] = spec; },
    loader() {},
    colors: [1, 2, 3, 4, 5, 6, 7, 8].map((k) => `var(--cds-chart-categorical-${k})`),
    params: () => ({ ...params }),
    setParams(p) { params = { ...params, ...p }; notify(); },
    resetParams() { params = {}; notify(); },
    setLink(name) { history.replaceState(null, '', `${location.pathname}${location.search}#${name}`); },
    refresh(id) { load(id); notify(); },
  };

  // Width changes redraw, as the type does.
  let lastW = 0;
  const ro = new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (w !== lastW) { lastW = w; notify(); }
  });
  document.addEventListener('DOMContentLoaded', () => { const root = document.getElementById('dash-root'); if (root) ro.observe(root); });
})();
