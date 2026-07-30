/* snapshot.js — "share this forecast" PNG export.
 *
 * Public API (global, classic-script scope):
 *   exportSnapshot(fc)            -> renders a dark postcard to an offscreen
 *                                    canvas and downloads it as a PNG. Uses
 *                                    navigator.share / clipboard as a nicety.
 *   renderShareButton(fc, el)     -> drops a small "⬇ Share image" button into
 *                                    `el` wired to exportSnapshot(fc).
 *
 * Pure client-side. No network. Never throws out of a render fn.
 */

/* ---- palette (mirrors the app's CSS vars) ---- */
var SNAP_BG      = '#0e1116';
var SNAP_CARD    = '#161b22';
var SNAP_INK     = '#e6edf3';
var SNAP_MUTED   = '#8b949e';
var SNAP_LINE    = '#30363d';
var SNAP_BLUE    = '#4d9bff';
var SNAP_FONT    = 'Georgia, "Times New Roman", serif';

/* ---- small helpers ---- */

// First finite number in an array (or fallback).
function snapFirstNum(arr, fallback) {
  if (Array.isArray(arr)) {
    for (var i = 0; i < arr.length; i++) {
      if (typeof arr[i] === 'number' && isFinite(arr[i])) return arr[i];
    }
  }
  return fallback;
}

// Round to nearest int, guarding NaN.
function snapRound(n) {
  return (typeof n === 'number' && isFinite(n)) ? Math.round(n) : null;
}

// "72°" or "—" if not a number.
function snapDeg(n) {
  var r = snapRound(n);
  return (r === null) ? '—' : (r + '°');
}

// Local time string in the place's timezone (falls back to browser tz).
function snapLocalTime(fc) {
  try {
    var secs = snapFirstNum(fc.time, Math.floor(Date.now() / 1000));
    var opts = { weekday: 'short', month: 'short', day: 'numeric',
                 hour: 'numeric', minute: '2-digit' };
    if (fc.place && fc.place.tz) opts.timeZone = fc.place.tz;
    return new Intl.DateTimeFormat(undefined, opts).format(new Date(secs * 1000));
  } catch (e) {
    return '';
  }
}

// Draw the mini temperature band sparkline (filled band + median line) into
// the rect [x, y, w, h]. Uses tLo/tMed/tHi over the next ~n hours.
function snapDrawSparkline(ctx, fc, x, y, w, h, hours) {
  var lo = fc.tLo, med = fc.tMed, hi = fc.tHi;
  if (!Array.isArray(med) || med.length < 2) return false;

  var n = Math.min(hours, med.length);
  if (n < 2) return false;

  // Collect a padded value range across whichever series exist.
  var min = Infinity, max = -Infinity, i, v;
  function consider(arr) {
    if (!Array.isArray(arr)) return;
    for (i = 0; i < n; i++) {
      v = arr[i];
      if (typeof v === 'number' && isFinite(v)) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
  }
  consider(lo); consider(med); consider(hi);
  if (!isFinite(min) || !isFinite(max)) return false;
  if (max - min < 1) { max += 1; min -= 1; } // avoid flat divide-by-zero
  var pad = (max - min) * 0.12;
  min -= pad; max += pad;

  function px(idx) { return x + (w * idx) / (n - 1); }
  function py(val) { return y + h - ((val - min) / (max - min)) * h; }

  var haveBand = Array.isArray(lo) && Array.isArray(hi);

  // Filled p10–p90 band.
  if (haveBand) {
    ctx.beginPath();
    var started = false;
    for (i = 0; i < n; i++) {
      v = hi[i];
      if (typeof v !== 'number' || !isFinite(v)) v = med[i];
      if (!started) { ctx.moveTo(px(i), py(v)); started = true; }
      else ctx.lineTo(px(i), py(v));
    }
    for (i = n - 1; i >= 0; i--) {
      v = lo[i];
      if (typeof v !== 'number' || !isFinite(v)) v = med[i];
      ctx.lineTo(px(i), py(v));
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(77, 155, 255, 0.22)';
    ctx.fill();
  }

  // Median line.
  ctx.beginPath();
  var moved = false;
  for (i = 0; i < n; i++) {
    v = med[i];
    if (typeof v !== 'number' || !isFinite(v)) continue;
    if (!moved) { ctx.moveTo(px(i), py(v)); moved = true; }
    else ctx.lineTo(px(i), py(v));
  }
  ctx.strokeStyle = SNAP_BLUE;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.stroke();

  return true;
}

/* ---- the postcard renderer ---- */

// Draws the full 1000x520 postcard onto `canvas` at the given devicePixelRatio.
// Returns nothing; assumes canvas is already sized.
function snapPaint(fc, canvas, dpr) {
  var W = 1000, H = 520;
  var ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // crisp on high-DPI
  ctx.textBaseline = 'alphabetic';

  // Background.
  ctx.fillStyle = SNAP_BG;
  ctx.fillRect(0, 0, W, H);

  // Rounded inner card.
  var m = 28, r = 18;
  snapRoundRect(ctx, m, m, W - 2 * m, H - 2 * m, r);
  ctx.fillStyle = SNAP_CARD;
  ctx.fill();
  ctx.strokeStyle = SNAP_LINE;
  ctx.lineWidth = 1;
  ctx.stroke();

  var padX = m + 32;
  var topY = m + 30;

  // Place name.
  var place = (fc.place && fc.place.name) ? fc.place.name : 'Forecast';
  ctx.fillStyle = SNAP_INK;
  ctx.font = '600 34px ' + SNAP_FONT;
  ctx.fillText(place, padX, topY + 18);

  // Local time.
  ctx.fillStyle = SNAP_MUTED;
  ctx.font = '18px ' + SNAP_FONT;
  ctx.fillText(snapLocalTime(fc), padX, topY + 48);

  // Big current temp (tMed[0]).
  var t0 = snapFirstNum(fc.tMed, null);
  ctx.fillStyle = SNAP_INK;
  ctx.font = '600 118px ' + SNAP_FONT;
  var bigY = topY + 170;
  ctx.fillText(snapDeg(t0), padX, bigY);
  var bigW = ctx.measureText(snapDeg(t0)).width;

  // Feels-like + p10–p90 range, to the right of the big number.
  var feels = snapFirstNum(fc.feelsMed, null);
  var fLo = snapFirstNum(fc.feelsLo, null);
  var fHi = snapFirstNum(fc.feelsHi, null);
  var fx = padX + bigW + 26;
  ctx.fillStyle = SNAP_MUTED;
  ctx.font = '20px ' + SNAP_FONT;
  ctx.fillText('feels like', fx, bigY - 74);
  ctx.fillStyle = SNAP_INK;
  ctx.font = '600 40px ' + SNAP_FONT;
  ctx.fillText(snapDeg(feels), fx, bigY - 38);
  if (fLo !== null && fHi !== null) {
    ctx.fillStyle = SNAP_MUTED;
    ctx.font = '18px ' + SNAP_FONT;
    ctx.fillText(snapRound(fLo) + '° – ' + snapRound(fHi) + '°', fx, bigY - 8);
  }

  // Stat row: precip chance / humidity.
  var statY = bigY + 44;
  var pop = snapFirstNum(fc.pop, null);
  var rh = snapFirstNum(fc.rhMed, null);
  var stats = [];
  stats.push(['precip', pop === null ? '—' : (snapRound(pop) + '%')]);
  stats.push(['humidity', rh === null ? '—' : (snapRound(rh) + '%')]);
  var sx = padX;
  for (var s = 0; s < stats.length; s++) {
    ctx.fillStyle = SNAP_MUTED;
    ctx.font = '17px ' + SNAP_FONT;
    ctx.fillText(stats[s][0], sx, statY);
    ctx.fillStyle = SNAP_INK;
    ctx.font = '600 26px ' + SNAP_FONT;
    ctx.fillText(stats[s][1], sx, statY + 30);
    sx += 150;
  }

  // Sparkline panel (next ~48h temperature band).
  var spX = padX, spY = statY + 60;
  var spW = W - padX - m - 32, spH = 96;
  ctx.fillStyle = SNAP_MUTED;
  ctx.font = '15px ' + SNAP_FONT;
  ctx.fillText('next 48 hours', spX, spY - 8);
  var drew = snapDrawSparkline(ctx, fc, spX, spY, spW, spH, 48);
  if (!drew) {
    ctx.fillStyle = SNAP_MUTED;
    ctx.font = '16px ' + SNAP_FONT;
    ctx.fillText('trend unavailable', spX, spY + spH / 2);
  }

  // Footer.
  ctx.fillStyle = SNAP_MUTED;
  ctx.font = '15px ' + SNAP_FONT;
  ctx.fillText('yoursite • Open-Meteo ensemble', padX, H - m - 20);
}

// Rounded-rect path helper.
function snapRoundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/* ---- export + share ---- */

function snapFilename(fc) {
  var slug = (fc.place && (fc.place.slug || fc.place.name)) || 'forecast';
  slug = String(slug).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return 'forecast-' + (slug || 'snapshot') + '.png';
}

// Trigger a browser download of a blob.
function snapDownload(blob, filename) {
  try {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  } catch (e) { /* ignore */ }
}

// Nicety: offer native share / clipboard when the platform supports files.
function snapTryShare(blob, filename, fc) {
  try {
    var file = (typeof File !== 'undefined')
      ? new File([blob], filename, { type: 'image/png' })
      : null;
    if (file && navigator.canShare && navigator.canShare({ files: [file] })
        && navigator.share) {
      var place = (fc.place && fc.place.name) ? fc.place.name : 'Forecast';
      navigator.share({ files: [file], title: place + ' forecast' })
        .catch(function () {});
      return;
    }
    // Silent clipboard copy where available (non-blocking, best-effort).
    if (file && navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
      var item = {}; item['image/png'] = blob;
      navigator.clipboard.write([new window.ClipboardItem(item)]).catch(function () {});
    }
  } catch (e) { /* ignore */ }
}

// Main entry: build the postcard and download it.
function exportSnapshot(fc) {
  try {
    if (!fc) return;
    var W = 1000, H = 520;
    var dpr = Math.max(1, (window.devicePixelRatio || 1));
    var canvas = document.createElement('canvas');
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';

    snapPaint(fc, canvas, dpr);

    var filename = snapFilename(fc);
    if (canvas.toBlob) {
      canvas.toBlob(function (blob) {
        if (!blob) return;
        snapDownload(blob, filename);
        snapTryShare(blob, filename, fc);
      }, 'image/png');
    } else {
      // Very old fallback: data-URL download.
      var a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = filename;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
    }
  } catch (e) {
    // Never throw out of the handler.
    try { console && console.warn && console.warn('snapshot export failed', e); } catch (_) {}
  }
}

// Renders a small share button into `el`, wired to exportSnapshot(fc).
function renderShareButton(fc, el) {
  try {
    if (!el) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'snap-share-btn';
    btn.textContent = '⬇ Share image';
    btn.addEventListener('click', function () {
      btn.disabled = true;
      var prev = btn.textContent;
      btn.textContent = '… rendering';
      // Yield so the label repaints before the (sync) canvas work.
      setTimeout(function () {
        exportSnapshot(fc);
        btn.disabled = false;
        btn.textContent = prev;
      }, 0);
    });
    el.appendChild(btn);
  } catch (e) {
    try {
      if (el) { el.insertAdjacentHTML('beforeend',
        '<span class="muted hint">share unavailable</span>'); }
    } catch (_) {}
  }
}