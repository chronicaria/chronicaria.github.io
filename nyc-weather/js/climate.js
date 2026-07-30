// ---------------------------------------------------------------------------
// Climate layer: "today vs normal" + records, from ERA5 reanalysis.
// Open-Meteo Archive API (FREE, no key, CORS). ERA5 has ~5-day latency and
// ~80yr history; we fetch ~20 years, then client-side filter to a ±3-calendar-
// day window around today's month/day across all years to compute the normal
// high/low and record high/low. Results (four numbers + record years) are cached
// AGGRESSIVELY in localStorage (keyed by rounded lat/lon + calendar day, 7-day
// TTL) so this expensive fetch happens rarely and re-loads are instant.
//
// Honest labeling: these are REANALYSIS normals (a gridded model estimate), not
// official station records. Depends (via <script> order) on nothing but the
// browser; renderClimate reads the `fc` object app.js already localized.
// ---------------------------------------------------------------------------
"use strict";

// Ordinal 1..366 for a month/day, using a fixed non-leap calendar so every year
// lines up. Feb 29 collapses onto Feb 28's ordinal (fine for a ±3-day window).
const CLIMATE_MONTH_CUM = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
function climateOrdinal(month1, day) {
  return CLIMATE_MONTH_CUM[month1 - 1] + day; // month1 is 1..12
}

// Circular distance between two ordinals on a 365-day ring (so Dec 31 ↔ Jan 1
// is a distance of 1, not 364). Used to select the ±3-day window.
function climateDayDist(a, b) {
  const d = Math.abs(a - b);
  return Math.min(d, 365 - d);
}

// Fetch ~20 years of ERA5 daily max/min, filter to a ±3-day window around
// todayDate's month/day across all years, and reduce to normals + records.
// todayDate: a Date (defaults to now). Returns:
//   { normalHigh, normalLow, recordHigh, recordHighYear, recordLow, recordLowYear,
//     sampleDays, throughYear }  — or null on failure.
async function getClimate(lat, lon, todayDate) {
  const today = todayDate || new Date();
  const dayKey =
    today.getFullYear() + "-" +
    String(today.getMonth() + 1).padStart(2, "0") + "-" +
    String(today.getDate()).padStart(2, "0");
  const cacheKey = `wx.climate.${lat.toFixed(2)},${lon.toFixed(2)}.${dayKey}`;
  const TTL = 7 * 24 * 3600e3; // 7 days

  // cache read
  try {
    const raw = localStorage.getItem(cacheKey);
    if (raw) {
      const { t, v } = JSON.parse(raw);
      if (v && Date.now() - t < TTL) return v;
    }
  } catch (e) { /* ignore corrupt/absent cache */ }

  try {
    // ERA5 latency: end the window ~7 days back so we never request missing days.
    const end = new Date(Date.now() - 7 * 24 * 3600e3);
    const endStr =
      end.getFullYear() + "-" +
      String(end.getMonth() + 1).padStart(2, "0") + "-" +
      String(end.getDate()).padStart(2, "0");
    const startStr = (end.getFullYear() - 20) + "-01-01"; // ~20 years back

    const url =
      "https://archive-api.open-meteo.com/v1/archive" +
      `?latitude=${lat}&longitude=${lon}` +
      `&start_date=${startStr}&end_date=${endStr}` +
      "&daily=temperature_2m_max,temperature_2m_min" +
      "&timezone=auto&temperature_unit=fahrenheit";

    const res = await fetch(url);
    if (!res.ok) throw new Error("climate fetch failed: " + res.status);
    const j = await res.json();
    const d = j && j.daily;
    if (!d || !d.time || !d.temperature_2m_max) throw new Error("no daily data");

    const target = climateOrdinal(today.getMonth() + 1, today.getDate());
    const highs = d.temperature_2m_max;
    const lows = d.temperature_2m_min;

    let hiSum = 0, hiN = 0, loSum = 0, loN = 0;
    let recHi = -Infinity, recHiYear = null;
    let recLo = Infinity, recLoYear = null;

    for (let i = 0; i < d.time.length; i++) {
      const s = d.time[i];            // "YYYY-MM-DD"
      const year = +s.slice(0, 4);
      const month = +s.slice(5, 7);
      const day = +s.slice(8, 10);
      if (climateDayDist(climateOrdinal(month, day), target) > 3) continue;

      const hi = highs[i], lo = lows[i];
      if (hi != null) {
        hiSum += hi; hiN++;
        if (hi > recHi) { recHi = hi; recHiYear = year; }
      }
      if (lo != null) {
        loSum += lo; loN++;
        if (lo < recLo) { recLo = lo; recLoYear = year; }
      }
    }

    if (!hiN || !loN) throw new Error("empty ±3-day window");

    const out = {
      normalHigh: hiSum / hiN,
      normalLow: loSum / loN,
      recordHigh: recHi,
      recordHighYear: recHiYear,
      recordLow: recLo,
      recordLowYear: recLoYear,
      sampleDays: hiN,
      throughYear: end.getFullYear(),
    };
    try { localStorage.setItem(cacheKey, JSON.stringify({ t: Date.now(), v: out })); } catch (e) { /* quota */ }
    return out;
  } catch (e) {
    console.error("getClimate:", e);
    return null;
  }
}

// Highest fc.tMed over today's calendar day (in the place's tz). Returns null if
// no forecast hours fall on today.
function climateTodayHigh(fc, tz) {
  if (!fc || !fc.time || !fc.tMed || !fc.time.length) return null;
  const ymd = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
  });
  const todayStr = ymd.format(new Date()); // "YYYY-MM-DD" in tz
  let hi = -Infinity;
  for (let i = 0; i < fc.time.length; i++) {
    if (ymd.format(new Date(fc.time[i] * 1000)) !== todayStr) continue;
    const t = fc.tMed[i];
    if (t != null && t > hi) hi = t;
  }
  return hi > -Infinity ? hi : null;
}

// Compact "today vs normal" card. Fetches climate (cached), then fills `el`.
// Reads the place's timezone from fc.place.tz when present, else the app's
// global TZ, else UTC. Never throws; shows a muted "unavailable" line on error.
function renderClimate(fc, el) {
  if (!el) return;
  const place = fc && fc.place;
  const tz = (place && place.tz) || (typeof TZ !== "undefined" ? TZ : "UTC");
  const lat = place ? place.lat : (fc && fc.lat);
  const lon = place ? place.lon : (fc && fc.lon);

  const unavail = (msg) => {
    el.innerHTML =
      `<h2>Today vs normal</h2>` +
      `<div class="muted climate-unavail">${msg || "Climate normals unavailable."}</div>`;
  };

  if (lat == null || lon == null) { unavail("Climate normals unavailable (no location)."); return; }

  el.innerHTML = `<h2>Today vs normal</h2><div class="muted climate-loading">Loading reanalysis normals…</div>`;

  getClimate(lat, lon).then((c) => {
    if (!c) { unavail(); return; }

    const r = (v) => (v == null ? "--" : Math.round(v));
    const yr = (y) => (y == null ? "" : ` <span class="climate-yr">(${y})</span>`);

    const todayHi = climateTodayHigh(fc, tz);
    let anomaly = "";
    if (todayHi != null && c.normalHigh != null) {
      const diff = todayHi - c.normalHigh;
      const mag = Math.abs(diff);
      if (mag < 1) {
        anomaly = `Today's forecast high <b>${r(todayHi)}°</b> — right about normal.`;
      } else {
        const dir = diff > 0 ? "above" : "below";
        anomaly =
          `Today's forecast high <b>${r(todayHi)}°</b> — running ` +
          `<b class="climate-${diff > 0 ? "warm" : "cool"}">${Math.round(mag)}° ${dir}</b> normal.`;
      }
    }

    el.innerHTML =
      `<h2>Today vs normal</h2>` +
      `<div class="climate-line">` +
        `<span class="climate-lab">Normal</span> ` +
        `<b>${r(c.normalHigh)}°</b> / <b>${r(c.normalLow)}°</b>` +
        ` <span class="climate-sep">·</span> ` +
        `<span class="climate-lab">Record</span> ` +
        `<b>${r(c.recordHigh)}°</b>${yr(c.recordHighYear)} / ` +
        `<b>${r(c.recordLow)}°</b>${yr(c.recordLowYear)}` +
      `</div>` +
      (anomaly ? `<div class="climate-anom">${anomaly}</div>` : "") +
      `<div class="climate-note muted">Reanalysis normal (ERA5), ±3-day window · ` +
        `${c.sampleDays} days through ${c.throughYear} · ~5-day latency. Not station records.</div>`;
  }).catch((e) => { console.error("renderClimate:", e); unavail(); });
}