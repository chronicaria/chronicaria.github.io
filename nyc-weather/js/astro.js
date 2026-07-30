/* js/astro.js — Sun & Moon strip.
 * Depends only on global SunCalc (mourner/suncalc), vendored before this script.
 * Entry point: renderAstro(fc, el). Never throws out of the render fn.
 */

/* ---- small helpers ------------------------------------------------------ */

// Is this a real, finite Date? SunCalc returns `Invalid Date` at high
// latitudes when the sun never rises/sets, so every time value gets checked.
function astroValidDate(d) {
  return d instanceof Date && !isNaN(d.getTime());
}

// Format a Date as a short local time (e.g. "6:14am") in the place's tz.
// Returns null for missing/invalid dates so callers can show a dash.
function astroFmtTime(d, tz) {
  if (!astroValidDate(d)) return null;
  try {
    var s = new Intl.DateTimeFormat('en-US', {
      hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz
    }).format(d);
    // "6:14 AM" -> "6:14am"
    return s.replace(/\s/g, '').replace('AM', 'am').replace('PM', 'pm');
  } catch (e) {
    return null;
  }
}

// Duration in ms -> "10h 32m".
function astroFmtDur(ms) {
  if (!isFinite(ms) || ms < 0) return '—';
  var mins = Math.round(ms / 60000);
  var h = Math.floor(mins / 60);
  var m = mins % 60;
  return h + 'h ' + (m < 10 ? '0' + m : m) + 'm';
}

// Signed "+3m 12s" / "−1m 40s" delta vs yesterday, given ms difference.
function astroFmtDelta(ms) {
  if (!isFinite(ms)) return '';
  var sign = ms >= 0 ? '+' : '−'; // real minus sign for the negative case
  var secs = Math.round(Math.abs(ms) / 1000);
  var m = Math.floor(secs / 60);
  var s = secs % 60;
  return sign + m + 'm ' + (s < 10 ? '0' + s : s) + 's';
}

// Escape for safe innerHTML injection (place names, etc.).
function astroEsc(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Map moon phase fraction (0..1 from SunCalc) to a name.
// 0 = new, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter.
function astroPhaseName(phase) {
  if (phase < 0.03 || phase > 0.97) return 'New moon';
  if (phase < 0.22) return 'Waxing crescent';
  if (phase < 0.28) return 'First quarter';
  if (phase < 0.47) return 'Waxing gibbous';
  if (phase < 0.53) return 'Full moon';
  if (phase < 0.72) return 'Waning gibbous';
  if (phase < 0.78) return 'Last quarter';
  return 'Waning crescent';
}

// A little unicode moon glyph for the phase, oriented for N. hemisphere.
function astroPhaseGlyph(phase) {
  if (phase < 0.03 || phase > 0.97) return '🌑'; // new
  if (phase < 0.22) return '🌒'; // waxing crescent
  if (phase < 0.28) return '🌓'; // first quarter
  if (phase < 0.47) return '🌔'; // waxing gibbous
  if (phase < 0.53) return '🌕'; // full
  if (phase < 0.72) return '🌖'; // waning gibbous
  if (phase < 0.78) return '🌗'; // last quarter
  return '🌘'; // waning crescent
}

// Waxing = illumination growing (phase 0..0.5); waning = shrinking (0.5..1).
function astroWaxWane(phase) {
  if (phase < 0.02 || phase > 0.98 || Math.abs(phase - 0.5) < 0.02) return '';
  return phase < 0.5 ? 'waxing' : 'waning';
}

// Fraction (0..1) of `d` between start..end, clamped. Used to place the sun
// dot along the daylight row. Returns null if the window is degenerate/invalid.
function astroFrac(d, start, end) {
  if (!astroValidDate(d) || !astroValidDate(start) || !astroValidDate(end)) return null;
  var span = end.getTime() - start.getTime();
  if (span <= 0) return null;
  var f = (d.getTime() - start.getTime()) / span;
  return Math.max(0, Math.min(1, f));
}

/* ---- main render -------------------------------------------------------- */

function renderAstro(fc, el) {
  if (!el) return;
  try {
    if (typeof SunCalc === 'undefined' || !SunCalc) {
      el.innerHTML = '<div class="astro card"><div class="muted">Sun &amp; moon data unavailable.</div></div>';
      return;
    }

    var place = (fc && fc.place) || {};
    var lat = place.lat, lon = place.lon;
    var tz = place.tz || 'UTC';
    if (typeof lat !== 'number' || typeof lon !== 'number') {
      el.innerHTML = '<div class="astro card"><div class="muted">Sun &amp; moon data unavailable.</div></div>';
      return;
    }

    var now = new Date();
    // Yesterday, same clock time — good enough for a day-length delta.
    var yesterday = new Date(now.getTime() - 86400000);

    var t = SunCalc.getTimes(now, lat, lon);
    var tY = SunCalc.getTimes(yesterday, lat, lon);

    // Day length today & yesterday (from sunrise->sunset).
    var dayMs = NaN, dayMsY = NaN, deltaMs = NaN;
    if (astroValidDate(t.sunrise) && astroValidDate(t.sunset)) {
      dayMs = t.sunset.getTime() - t.sunrise.getTime();
    }
    if (astroValidDate(tY.sunrise) && astroValidDate(tY.sunset)) {
      dayMsY = tY.sunset.getTime() - tY.sunrise.getTime();
    }
    if (isFinite(dayMs) && isFinite(dayMsY)) deltaMs = dayMs - dayMsY;

    var fmt = function (d) { return astroFmtTime(d, tz); };
    var dash = '<span class="astro-dash">—</span>';
    var cell = function (d) { var s = fmt(d); return s ? astroEsc(s) : dash; };

    // Sun positions along the row (sunrise=0 .. sunset=1).
    var noonFrac = astroFrac(t.solarNoon, t.sunrise, t.sunset);
    var goldenEndFrac = astroFrac(t.goldenHourEnd, t.sunrise, t.sunset); // morning golden hour end
    var goldenFrac = astroFrac(t.goldenHour, t.sunrise, t.sunset);       // evening golden hour start

    // --- Moon ---
    var illum = SunCalc.getMoonIllumination(now); // { fraction, phase, angle }
    var pct = Math.round((illum.fraction || 0) * 100);
    var phaseName = astroPhaseName(illum.phase);
    var glyph = astroPhaseGlyph(illum.phase);
    var ww = astroWaxWane(illum.phase);

    // Moonrise/set can land on the day before/after; check today and, if a
    // value is missing, peek at the next day so we still show one.
    var mt = SunCalc.getMoonTimes(now, lat, lon);
    var moonrise = mt.rise, moonset = mt.set;
    if (!astroValidDate(moonrise)) {
      var mtN = SunCalc.getMoonTimes(new Date(now.getTime() + 86400000), lat, lon);
      if (astroValidDate(mtN.rise)) moonrise = mtN.rise;
    }
    if (!astroValidDate(moonset)) {
      var mtN2 = SunCalc.getMoonTimes(new Date(now.getTime() + 86400000), lat, lon);
      if (astroValidDate(mtN2.set)) moonset = mtN2.set;
    }

    // --- "Tonight's sky" one-liner ---
    var skyBits = [];
    skyBits.push(phaseName);
    skyBits.push(pct + '% lit');
    var riseStr = astroFmtTime(moonrise, tz);
    if (riseStr && astroValidDate(moonrise) && moonrise.getTime() > now.getTime()) {
      skyBits.push('rises ' + riseStr);
    } else {
      var setStr = astroFmtTime(moonset, tz);
      if (setStr) skyBits.push('sets ' + setStr);
    }
    var brightness = pct >= 65 ? 'bright night'
                   : pct >= 30 ? 'moderate moonlight'
                   : pct <= 8  ? 'dark night — good for stars'
                   : 'dim moonlight';
    var skyNote = skyBits.join(', ') + ' — ' + brightness + '.';

    // Polar note: if the sun never rose or set today.
    var polarNote = '';
    if (!astroValidDate(t.sunrise) || !astroValidDate(t.sunset)) {
      var noonPos = SunCalc.getPosition(astroValidDate(t.solarNoon) ? t.solarNoon : now, lat, lon);
      polarNote = (noonPos.altitude > 0)
        ? 'Polar day — the sun stays above the horizon.'
        : 'Polar night — the sun stays below the horizon.';
    }

    /* ---- markup ---- */

    var sunRow;
    if (astroValidDate(t.sunrise) && astroValidDate(t.sunset) && noonFrac != null) {
      // Golden-hour band: morning (sunrise..goldenHourEnd) + evening (goldenHour..sunset).
      var gEnd = goldenEndFrac == null ? 0 : goldenEndFrac;
      var gStart = goldenFrac == null ? 1 : goldenFrac;
      sunRow =
        '<div class="astro-suntrack">' +
          '<div class="astro-track">' +
            '<div class="astro-golden astro-golden-am" style="left:0;width:' + (gEnd * 100).toFixed(1) + '%"></div>' +
            '<div class="astro-golden astro-golden-pm" style="left:' + (gStart * 100).toFixed(1) + '%;right:0"></div>' +
            '<div class="astro-arc"></div>' +
            '<div class="astro-noon" style="left:' + (noonFrac * 100).toFixed(1) + '%"></div>' +
            '<div class="astro-sun" style="left:' + (noonFrac * 100).toFixed(1) + '%"></div>' +
          '</div>' +
          '<div class="astro-ends">' +
            '<span class="astro-end"><span class="astro-ico">☀</span> ' + cell(t.sunrise) + '</span>' +
            '<span class="astro-end astro-end-mid">noon ' + cell(t.solarNoon) + '</span>' +
            '<span class="astro-end">' + cell(t.sunset) + ' <span class="astro-ico">◐</span></span>' +
          '</div>' +
        '</div>';
    } else {
      sunRow = '<div class="astro-suntrack"><div class="muted astro-polar">' +
        astroEsc(polarNote || 'Sun times unavailable at this latitude today.') + '</div></div>';
    }

    var deltaHtml = isFinite(deltaMs)
      ? '<span class="astro-delta ' + (deltaMs >= 0 ? 'astro-up' : 'astro-down') + '">' +
        astroFmtDelta(deltaMs) + ' vs yesterday</span>'
      : '';

    var facts =
      '<div class="astro-facts">' +
        '<span class="astro-fact"><span class="astro-k">Dawn</span>' + cell(t.dawn) + '</span>' +
        '<span class="astro-fact"><span class="astro-k">Golden a.m.</span>' + cell(t.goldenHourEnd) + '</span>' +
        '<span class="astro-fact"><span class="astro-k">Golden p.m.</span>' + cell(t.goldenHour) + '</span>' +
        '<span class="astro-fact"><span class="astro-k">Dusk</span>' + cell(t.dusk) + '</span>' +
        '<span class="astro-fact"><span class="astro-k">Day length</span>' + astroFmtDur(dayMs) +
          ' ' + deltaHtml + '</span>' +
      '</div>';

    var moonBlock =
      '<div class="astro-moon">' +
        '<div class="astro-moon-glyph" aria-hidden="true">' + glyph + '</div>' +
        '<div class="astro-moon-body">' +
          '<div class="astro-moon-title">' + astroEsc(phaseName) +
            (ww ? ' <span class="astro-moon-ww">(' + ww + ')</span>' : '') + '</div>' +
          '<div class="astro-moon-sub">' + pct + '% illuminated</div>' +
          '<div class="astro-moon-times">' +
            '<span><span class="astro-k">Moonrise</span>' + cell(moonrise) + '</span>' +
            '<span><span class="astro-k">Moonset</span>' + cell(moonset) + '</span>' +
          '</div>' +
        '</div>' +
      '</div>';

    el.innerHTML =
      '<div class="astro card">' +
        '<div class="astro-head">' +
          '<span class="astro-title">Sun &amp; Moon</span>' +
          '<span class="astro-place muted">' + astroEsc(place.name || '') + '</span>' +
        '</div>' +
        sunRow +
        facts +
        moonBlock +
        '<div class="astro-sky hint">' + astroEsc(skyNote) + '</div>' +
        (polarNote && astroValidDate(t.sunrise) ? '<div class="astro-sky hint">' + astroEsc(polarNote) + '</div>' : '') +
      '</div>';
  } catch (e) {
    // Absolute last resort — never throw out of a render fn.
    try {
      el.innerHTML = '<div class="astro card"><div class="muted">Sun &amp; moon data unavailable.</div></div>';
    } catch (e2) { /* give up silently */ }
  }
}