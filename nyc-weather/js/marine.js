/* js/marine.js — coastal-only waves + tides panel.
 *
 * Public API (all on global scope, classic script — no import/export):
 *   isCoastal(place)         -> boolean   (slug set + runtime additions + place.coastal tag)
 *   addCoastalSlug(slug)     -> void      (extend the coastal set at runtime)
 *   getMarine(lat, lon)      -> Promise<marine|null>   (Open-Meteo marine, cached)
 *   getTides(slug)           -> Promise<tides|null>    (NOAA hi/lo predictions, cached)
 *   renderMarine(fc, el)     -> Promise<void>          (main entry; fills `el`)
 *
 * Data are INDICATIVE model output, NOT for navigation. See notes.
 */

/* ---- coastal gating ------------------------------------------------------ */

// Hardcoded coastal slugs (spec). Mutable set so callers can extend it.
var MARINE_COASTAL_SLUGS = new Set([
  'battery-park', 'flushing', 'stony-brook', 'houston'
]);

// Slug -> nearby NOAA tide station id (US only).
var MARINE_TIDE_STATIONS = {
  'battery-park': '8518750', // The Battery, NY
  'stony-brook':  '8514560', // Port Jefferson, NY
  'flushing':     '8516945', // Kings Point, NY
  'houston':      '8770613'  // Morgans Point, Galveston Bay, TX
};

function addCoastalSlug(slug, tideStationId) {
  if (!slug) return;
  MARINE_COASTAL_SLUGS.add(slug);
  if (tideStationId) MARINE_TIDE_STATIONS[slug] = String(tideStationId);
}

function isCoastal(place) {
  if (!place) return false;
  // Explicit tag wins (Andrew will tag coastal places).
  if (place.coastal === true) return true;
  return MARINE_COASTAL_SLUGS.has(place.slug);
}

/* ---- tiny cached-fetch helper (localStorage {t,v} + TTL) ----------------- */

function _marineCacheGet(key, ttlMs) {
  try {
    var raw = localStorage.getItem(key);
    if (!raw) return null;
    var o = JSON.parse(raw);
    if (o && typeof o.t === 'number' && (Date.now() - o.t) < ttlMs) return o.v;
  } catch (e) { /* ignore corrupt/absent cache */ }
  return null;
}
function _marineCacheSet(key, v) {
  try { localStorage.setItem(key, JSON.stringify({ t: Date.now(), v: v })); }
  catch (e) { /* quota/full — non-fatal */ }
}

/* ---- unit + time helpers ------------------------------------------------- */

function _cToF(c) { return (c == null) ? null : (c * 9 / 5 + 32); }
function _mToFt(m) { return (m == null) ? null : (m * 3.28084); }

// First non-null value at-or-after `nowSec` in a unixtime-indexed series.
function _seriesAt(times, vals, nowSec) {
  if (!times || !vals) return { i: -1, v: null };
  for (var i = 0; i < times.length; i++) {
    if (times[i] >= nowSec && vals[i] != null) return { i: i, v: vals[i] };
  }
  // fall back to last non-null before now
  for (var j = times.length - 1; j >= 0; j--) {
    if (vals[j] != null) return { i: j, v: vals[j] };
  }
  return { i: -1, v: null };
}

// 16-point compass from degrees.
function _compass(deg) {
  if (deg == null) return '';
  var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
              'S','SSW','SW','WSW','W','WNW','NW','NNW'];
  return dirs[Math.round(((deg % 360) / 22.5)) % 16];
}

function _esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

/* ---- getMarine ----------------------------------------------------------- */
// Returns { time:number[], waveHeight:number[](m), wavePeriod:number[](s),
//           waveDir:number[](deg), sstC:number[](°C) } or null on error.
// hasWaves / hasSst flags computed by caller from null-ness.
function getMarine(lat, lon) {
  var key = 'marine:' + lat.toFixed(3) + ',' + lon.toFixed(3);
  var cached = _marineCacheGet(key, 60 * 60 * 1000); // 1h TTL
  if (cached) return Promise.resolve(cached);

  var url = 'https://marine-api.open-meteo.com/v1/marine'
    + '?latitude=' + encodeURIComponent(lat)
    + '&longitude=' + encodeURIComponent(lon)
    + '&hourly=wave_height,wave_period,wave_direction,sea_surface_temperature'
    + '&timezone=auto&timeformat=unixtime&forecast_days=2';

  return fetch(url).then(function (r) {
    if (!r.ok) throw new Error('marine http ' + r.status);
    return r.json();
  }).then(function (d) {
    var h = (d && d.hourly) || {};
    var out = {
      time:       h.time || [],
      waveHeight: h.wave_height || [],
      wavePeriod: h.wave_period || [],
      waveDir:    h.wave_direction || [],
      sstC:       h.sea_surface_temperature || []
    };
    _marineCacheSet(key, out);
    return out;
  }).catch(function () { return null; });
}

/* ---- getTides ------------------------------------------------------------ */
// Returns { events:[{ local:string, type:'H'|'L', ft:number }] } or null.
// NOAA returns station-local wall-clock strings ("YYYY-MM-DD HH:MM" via
// lst_ldt); we keep the raw string and convert to an epoch in the place tz
// downstream (see _wallClockToEpochSec).
function getTides(slug) {
  var station = MARINE_TIDE_STATIONS[slug];
  if (!station) return Promise.resolve(null);

  var key = 'tides:' + slug + ':' + new Date().toISOString().slice(0, 10);
  var cached = _marineCacheGet(key, 6 * 60 * 60 * 1000); // 6h TTL (today only)
  if (cached) return Promise.resolve(cached);

  var url = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
    + '?product=predictions&interval=hilo&datum=MLLW&units=english'
    + '&time_zone=lst_ldt&format=json&date=today&station=' + station;

  return fetch(url).then(function (r) {
    if (!r.ok) throw new Error('tides http ' + r.status);
    return r.json();
  }).then(function (d) {
    if (!d || d.error || !Array.isArray(d.predictions)) return null;
    var events = d.predictions.map(function (p) {
      return { local: p.t, type: p.type, ft: parseFloat(p.v) };
    }).filter(function (e) { return e.local && (e.type === 'H' || e.type === 'L'); });
    var out = { events: events };
    _marineCacheSet(key, out);
    return out;
  }).catch(function () { return null; });
}

/* ---- tide time parsing ---------------------------------------------------
 * NOAA gives station-local wall-clock strings (lst_ldt). We format everything
 * in fc.place.tz. For US coastal places the station tz == place tz, so we
 * parse the wall-clock string against the place tz: find the UTC instant whose
 * representation in tz matches, via the tz offset at that date (DST-correct).
 */
function _wallClockToEpochSec(localStr, tz) {
  var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(localStr);
  if (!m) return NaN;
  var y = +m[1], mo = +m[2], d = +m[3], hh = +m[4], mm = +m[5];
  // Treat the wall time as if UTC, then correct by the tz offset at that instant.
  var guess = Date.UTC(y, mo - 1, d, hh, mm, 0);
  var offsetMs = _tzOffsetMs(guess, tz);
  return Math.round((guess - offsetMs) / 1000);
}

// Offset (ms) of `tz` from UTC at instant `utcMs`. Positive east of UTC.
function _tzOffsetMs(utcMs, tz) {
  try {
    var dtf = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    var parts = dtf.formatToParts(new Date(utcMs));
    var map = {};
    for (var i = 0; i < parts.length; i++) map[parts[i].type] = parts[i].value;
    var asUTC = Date.UTC(+map.year, +map.month - 1, +map.day,
                         +map.hour === 24 ? 0 : +map.hour, +map.minute, +map.second);
    return asUTC - utcMs;
  } catch (e) { return 0; }
}

function _fmtTime(epochSec, tz) {
  try {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hour: 'numeric', minute: '2-digit'
    }).format(new Date(epochSec * 1000));
  } catch (e) {
    return new Date(epochSec * 1000).toUTCString().slice(17, 22);
  }
}

/* ---- renderMarine -------------------------------------------------------- */

function renderMarine(fc, el) {
  if (!el) return Promise.resolve();
  var place = fc && fc.place;

  if (!isCoastal(place)) { el.innerHTML = ''; return Promise.resolve(); }

  el.innerHTML = '<div class="card marine"><div class="muted">Loading marine…</div></div>';

  var nowSec = (fc && fc.time && fc.time.length) ? fc.time[0]
             : Math.floor(Date.now() / 1000);

  return Promise.all([
    getMarine(place.lat, place.lon),
    getTides(place.slug)
  ]).then(function (res) {
    var marine = res[0], tides = res[1];

    var hasWaves = !!(marine && marine.waveHeight.some(function (v) { return v != null; }));
    var hasSst   = !!(marine && marine.sstC.some(function (v) { return v != null; }));
    var hasTides = !!(tides && tides.events.length);

    // Open-Meteo returns null arrays inland — if nothing marine at all, hide.
    if (!hasWaves && !hasSst && !hasTides) {
      el.innerHTML = '';
      return;
    }

    var html = '<div class="card marine">';
    html += '<div class="marine-title">Marine <span class="hint">' + _esc(place.name || '') + '</span></div>';

    /* --- Sea surface temperature --- */
    if (hasSst) {
      var sst = _seriesAt(marine.time, marine.sstC, nowSec);
      var sstF = _cToF(sst.v);
      var nextIdx = sst.i >= 0 ? sst.i + 6 : -1;
      var nextF = (nextIdx >= 0 && nextIdx < marine.sstC.length)
        ? _cToF(marine.sstC[nextIdx]) : null;
      html += '<div class="marine-row"><span class="marine-k">Sea temp</span>'
        + '<span class="marine-v">' + (sstF != null ? Math.round(sstF) + '°F' : '—');
      if (nextF != null && sstF != null && Math.abs(nextF - sstF) >= 1) {
        html += ' <span class="hint">→ ' + Math.round(nextF) + '° in 6h</span>';
      }
      html += '</span></div>';
    }

    /* --- Waves --- */
    if (hasWaves) {
      var wh = _seriesAt(marine.time, marine.waveHeight, nowSec);
      var wp = _seriesAt(marine.time, marine.wavePeriod, nowSec);
      var wd = _seriesAt(marine.time, marine.waveDir, nowSec);
      var ft = _mToFt(wh.v);
      html += '<div class="marine-row"><span class="marine-k">Waves</span>'
        + '<span class="marine-v">'
        + (ft != null ? ft.toFixed(1) + ' ft' : '—')
        + (wh.v != null ? ' <span class="hint">(' + wh.v.toFixed(2) + ' m)</span>' : '')
        + '</span></div>';
      var swellBits = [];
      if (wp.v != null) swellBits.push(wp.v.toFixed(0) + 's period');
      if (wd.v != null) swellBits.push('from ' + _compass(wd.v) + ' (' + Math.round(wd.v) + '°)');
      if (swellBits.length) {
        html += '<div class="marine-row"><span class="marine-k">Swell</span>'
          + '<span class="marine-v">' + swellBits.join(' · ') + '</span></div>';
      }
    }

    /* --- Tides --- */
    if (hasTides) {
      var tz = place.tz;
      var evs = tides.events.map(function (e) {
        return { tSec: _wallClockToEpochSec(e.local, tz), type: e.type, ft: e.ft };
      }).filter(function (e) { return !isNaN(e.tSec); })
        .sort(function (a, b) { return a.tSec - b.tSec; });

      // Rising/falling now: between events tide moves toward the NEXT event's type.
      var nextEv = null, prevEv = null;
      for (var k = 0; k < evs.length; k++) {
        if (evs[k].tSec >= nowSec) { nextEv = evs[k]; break; }
        prevEv = evs[k];
      }
      var trend = '';
      if (nextEv) {
        trend = (nextEv.type === 'H') ? 'rising' : 'falling';
      } else if (prevEv) {
        // after last event of the day — heading toward the opposite of last.
        trend = (prevEv.type === 'H') ? 'falling' : 'rising';
      }

      html += '<div class="marine-row marine-tide-now"><span class="marine-k">Tide</span>'
        + '<span class="marine-v">'
        + (trend ? '<span class="marine-trend marine-' + trend + '">'
              + (trend === 'rising' ? '▲ rising' : '▼ falling') + '</span>' : '—')
        + '</span></div>';

      html += '<div class="marine-tides">';
      for (var t = 0; t < evs.length; t++) {
        var e2 = evs[t];
        var isNext = (nextEv && e2.tSec === nextEv.tSec);
        html += '<div class="marine-tide' + (isNext ? ' is-next' : '')
              + (e2.tSec < nowSec ? ' is-past' : '') + '">'
          + '<span class="marine-tide-type marine-tide-' + (e2.type === 'H' ? 'hi' : 'lo') + '">'
          + (e2.type === 'H' ? 'High' : 'Low') + '</span>'
          + '<span class="marine-tide-time">' + _fmtTime(e2.tSec, tz) + '</span>'
          + '<span class="marine-tide-ft">' + e2.ft.toFixed(1) + ' ft</span>'
          + '</div>';
      }
      html += '</div>';
    } else {
      html += '<div class="marine-row"><span class="marine-k">Tide</span>'
        + '<span class="marine-v muted">no station</span></div>';
    }

    html += '<div class="hint marine-caveat">Indicative model &amp; predicted tides — not for navigation.</div>';
    html += '</div>';
    el.innerHTML = html;
  }).catch(function () {
    // Never throw out of a render fn.
    el.innerHTML = '<div class="card marine"><div class="muted">Marine data unavailable.</div></div>';
  });
}