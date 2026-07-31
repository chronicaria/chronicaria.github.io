// ---------------------------------------------------------------------------
// App: grouped place sidebar, 7-day cards, "now" card, charts, NWS alerts.
// Each place carries its own timezone; charts read in that place's local time.
// The neighborhood urban-heat offset (NYC only) localizes the forecast (Phase 3).
// Depends (via classic <script> order) on: data.js, chart.js, places.js.
// ---------------------------------------------------------------------------
"use strict";

const $ = (id) => document.getElementById(id);
let charts = [];
let lastFc = null; // localized forecast, for cheap chart re-render on resize
let current = 0;
let TZ = "America/New_York"; // current place's timezone (for day-card labels)

function setStatus(msg) { $("status").textContent = msg; }

function nowIndex(time) {
  const now = Date.now() / 1000;
  let idx = 0, best = Infinity;
  for (let i = 0; i < time.length; i++) {
    const dd = Math.abs(time[i] - now);
    if (dd < best) { best = dd; idx = i; }
  }
  return idx;
}

// slice all series so the charts start at the current hour (index of last hour <= now)
function sliceFrom(fc, s) {
  const out = { ...fc };
  for (const k of ["time", "tMed", "tLo", "tHi", "feelsMed", "feelsLo", "feelsHi", "rhMed", "rhLo", "rhHi", "dewMed", "uv", "cloud", "code", "pop", "windMed", "gustMed"]) {
    if (Array.isArray(fc[k])) out[k] = fc[k].slice(s);
  }
  if (fc.members) out.members = { t: fc.members.t.slice(s), precip: fc.members.precip.slice(s), gust: fc.members.gust.slice(s) };
  return out;
}

// Phase 3 — apply the neighborhood's day/night urban-heat offset to the forecast.
function isNight(ts) { const h = localHour(ts); return h < 7 || h >= 19; }
function localize(fc, offset) {
  if (!offset || (!offset.day && !offset.night)) return fc;
  const shift = fc.time.map((ts) => (isNight(ts) ? offset.night : offset.day));
  const add = (arr) => arr.map((v, i) => (v == null ? null : v + shift[i]));
  const out = {
    ...fc,
    tMed: add(fc.tMed), tLo: add(fc.tLo), tHi: add(fc.tHi),
    feelsMed: add(fc.feelsMed), feelsLo: add(fc.feelsLo), feelsHi: add(fc.feelsHi),
  };
  if (fc.members) out.members = { ...fc.members, t: fc.members.t.map((row, i) => row.map((v) => v + shift[i])) };
  return out;
}

function dailySummary(fc) {
  const ymd = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
  const dow = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short" });
  const map = new Map();
  for (let i = 0; i < fc.time.length; i++) {
    const d = new Date(fc.time[i] * 1000);
    const key = ymd.format(d);
    let g = map.get(key);
    if (!g) { g = { dow: dow.format(d), hi: -Infinity, lo: Infinity, pop: 0, uvMax: 0, windMax: 0, cloudSum: 0, n: 0, startIdx: i, endIdx: i }; map.set(key, g); }
    g.endIdx = i;
    const t = fc.tMed[i];
    if (t != null) { if (t > g.hi) g.hi = t; if (t < g.lo) g.lo = t; }
    if (fc.pop[i] != null && fc.pop[i] > g.pop) g.pop = fc.pop[i];
    if (fc.uv && fc.uv[i] != null && fc.uv[i] > g.uvMax) g.uvMax = fc.uv[i];
    if (fc.gustMed[i] != null && fc.gustMed[i] > g.windMax) g.windMax = fc.gustMed[i];
    if (fc.cloud && fc.cloud[i] != null) { g.cloudSum += fc.cloud[i]; g.n++; }
  }
  return [...map.values()].filter((g) => g.hi > -Infinity).slice(0, 7).map((g) => ({ ...g, cloudMean: g.n ? g.cloudSum / g.n : null }));
}

function popIcon(p) { return p >= 60 ? "🌧️" : p >= 30 ? "🌦️" : p >= 15 ? "⛅" : "☀️"; }

// p10/p90 of each member's daily-max temperature — the "cool-case / hot-case" range
function dayHiRange(fc, g) {
  const M = fc.members && fc.members.t;
  if (!M) return null;
  const first = M[g.startIdx];
  if (!first || !first.length) return null;
  const maxes = [];
  for (let m = 0; m < first.length; m++) {
    let mx = -Infinity;
    for (let i = g.startIdx; i <= g.endIdx; i++) { const v = M[i] && M[i][m]; if (v != null && v > mx) mx = v; }
    if (mx > -Infinity) maxes.push(mx);
  }
  if (!maxes.length) return null;
  maxes.sort((a, b) => a - b);
  const q = (p) => maxes[Math.floor((p / 100) * (maxes.length - 1))];
  return { lo: q(10), hi: q(90) };
}

function renderDayCards(fc, days, chips) {
  $("daycards").innerHTML = days
    .map((g, i) => {
      const spark = sparklineSVG(fc.tLo.slice(g.startIdx, g.endIdx + 1), fc.tHi.slice(g.startIdx, g.endIdx + 1), fc.tMed.slice(g.startIdx, g.endIdx + 1));
      const r = dayHiRange(fc, g);
      const range = r ? `<div class="dc-range">${r.lo.toFixed(0)}–${r.hi.toFixed(0)}°</div>` : "";
      const chip = chips && chips[i] ? `<div class="dc-chip">${chips[i]}</div>` : "";
      return `<div class="daycard">
        <div class="dc-day">${i === 0 ? "Today" : g.dow}</div>
        <div class="dc-icon">${popIcon(g.pop)}</div>
        <div class="dc-hi">${g.hi.toFixed(1)}°</div>
        ${range}
        <div class="dc-lo">${g.lo.toFixed(1)}°</div>
        ${spark}
        <div class="dc-pop">💧 ${Math.round(g.pop)}%</div>
        ${chip}
      </div>`;
    })
    .join("");
}

function renderAlerts(alerts) {
  const el = $("alerts");
  if (!alerts || !alerts.length) { el.innerHTML = ""; el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = alerts
    .map((a) => `<strong>⚠ ${a.event || "Alert"}</strong>${a.headline ? " — " + a.headline : ""}`)
    .join("<br>");
}

function offsetCaption(name, offset) {
  if (!offset || (!offset.day && !offset.night)) return name;
  const s = (v) => (v >= 0 ? "+" : "") + v + "°";
  return `${name} · urban-heat offset ${s(offset.day)} day / ${s(offset.night)} night (est.)`;
}

function renderNow(fc, name, offset, today) {
  const i = nowIndex(fc.time);
  const t = fc.tMed[i], f = fc.feelsMed[i], p = fc.pop[i], rh = fc.rhMed[i];
  let niceLine = "";
  if (typeof niceDayScore === "function" && today) {
    const nd = safe(() => niceDayScore({ hiF: today.hi, loF: today.lo, popMax: today.pop, windMax: today.windMax, uvMax: today.uvMax, cloudMeanPct: today.cloudMean }));
    if (nd && nd.score != null) niceLine = `<div class="now-nice">Today's vibe <b>${nd.score}/100</b>${nd.reason ? ` — ${nd.reason}` : ""}</div>`;
  }
  $("now").innerHTML = `
    <div class="now-main">${t == null ? "--" : t.toFixed(1)}°<span class="now-unit">F</span></div>
    <div class="now-side">
      <div>Feels like <b>${f == null ? "--" : f.toFixed(1)}°</b></div>
      <div>Precip chance <b>${p == null ? "--" : Math.round(p)}%</b> · Humidity <b>${rh == null ? "--" : Math.round(rh)}%</b></div>
      ${niceLine}
      <div class="now-off">${offsetCaption(name, offset)}</div>
    </div>`;
}

function renderCharts(fc) {
  charts.forEach((c) => { try { c.destroy(); } catch (e) {} });
  const now = Date.now() / 1000;
  let s = 0;
  for (let i = 0; i < fc.time.length; i++) { if (fc.time[i] <= now) s = i; }
  const v = sliceFrom(fc, s); // anchor charts to the current hour
  charts = [
    tempFeelsChart($("chart-tempfeels"), v),
    precipChart($("chart-precip"), v),
    windChart($("chart-wind"), v),
    bandChart($("chart-humidity"), v.time, { med: v.rhMed, lo: v.rhLo, hi: v.rhHi, name: "Humidity", color: "#4fd1c5", fill: "rgba(79,209,197,0.15)", unit: "%", suffix: "%", dec: 0, height: 150 }),
  ];
}

function safe(fn) { try { return fn(); } catch (e) { console.warn(e); return null; } }

// short local time, e.g. "4:20 PM", in the place's timezone
function fmtT(ts, tz) {
  return new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(ts * 1000));
}

// format derive.thresholdProbs output ([{dateKey, chips:[{label,pct,kind}]}]) → one chip string per day
function thresholdChips(fc, days) {
  const tp = thresholdProbs(fc, days);
  if (!Array.isArray(tp)) return null;
  return tp.map((d) => {
    const chips = d && d.chips ? d.chips : (Array.isArray(d) ? d : []);
    const c = chips[0];
    return c && c.pct != null && c.pct >= 10 ? `${Math.round(c.pct)}% ${c.label}` : "";
  });
}

// --- derive-based glance panels (I render; derive.js supplies the logic) ---
function renderRainTiming(fc, el) {
  if (typeof rainWindows !== "function") { el.innerHTML = ""; return; }
  const { windows, dryWindows } = rainWindows(fc, 24);
  const tz = fc.place.tz;
  if (!windows.length) { el.innerHTML = `<h3>🌂 Rain timing</h3><div class="muted">No rain expected in the next 24 hours.</div>`; return; }
  const lines = windows.slice(0, 2).map((w) =>
    `<div><b>${w.intensity}</b> · ${w.confidence} — ${fmtT(w.startTs, tz)}–${fmtT(w.endTs, tz)} <span class="muted">(${Math.round(w.prob * 100)}%)</span></div>`).join("");
  let dry = null;
  for (const d of dryWindows) if (!dry || (d.endTs - d.startTs) > (dry.endTs - dry.startTs)) dry = d;
  const dryLine = dry && dry.endTs > dry.startTs ? `<div class="muted" style="margin-top:6px">Driest gap: ${fmtT(dry.startTs, tz)}–${fmtT(dry.endTs, tz)}</div>` : "";
  el.innerHTML = `<h3>🌂 Rain timing</h3>${lines}${dryLine}`;
}

function renderWhatWear(fc, el) {
  if (typeof whatToWear !== "function") { el.innerHTML = ""; return; }
  const { icons, verdict } = whatToWear(fc);
  const row = icons.map((ic) => `<span class="wear-ic" title="${ic.label}">${ic.emoji}</span>`).join(" ");
  el.innerHTML = `<h3>🧥 What to wear</h3><div class="wear-row">${row || "—"}</div><div class="muted">${verdict}</div>`;
}

function renderComfort(fc, el) {
  if (typeof mugginess !== "function") { el.innerHTML = ""; return; }
  const dew0 = fc.dewMed && fc.dewMed[0];
  const mug = mugginess(dew0);
  const wc = warmestCoolestHour(fc);
  const tz = fc.place.tz;
  const warm = wc.warmIdx != null ? `${Math.round(fc.tMed[wc.warmIdx])}° ${fmtT(fc.time[wc.warmIdx], tz)}` : "—";
  const cool = wc.coolIdx != null ? `${Math.round(fc.tMed[wc.coolIdx])}° ${fmtT(fc.time[wc.coolIdx], tz)}` : "—";
  el.innerHTML = `<h3>💧 Comfort</h3><div><span class="big">${mug.label}</span>${dew0 != null ? ` <span class="muted">dew ${Math.round(dew0)}°</span>` : ""}</div>` +
    `<div class="muted" style="margin-top:6px">Warmest ${warm} · coolest ${cool}</div>`;
}

function renderUV(fc, el) {
  if (typeof uvWindow !== "function" || !fc.uv) { el.innerHTML = ""; return; }
  const H = fc.time.length;
  const uw = uvWindow(fc, [0, Math.min(23, H - 1)]);
  if (uw.peak == null || uw.peak < 1) { el.innerHTML = `<h3>☀️ UV index</h3><div class="muted">Low UV in the next 24h — no protection needed.</div>`; return; }
  const tz = fc.place.tz;
  const cat = uw.peak >= 11 ? "Extreme" : uw.peak >= 8 ? "Very high" : uw.peak >= 6 ? "High" : uw.peak >= 3 ? "Moderate" : "Low";
  const win = uw.protectStartTs != null ? `Protect ${fmtT(uw.protectStartTs, tz)}–${fmtT(uw.protectEndTs, tz)}` : "";
  el.innerHTML = `<h3>☀️ UV index</h3><div><span class="big">${uw.peak.toFixed(0)}</span> <span class="muted">${cat}, peaks ${fmtT(uw.peakTs, tz)}</span></div><div class="muted" style="margin-top:6px">${win}</div>`;
}

// call a feature module's render fn into a container, only if the module is loaded.
// Clear first so append-style modules (e.g. share button) don't accumulate on re-render.
function callPanel(fnName, fc, id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = "";
  if (typeof window[fnName] === "function") safe(() => window[fnName](fc, el));
}

function renderFeatures(fc, days) {
  callPanel("renderRainTiming", fc, "panel-rain");
  callPanel("renderWhatWear", fc, "panel-wear");
  callPanel("renderComfort", fc, "panel-comfort");
  callPanel("renderUV", fc, "panel-uv");
  callPanel("renderAstro", fc, "panel-astro");
  callPanel("renderAQI", fc, "panel-aqi");
  callPanel("renderClimate", fc, "panel-climate");
  callPanel("renderMarine", fc, "panel-marine");
  callPanel("renderShareButton", fc, "share-btn");
}

async function load(place) {
  setChartTz(place.tz);
  TZ = place.tz;
  setStatus("Loading…");
  const [fcRaw, alerts] = await Promise.all([
    getForecast(place.lat, place.lon).catch((e) => { console.error(e); return null; }),
    getAlerts(place.lat, place.lon).catch(() => []),
  ]);
  renderAlerts(alerts);
  if (fcRaw) {
    const fc = localize(fcRaw, place.offsetF);
    fc.place = place;
    lastFc = fc;
    const days = dailySummary(fc);
    const chips = safe(() => (typeof thresholdProbs === "function" ? thresholdChips(fc, days) : null));
    renderDayCards(fc, days, chips);
    renderNow(fc, place.name, place.offsetF, days[0]);
    renderCharts(fc);
    renderFeatures(fc, days); // Wave-2 feature panels (derive/astro/aqi/climate/marine/snapshot)
  } else {
    $("now").innerHTML = `<div class="muted">Forecast unavailable — check your connection and reload.</div>`;
  }
  setStatus(
    fcRaw
      ? `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · ${fcRaw.memberCount} ensemble members`
      : "Forecast unavailable"
  );
}

// --- URL routing: each place is a shareable hash (e.g. #seoul) ---
let loadedSlug = null;

function slugToIndex(slug) {
  const i = PLACES.findIndex((p) => p.slug === slug);
  return i >= 0 ? i : Math.max(0, PLACES.findIndex((p) => p.name === DEFAULT_PLACE));
}

function routeTo(slug) {
  const i = slugToIndex(slug);
  const p = PLACES[i];
  current = i;
  const buttons = [...document.querySelectorAll(".nb")];
  buttons.forEach((b) => b.classList.toggle("active", +b.dataset.i === i));
  const active = buttons.find((b) => +b.dataset.i === i);
  if (active) active.scrollIntoView({ block: "nearest" });
  document.title = `${p.name} — Weather Dashboard`;
  if (loadedSlug !== p.slug) { loadedSlug = p.slug; load(p); }
  if (location.hash.slice(1) !== p.slug) location.hash = p.slug; // normalize URL
}

function initSidebar() {
  const list = $("place-list");
  list.innerHTML = PLACE_GROUPS
    .map((g) => `
      <div class="place-group">
        <div class="group-head">${g.group}</div>
        <ul class="nbhd-list">
          ${g.places.map((p) => `<li><button class="nb" data-i="${PLACES.indexOf(p)}">${p.name}</button></li>`).join("")}
        </ul>
      </div>`)
    .join("");
  list.addEventListener("click", (e) => {
    const b = e.target.closest(".nb");
    if (b) location.hash = PLACES[+b.dataset.i].slug; // → hashchange → routeTo
  });
}

// debounced re-render (uPlot needs an explicit width) on window resize
let rt;
window.addEventListener("resize", () => {
  clearTimeout(rt);
  rt = setTimeout(() => { if (lastFc) renderCharts(lastFc); }, 150);
});

window.addEventListener("hashchange", () => routeTo(location.hash.slice(1)));

// spaghetti (raw ensemble members) toggle
const spag = $("spaghetti-toggle");
if (spag) spag.addEventListener("change", () => { setSpaghetti(spag.checked); if (lastFc) renderCharts(lastFc); });

initSidebar();
routeTo(location.hash.slice(1)); // deep-link on load, or default
