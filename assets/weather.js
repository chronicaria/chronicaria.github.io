/* Temperature page — hour-by-hour county map.
 * Loads the county geometry once (assets/weather/county-temp.svg, id="c<FIPS>"
 * per county), then recolours those paths from data/weather-hourly.json as the
 * slider moves. Two colour modes:
 *   - "pct"  percentile within the selected hour (de-skews Alaska's extremes)
 *   - "abs"  absolute °F on a fixed scale shared across all hours
 */
(() => {
  const RAMP = [
    "#244079", "#3358a2", "#4170cd", "#678cd7", "#8da9e2", "#b4c7ec", "#dee8fb", "#eef3fd",
    "#fdeeee", "#fbdedd", "#f1b4b2", "#ed8783", "#e55651", "#d02923", "#b00600", "#850400",
  ];
  const NO_DATA = "#d9d9d9";
  const N = RAMP.length;
  const BUST = new Date().toISOString().slice(0, 10);

  const $ = (s) => document.querySelector(s);
  const box = $("[data-temp-map]");
  if (!box) return;

  let HOURS = [], NAMES = {}, paths = [];
  let idx = 0, mode = localStorage.getItem("tempMode") || "pct";
  let gMin = Infinity, gMax = -Infinity;

  const fmtTime = (iso) =>
    new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric" });

  Promise.all([
    fetch(`assets/weather/county-temp.svg?v=${BUST}`).then((r) => (r.ok ? r.text() : Promise.reject())),
    fetch(`data/weather-hourly.json?v=${Date.now()}`).then((r) => (r.ok ? r.json() : Promise.reject())),
  ]).then(([svgText, data]) => {
    box.innerHTML = svgText;
    const svg = box.querySelector("svg");
    if (!svg) throw new Error("no svg");
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    // the baked SVG ships its own legend/annotations + a white backdrop — drop
    // them so the live legend and the page theme show through.
    svg.querySelectorAll("text, rect").forEach((n) => n.remove());
    paths = [...svg.querySelectorAll("path[id]")].filter((p) => /^c\d{5}$/.test(p.id));

    HOURS = (data.hours || []).filter((h) => h && h.temps);
    NAMES = data.names || {};
    if (!HOURS.length) throw new Error("no hours");
    for (const h of HOURS) { gMin = Math.min(gMin, h.min_f); gMax = Math.max(gMax, h.max_f); }
    idx = HOURS.length - 1;
    wireControls();
    render();
  }).catch(() => {
    box.innerHTML =
      '<img src="assets/weather/county-temp.svg" alt="County temperature map" ' +
      'style="display:block;width:100%;height:auto;background:#fff;">';
    const c = $("[data-temp-controls]");
    if (c) c.hidden = true;
  });

  function wireControls() {
    const slider = $("[data-temp-slider]");
    if (slider) {
      slider.min = "0";
      slider.max = String(HOURS.length - 1);
      slider.value = String(idx);
      slider.addEventListener("input", () => { idx = +slider.value; render(); });
    }
    document.querySelectorAll("[data-temp-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        mode = btn.dataset.tempMode;
        localStorage.setItem("tempMode", mode);
        render();
      });
    });
    const ctrls = $("[data-temp-controls]");
    if (ctrls) ctrls.hidden = false;
  }

  // rank of v among sorted s (count of values strictly below) → [0, s.length]
  function rankBelow(s, v) {
    let lo = 0, hi = s.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (s[m] < v) lo = m + 1; else hi = m; }
    return lo;
  }

  function bucketFor(temp, hour) {
    if (temp == null || Number.isNaN(temp)) return -1;
    let b;
    if (mode === "pct") {
      b = Math.floor((rankBelow(hour._sorted, temp) / hour._sorted.length) * N);
    } else {
      b = Math.floor(((temp - gMin) / (gMax - gMin || 1)) * N);
    }
    return Math.max(0, Math.min(N - 1, b));
  }

  function render() {
    const hour = HOURS[idx];
    if (!hour) return;
    if (!hour._sorted) hour._sorted = Object.values(hour.temps).slice().sort((a, b) => a - b);
    for (const p of paths) {
      const t = hour.temps[p.id.slice(1)];
      const b = bucketFor(t, hour);
      p.style.fill = b < 0 ? NO_DATA : RAMP[b];
    }
    updateStats(hour);
    const lbl = $("[data-temp-when]");
    if (lbl) lbl.textContent = fmtTime(hour.valid_utc);
    const rel = $("[data-temp-rel]");
    if (rel) {
      const back = HOURS.length - 1 - idx;
      rel.textContent = back === 0 ? "latest" : `${back}h earlier`;
    }
    drawLegend(hour);
    document.querySelectorAll("[data-temp-mode]").forEach((b) =>
      b.classList.toggle("active", b.dataset.tempMode === mode));
  }

  function updateStats(hour) {
    let hi = null, lo = null;
    for (const [fips, t] of Object.entries(hour.temps)) {
      if (hi === null || t > hi.t) hi = { fips, t };
      if (lo === null || t < lo.t) lo = { fips, t };
    }
    const label = (e) => `${NAMES[e.fips] || e.fips} · ${e.t.toFixed(1)}°F`;
    const set = (sel, txt) => { const el = $(sel); if (el) el.textContent = txt; };
    if (hi) set("[data-stat-hottest]", label(hi));
    if (lo) set("[data-stat-coldest]", label(lo));
    set("[data-stat-span]", `${hour.min_f.toFixed(1)}°F – ${hour.max_f.toFixed(1)}°F`);
    set("[data-stat-valid]", fmtTime(hour.valid_utc));
    set("[data-valid-time]", "valid " + fmtTime(hour.valid_utc));
  }

  function drawLegend(hour) {
    const wrap = $("[data-temp-legend]");
    if (!wrap) return;
    // bucket edge temps: percentile → quantiles of this hour; absolute → fixed scale
    const edges = [];
    for (let i = 0; i <= N; i++) {
      if (mode === "pct") {
        const k = Math.min(hour._sorted.length - 1, Math.round((i / N) * (hour._sorted.length - 1)));
        edges.push(hour._sorted[k]);
      } else {
        edges.push(gMin + (i / N) * (gMax - gMin));
      }
    }
    let html = `<span class="tl-cap">Cold</span>`;
    for (let i = 0; i < N; i++) {
      html += `<i style="background:${RAMP[i]}" title="${edges[i].toFixed(1)}–${edges[i + 1].toFixed(1)}°F"></i>`;
    }
    html += `<span class="tl-cap">Hot</span>`;
    const note = mode === "pct"
      ? `Each colour holds 1/${N} of counties this hour (percentile) — so Alaska no longer stretches the scale.`
      : `Fixed scale: ${gMin.toFixed(0)}°F to ${gMax.toFixed(0)}°F across all ${HOURS.length} hours.`;
    wrap.innerHTML = `<div class="tl-ramp">${html}</div><span class="tl-note">${note}</span>`;
  }
})();
