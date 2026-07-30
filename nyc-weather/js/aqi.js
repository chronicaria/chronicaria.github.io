/* js/aqi.js — air quality + wildfire-smoke flag.
 * Data: Open-Meteo Air Quality API (free, no key, CORS).
 * Public globals: getAQI(lat, lon) -> Promise<{...}>, renderAQI(fc, el).
 * Classic script: NO import/export. Degrades gracefully; never throws out of render.
 */

/* ---- US AQI category bands (breakpoints inclusive of low bound) ---- */
var AQI_BANDS = [
  { max: 50,       label: 'Good',           color: '#00e400',
    guide: 'Air quality is satisfactory; little or no risk.' },
  { max: 100,      label: 'Moderate',       color: '#e6c700',
    guide: 'Acceptable; unusually sensitive people should watch symptoms.' },
  { max: 150,      label: 'Unhealthy for Sensitive Groups', color: '#ff7e00',
    guide: 'Sensitive groups (heart/lung, kids, elderly) should limit prolonged exertion.' },
  { max: 200,      label: 'Unhealthy',      color: '#ff0000',
    guide: 'Everyone may feel effects; sensitive groups more serious. Limit exertion.' },
  { max: 300,      label: 'Very Unhealthy', color: '#8f3f97',
    guide: 'Health alert — everyone should avoid prolonged outdoor exertion.' },
  { max: Infinity, label: 'Hazardous',      color: '#7e0023',
    guide: 'Emergency conditions — everyone should stay indoors, keep exertion low.' }
];

function aqiBand(v) {
  if (v == null || isNaN(v)) return AQI_BANDS[0];
  for (var i = 0; i < AQI_BANDS.length; i++) {
    if (v <= AQI_BANDS[i].max) return AQI_BANDS[i];
  }
  return AQI_BANDS[AQI_BANDS.length - 1];
}

/* Rough "dominant sense" from the numbers we have. The API doesn't return the
 * dominant pollutant directly, so infer PM2.5 vs ozone by comparing each to the
 * AQI level its own concentration implies (higher sub-index ~ dominant). */
function aqiDominant(pm25, ozone_ugm3, no2) {
  var parts = [];
  if (pm25 != null && !isNaN(pm25)) parts.push(['PM2.5 (fine particles)', pm25 / 35.4]);       // 35.4 = top of "moderate" PM2.5
  if (ozone_ugm3 != null && !isNaN(ozone_ugm3)) parts.push(['ozone', ozone_ugm3 / 140]);       // ~70 ppb ~ 140 ug/m3 moderate top
  if (no2 != null && !isNaN(no2)) parts.push(['nitrogen dioxide', no2 / 200]);
  if (!parts.length) return null;
  parts.sort(function (a, b) { return b[1] - a[1]; });
  return parts[0][0];
}

/* ---- fetch + cache ---- */
function getAQI(lat, lon) {
  var TTL = 30 * 60 * 1000; // 30 min
  var key = 'aqi:' + Number(lat).toFixed(3) + ',' + Number(lon).toFixed(3);

  try {
    var raw = localStorage.getItem(key);
    if (raw) {
      var c = JSON.parse(raw);
      if (c && c.t && (Date.now() - c.t < TTL) && c.v) return Promise.resolve(c.v);
    }
  } catch (e) { /* ignore cache read errors */ }

  var url = 'https://air-quality-api.open-meteo.com/v1/air-quality'
    + '?latitude=' + encodeURIComponent(lat)
    + '&longitude=' + encodeURIComponent(lon)
    + '&hourly=us_aqi,pm2_5,pm10,ozone,nitrogen_dioxide,aerosol_optical_depth'
    + '&current=us_aqi,pm2_5'
    + '&timezone=auto&timeformat=unixtime&forecast_days=2&past_days=1';

  return fetch(url)
    .then(function (r) {
      if (!r.ok) throw new Error('aqi http ' + r.status);
      return r.json();
    })
    .then(function (j) {
      var h = j.hourly || {};
      var cur = j.current || {};
      var v = {
        time:        h.time || [],
        us_aqi:      h.us_aqi || [],
        pm2_5:       h.pm2_5 || [],
        pm10:        h.pm10 || [],
        ozone:       h.ozone || [],
        no2:         h.nitrogen_dioxide || [],
        aod:         h.aerosol_optical_depth || [],
        currentAqi:  (cur.us_aqi != null ? cur.us_aqi : null),
        currentPm25: (cur.pm2_5 != null ? cur.pm2_5 : null)
      };
      try { localStorage.setItem(key, JSON.stringify({ t: Date.now(), v: v })); } catch (e) {}
      return v;
    });
}

/* ---- helpers ---- */
function aqiMedian(arr) {
  var xs = [];
  for (var i = 0; i < arr.length; i++) {
    var n = arr[i];
    if (n != null && !isNaN(n)) xs.push(n);
  }
  if (!xs.length) return null;
  xs.sort(function (a, b) { return a - b; });
  var m = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
}

/* index in aqi.time nearest to a target unix-seconds t (both sorted asc) */
function aqiNearestIdx(times, t) {
  if (!times || !times.length) return 0;
  var best = 0, bestD = Infinity;
  for (var i = 0; i < times.length; i++) {
    var d = Math.abs(times[i] - t);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

function aqiEscape(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c];
  });
}

/* ---- render ---- */
function renderAQI(fc, el) {
  if (!el) return;
  var tz = (fc && fc.place && fc.place.tz) || 'UTC';
  var lat = fc && fc.place && fc.place.lat;
  var lon = fc && fc.place && fc.place.lon;

  el.innerHTML = '<div class="aqi-card card"><div class="muted">Loading air quality…</div></div>';

  if (lat == null || lon == null) {
    el.innerHTML = '<div class="aqi-card card"><div class="muted">Air quality unavailable.</div></div>';
    return;
  }

  getAQI(lat, lon).then(function (aq) {
    try {
      var nowSec = (fc && fc.time && fc.time.length) ? fc.time[0] : Math.floor(Date.now() / 1000);
      var i0 = aqiNearestIdx(aq.time, nowSec);

      /* current AQI: prefer API's `current`, fall back to nearest hourly */
      var cur = aq.currentAqi;
      if (cur == null) cur = aq.us_aqi[i0];
      var band = aqiBand(cur);
      var curPm = (aq.currentPm25 != null ? aq.currentPm25 : aq.pm2_5[i0]);

      var dom = aqiDominant(curPm, aq.ozone[i0], aq.no2[i0]);

      /* ---- smoke flag: current PM2.5 vs the place's own past-24h baseline ---- */
      var past = [];
      for (var k = 0; k < i0; k++) {
        var p = aq.pm2_5[k];
        if (p != null && !isNaN(p)) past.push(p);
      }
      past = past.slice(-24); // last ~24 hourly samples before "now"
      var baseMed = aqiMedian(past);
      var smoke = false;
      if (curPm != null && !isNaN(curPm) && baseMed != null && baseMed > 0) {
        smoke = (curPm > 2.5 * baseMed) && (curPm > 20);
      }

      /* ---- next ~24h sparkline data ---- */
      var spark = [];
      for (var j = i0; j < aq.time.length && spark.length < 25; j++) {
        var val = aq.us_aqi[j];
        if (val != null && !isNaN(val)) spark.push({ t: aq.time[j], v: val });
      }

      /* time formatter in the place's tz */
      var fmt;
      try {
        fmt = new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: true });
      } catch (e) {
        fmt = new Intl.DateTimeFormat('en-US', { hour: 'numeric', hour12: true });
      }

      /* ---- build sparkline SVG (segments colored by band) ---- */
      var sparkHtml = '';
      if (spark.length >= 2) {
        var W = 260, H = 46, PAD = 3;
        var vals = spark.map(function (d) { return d.v; });
        var vmax = Math.max.apply(null, vals);
        var vmin = Math.min.apply(null, vals);
        var lo = Math.min(vmin, 0);
        var hi = Math.max(vmax, 50);      // keep a floor so flat-good days aren't a wild zigzag
        var span = (hi - lo) || 1;
        var n = spark.length;
        function sx(idx) { return PAD + idx * (W - 2 * PAD) / (n - 1); }
        function sy(v)   { return H - PAD - (v - lo) / span * (H - 2 * PAD); }

        var segs = '';
        for (var s = 0; s < n - 1; s++) {
          var midv = (spark[s].v + spark[s + 1].v) / 2;
          var c = aqiBand(midv).color;
          segs += '<line x1="' + sx(s).toFixed(1) + '" y1="' + sy(spark[s].v).toFixed(1)
                + '" x2="' + sx(s + 1).toFixed(1) + '" y2="' + sy(spark[s + 1].v).toFixed(1)
                + '" stroke="' + c + '" stroke-width="2" stroke-linecap="round"/>';
        }
        /* endpoint dot + peak label */
        var peakIdx = 0;
        for (var pI = 1; pI < n; pI++) if (spark[pI].v > spark[peakIdx].v) peakIdx = pI;
        var startLbl = aqiEscape(fmt.format(new Date(spark[0].t * 1000)));
        var endLbl   = aqiEscape(fmt.format(new Date(spark[n - 1].t * 1000)));

        sparkHtml =
          '<div class="aqi-spark-wrap">'
          + '<svg class="aqi-spark" viewBox="0 0 ' + W + ' ' + H + '" width="100%" height="' + H
          + '" preserveAspectRatio="none" role="img" aria-label="Next 24h AQI">'
          + segs
          + '<circle cx="' + sx(n - 1).toFixed(1) + '" cy="' + sy(spark[n - 1].v).toFixed(1)
          + '" r="2.5" fill="' + aqiBand(spark[n - 1].v).color + '"/>'
          + '</svg>'
          + '<div class="aqi-spark-axis"><span>' + startLbl + '</span>'
          + '<span>peak ' + Math.round(spark[peakIdx].v) + '</span>'
          + '<span>' + endLbl + '</span></div>'
          + '</div>';
      } else {
        sparkHtml = '<div class="muted hint">Hourly AQI forecast unavailable.</div>';
      }

      /* ---- assemble ---- */
      var curTxt = (cur != null && !isNaN(cur)) ? String(Math.round(cur)) : '—';
      var domTxt = dom ? ('Dominant: ' + aqiEscape(dom)) : '';
      var pmTxt  = (curPm != null && !isNaN(curPm))
        ? ('PM2.5 ' + (Math.round(curPm * 10) / 10) + ' µg/m³') : '';
      var subline = [domTxt, pmTxt].filter(Boolean).join(' · ');

      var smokeHtml = smoke
        ? ('<div class="aqi-smoke">🔥 Smoke likely — PM2.5 is '
           + (Math.round((curPm / baseMed) * 10) / 10) + '× above this location’s recent baseline.</div>')
        : '';

      el.innerHTML =
        '<div class="aqi-card card">'
        + '<div class="aqi-head">'
        +   '<div class="aqi-num" style="color:' + band.color + '">' + curTxt + '</div>'
        +   '<div class="aqi-headtxt">'
        +     '<div class="aqi-cat"><span class="aqi-dot" style="background:' + band.color + '"></span>'
        +       aqiEscape(band.label) + '</div>'
        +     '<div class="aqi-sub muted">US AQI · ' + aqiEscape(subline || 'air quality') + '</div>'
        +   '</div>'
        + '</div>'
        + smokeHtml
        + '<div class="aqi-guide">' + aqiEscape(band.guide) + '</div>'
        + sparkHtml
        + '<div class="hint muted aqi-src">Source: Open-Meteo air quality · updates ~hourly, model-based</div>'
        + '</div>';
    } catch (err) {
      el.innerHTML = '<div class="aqi-card card"><div class="muted">Air quality unavailable.</div></div>';
    }
  }).catch(function () {
    el.innerHTML = '<div class="aqi-card card"><div class="muted">Air quality unavailable.</div></div>';
  });
}