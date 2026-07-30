// ---------------------------------------------------------------------------
// Chart layer (dark, serif): uPlot builders for temperature, feels-like,
// humidity (generic band chart), precip probability (smooth curve), wind+gusts.
// The default legend is off; instead each chart shows an ON-GRAPH readout box
// that follows the cursor. All charts share cursor sync key "wx", so hovering
// one moves the crosshair AND the readout on every chart to the same hour.
// Times are real UTC unix seconds, formatted to America/New_York via Intl.
// ---------------------------------------------------------------------------
"use strict";

const FONT = '12px Georgia, "Times New Roman", serif';

// Timezone-aware formatters, rebuilt per place so every city reads in its own
// local time (data arrives as UTC unix seconds; we format in the place's tz).
let _wd, _hr, _h24, _full;
function setChartTz(tz) {
  _wd = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" });
  _hr = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", hour12: true });
  _h24 = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "2-digit", hour12: false });
  _full = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", month: "short", day: "numeric", hour: "numeric", hour12: true });
}
setChartTz("America/New_York");

function localHour(ts) { return +_h24.format(new Date(ts * 1000)) % 24; }

function axisTimeVals(u, splits) {
  return splits.map((ts) => {
    const d = new Date(ts * 1000);
    const h = +_h24.format(d) % 24;
    return h === 0 ? _wd.format(d) : _hr.format(d).replace(" ", "");
  });
}
const fullTime = (ts) => (ts == null ? "--" : _full.format(new Date(ts * 1000)));

function darkAxes(yLabel, yVals) {
  const common = {
    stroke: "#8b95a5",
    font: FONT,
    grid: { stroke: "rgba(255,255,255,0.06)", width: 1 },
    ticks: { stroke: "rgba(255,255,255,0.12)", width: 1, size: 4 },
  };
  return [
    { ...common, values: axisTimeVals },
    { ...common, label: yLabel, labelFont: FONT, labelSize: 20, values: yVals },
  ];
}

// dashed red vertical line at "now"
function nowLinePlugin() {
  return {
    hooks: {
      draw: (u) => {
        const now = Date.now() / 1000;
        const xs = u.data[0];
        if (!xs.length || now < xs[0] || now > xs[xs.length - 1]) return;
        const cx = Math.round(u.valToPos(now, "x", true));
        const ctx = u.ctx;
        ctx.save();
        ctx.strokeStyle = "rgba(255,99,99,0.6)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, u.bbox.top);
        ctx.lineTo(cx, u.bbox.top + u.bbox.height);
        ctx.stroke();
        ctx.restore();
      },
    },
  };
}

// on-graph readout box that follows the cursor; fmt(u, idx) -> HTML
function tipPlugin(fmt) {
  let tip;
  return {
    hooks: {
      init: (u) => {
        tip = document.createElement("div");
        tip.className = "u-tip";
        tip.style.display = "none";
        u.over.appendChild(tip);
      },
      setCursor: (u) => {
        const idx = u.cursor.idx;
        const left = u.cursor.left;
        if (idx == null || left == null || left < 0) { tip.style.display = "none"; return; }
        tip.innerHTML = fmt(u, idx);
        tip.style.display = "block";
        const w = tip.offsetWidth;
        const plotW = u.over.clientWidth;
        let x = left + 14;
        if (x + w > plotW) x = left - w - 14;
        tip.style.left = Math.max(2, Math.min(x, plotW - w - 2)) + "px";
        tip.style.top = "6px";
      },
    },
  };
}

const W = (el) => el.clientWidth || 600;
const invisible = { stroke: "transparent", points: { show: false } };
const num = (v, dec, suf) => (v == null ? "--" : v.toFixed(dec == null ? 1 : dec) + (suf || ""));

// spaghetti: draw every ensemble member's temperature as a faint thread
let SHOW_SPAGHETTI = false;
function setSpaghetti(on) { SHOW_SPAGHETTI = on; }
function spaghettiPlugin(membersT) {
  return {
    hooks: {
      draw: (u) => {
        if (!SHOW_SPAGHETTI || !membersT || !membersT.length) return;
        const ctx = u.ctx, xs = u.data[0];
        const M = membersT.find((r) => r && r.length);
        if (!M) return;
        ctx.save();
        ctx.strokeStyle = "rgba(77,155,255,0.09)";
        ctx.lineWidth = 1;
        for (let m = 0; m < M.length; m++) {
          ctx.beginPath();
          let started = false;
          for (let i = 0; i < xs.length; i++) {
            const row = membersT[i];
            if (!row || row[m] == null) { started = false; continue; }
            const x = u.valToPos(xs[i], "x", true);
            const y = u.valToPos(row[m], "y", true);
            if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        ctx.restore();
      },
    },
  };
}

// tiny inline-SVG temperature-band sparkline for the day cards
function sparklineSVG(lo, hi, med, w, h) {
  w = w || 108; h = h || 26;
  let min = Infinity, max = -Infinity;
  for (const a of [lo, hi]) for (const v of a) if (v != null) { if (v < min) min = v; if (v > max) max = v; }
  if (min === Infinity) return "";
  const n = med.length;
  const X = (i) => (n <= 1 ? 0 : (i / (n - 1)) * w);
  const Y = (v) => h - ((v - min) / (max - min || 1)) * (h - 2) - 1;
  const pts = (arr) => arr.map((v, i) => (v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
  const top = pts(hi), bot = pts(lo).reverse(), mid = pts(med);
  if (!mid.length) return "";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" preserveAspectRatio="none">` +
    `<path d="M${top.join(" L")} L${bot.join(" L")} Z" fill="rgba(77,155,255,0.20)"/>` +
    `<path d="M${mid.join(" L")}" fill="none" stroke="#4d9bff" stroke-width="1.2"/></svg>`;
}

// Generic median + p10–p90 band chart. Used for temperature, feels-like, humidity.
// o = { med, lo, hi, name, color, fill, unit, suffix, dec, height }
function bandChart(el, time, o) {
  el.innerHTML = "";
  const tip = (u, i) =>
    `<div class="tip-time">${fullTime(u.data[0][i])}</div>` +
    `<div class="tip-val"><b>${num(u.data[3][i], o.dec, o.suffix)}</b>` +
    `<span class="tip-band">${num(u.data[1][i], o.dec, "")}–${num(u.data[2][i], o.dec, o.suffix)}</span></div>`;
  return new uPlot(
    {
      width: W(el), height: o.height || 250,
      cursor: { sync: { key: "wx" } },
      legend: { show: false },
      scales: { x: { time: true } },
      series: [
        {},
        { ...invisible },
        { ...invisible },
        { stroke: o.color, width: 2, points: { show: false } },
      ],
      bands: [{ series: [2, 1], fill: o.fill }],
      axes: darkAxes(o.unit),
      plugins: [nowLinePlugin(), tipPlugin(tip)],
    },
    [time, o.lo, o.hi, o.med],
    el
  );
}

// Combined full-width temperature + feels-like: two bands + two medians, one
// overlay readout showing both values and both p10–p90 ranges.
function tempFeelsChart(el, fc) {
  el.innerHTML = "";
  const tip = (u, i) =>
    `<div class="tip-time">${fullTime(u.data[0][i])}</div>` +
    `<div class="tip-val"><span class="tip-dot" style="background:#4d9bff"></span>` +
    `<b>${num(u.data[3][i], 1, "°")}</b><span class="tip-band">${num(u.data[1][i], 1, "")}–${num(u.data[2][i], 1, "°")}</span></div>` +
    `<div class="tip-val"><span class="tip-dot" style="background:#ff9f45"></span>` +
    `<b>${num(u.data[6][i], 1, "°")}</b><span class="tip-band">${num(u.data[4][i], 1, "")}–${num(u.data[5][i], 1, "°")}</span></div>`;
  return new uPlot(
    {
      width: W(el), height: 300,
      cursor: { sync: { key: "wx" } },
      legend: { show: false },
      scales: { x: { time: true } },
      series: [
        {},
        { ...invisible }, { ...invisible },
        { stroke: "#4d9bff", width: 2, points: { show: false } },
        { ...invisible }, { ...invisible },
        { stroke: "#ff9f45", width: 2, dash: [5, 4], points: { show: false } },
      ],
      bands: SHOW_SPAGHETTI ? [] : [
        { series: [2, 1], fill: "rgba(77,155,255,0.15)" },
        { series: [5, 4], fill: "rgba(255,159,69,0.13)" },
      ],
      axes: darkAxes("°F"),
      plugins: [spaghettiPlugin(fc.members && fc.members.t), nowLinePlugin(), tipPlugin(tip)],
    },
    [fc.time, fc.tLo, fc.tHi, fc.tMed, fc.feelsLo, fc.feelsHi, fc.feelsMed],
    el
  );
}

function precipChart(el, d) {
  el.innerHTML = "";
  const tip = (u, i) =>
    `<div class="tip-time">${fullTime(u.data[0][i])}</div>` +
    `<div class="tip-val"><b>${u.data[1][i] == null ? "--" : Math.round(u.data[1][i]) + "%"}</b></div>`;
  return new uPlot(
    {
      width: W(el), height: 150,
      cursor: { sync: { key: "wx" } },
      legend: { show: false },
      scales: { x: { time: true }, y: { range: [0, 100] } },
      series: [
        {},
        { stroke: "#34d399", width: 2, fill: "rgba(52,211,153,0.22)", paths: uPlot.paths.spline(), points: { show: false } },
      ],
      axes: darkAxes("%", (u, vs) => vs.map((v) => v + "%")),
      plugins: [nowLinePlugin(), tipPlugin(tip)],
    },
    [d.time, d.pop],
    el
  );
}

function windChart(el, d) {
  el.innerHTML = "";
  const tip = (u, i) =>
    `<div class="tip-time">${fullTime(u.data[0][i])}</div>` +
    `<div class="tip-val"><b>${u.data[1][i] == null ? "--" : Math.round(u.data[1][i]) + " mph"}</b>` +
    `<span class="tip-band">gusts ${u.data[2][i] == null ? "--" : Math.round(u.data[2][i])}</span></div>`;
  return new uPlot(
    {
      width: W(el), height: 170,
      cursor: { sync: { key: "wx" } },
      legend: { show: false },
      scales: { x: { time: true } },
      series: [
        {},
        { stroke: "#a78bfa", width: 2, fill: "rgba(167,139,250,0.12)", points: { show: false } },
        { stroke: "#c4b5fd", width: 1.5, dash: [4, 3], points: { show: false } },
      ],
      axes: darkAxes("mph"),
      plugins: [nowLinePlugin(), tipPlugin(tip)],
    },
    [d.time, d.windMed, d.gustMed],
    el
  );
}
