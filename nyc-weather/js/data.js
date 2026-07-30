// ---------------------------------------------------------------------------
// Data layer: fetch forecasts / observations / alerts, compute ensemble bands.
// Plain classic script (no ES modules) so index.html works when opened directly
// from disk (file://) as well as when deployed. Functions live on global scope.
// ---------------------------------------------------------------------------
"use strict";

const POP_THRESHOLD_IN = 0.01; // inches/hour a member must exceed to count as "raining"

// linear-interpolated percentile of a numeric array; p in 0..100
function pct(vals, p) {
  if (!vals || !vals.length) return null;
  const s = vals.slice().sort((a, b) => a - b);
  const i = (p / 100) * (s.length - 1);
  const lo = Math.floor(i), hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
}

// Collect every ensemble member's series for a variable, transposed to per-hour rows.
// Handles single-model keys (temperature_2m_member01) AND multi-model keys
// (temperature_2m_member01_ncep_gefs_seamless). Nulls are dropped per hour.
function membersByHour(hourly, prefix, H) {
  const arrs = Object.keys(hourly)
    .filter((k) => k.startsWith(prefix + "_member"))
    .map((k) => hourly[k]);
  const out = new Array(H);
  for (let h = 0; h < H; h++) {
    const row = [];
    for (const a of arrs) { const v = a[h]; if (v != null) row.push(v); }
    out[h] = row;
  }
  return out;
}

// tiny localStorage cache: return cached value if fresh, else run fn() and store it
async function cached(key, ttlMs, fn) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const { t, v } = JSON.parse(raw);
      if (Date.now() - t < ttlMs) return v;
    }
  } catch (e) { /* ignore corrupt/absent cache */ }
  const v = await fn();
  try { localStorage.setItem(key, JSON.stringify({ t: Date.now(), v })); } catch (e) { /* quota */ }
  return v;
}

// Regional 7-day hourly forecast: ensemble percentile bands + raw members
// (for spaghetti / thresholds / rain-timing) + deterministic extras (uv, dew,
// cloud, weather code) from the standard forecast API, aligned by timestamp.
async function getForecast(lat, lon) {
  const key = `wx.fc.${lat.toFixed(3)},${lon.toFixed(3)}`;
  return cached(key, 2 * 3600e3 /* 2h */, async () => {
    const ensUrl =
      "https://ensemble-api.open-meteo.com/v1/ensemble" +
      `?latitude=${lat}&longitude=${lon}` +
      "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m" +
      "&models=gfs_seamless,ecmwf_ifs025,icon_seamless" +
      "&forecast_days=7&temperature_unit=fahrenheit&wind_speed_unit=mph" +
      "&precipitation_unit=inch&timezone=auto&timeformat=unixtime";
    const exUrl =
      "https://api.open-meteo.com/v1/forecast" +
      `?latitude=${lat}&longitude=${lon}` +
      "&hourly=uv_index,dew_point_2m,cloud_cover,weather_code" +
      "&forecast_days=7&temperature_unit=fahrenheit&timezone=auto&timeformat=unixtime";
    const [ensRes, exRes] = await Promise.all([fetch(ensUrl), fetch(exUrl).catch(() => null)]);
    if (!ensRes.ok) throw new Error("forecast fetch failed: " + ensRes.status);
    const { hourly } = await ensRes.json();
    const H = hourly.time.length;
    const T = membersByHour(hourly, "temperature_2m", H);
    const A = membersByHour(hourly, "apparent_temperature", H);
    const RH = membersByHour(hourly, "relative_humidity_2m", H);
    const P = membersByHour(hourly, "precipitation", H);
    const W = membersByHour(hourly, "wind_speed_10m", H);
    const G = membersByHour(hourly, "wind_gusts_10m", H);

    // deterministic extras, aligned to the ensemble time axis by timestamp
    let uv = [], dewMed = [], cloud = [], code = [];
    try {
      if (exRes && exRes.ok) {
        const ex = (await exRes.json()).hourly;
        const idx = new Map(ex.time.map((t, i) => [t, i]));
        for (const ts of hourly.time) {
          const j = idx.get(ts);
          uv.push(j == null ? null : ex.uv_index[j]);
          dewMed.push(j == null ? null : ex.dew_point_2m[j]);
          cloud.push(j == null ? null : ex.cloud_cover[j]);
          code.push(j == null ? null : ex.weather_code[j]);
        }
      }
    } catch (e) { /* extras optional */ }

    return {
      time: hourly.time, // unix seconds (UTC); formatted in the place's tz at display
      memberCount: T.reduce((m, r) => Math.max(m, r.length), 0),
      tMed: T.map((r) => pct(r, 50)), tLo: T.map((r) => pct(r, 10)), tHi: T.map((r) => pct(r, 90)),
      feelsMed: A.map((r) => pct(r, 50)), feelsLo: A.map((r) => pct(r, 10)), feelsHi: A.map((r) => pct(r, 90)),
      rhMed: RH.map((r) => pct(r, 50)), rhLo: RH.map((r) => pct(r, 10)), rhHi: RH.map((r) => pct(r, 90)),
      dewMed, uv, cloud, code,
      pop: P.map((r) => (r.length ? (r.filter((v) => v > POP_THRESHOLD_IN).length / r.length) * 100 : null)),
      windMed: W.map((r) => pct(r, 50)),
      gustMed: G.map((r) => pct(r, 50)),
      members: { t: T, precip: P, gust: G }, // [hourIndex][memberIndex]
    };
  });
}

// Active NWS alerts for a point (for the warnings banner; US only, empty elsewhere).
async function getAlerts(lat, lon) {
  return cached(`wx.alerts.${lat.toFixed(2)},${lon.toFixed(2)}`, 10 * 60e3, async () => {
    try {
      const res = await fetch(`https://api.weather.gov/alerts/active?point=${lat},${lon}`);
      if (!res.ok) return [];
      const j = await res.json();
      return (j.features || []).map((f) => ({
        event: f.properties && f.properties.event,
        headline: f.properties && f.properties.headline,
        severity: f.properties && f.properties.severity,
      }));
    } catch (e) { return []; }
  });
}
