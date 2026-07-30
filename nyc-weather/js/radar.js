/* radar.js — live precipitation radar mini-map (dependency-free, no Leaflet).
 *
 * Data:  RainViewer weather-maps.json  (free, no key, CORS)
 * Radar: ${host}${frame.path}/256/${z}/${x}/${y}/4/1_1.png   (color scheme 4, smooth+snow)
 * Base:  https://basemaps.cartocdn.com/dark_all/${z}/${x}/${y}.png  (CARTO dark, free, CORS)
 *
 * Entry point:  renderRadar(fc, el)
 * Never throws out of the render fn; degrades to a muted "unavailable" line.
 */

/* ---- config ------------------------------------------------------------- */
var RADAR_Z = 7;                 // slippy-map zoom
var RADAR_TILES = 3;             // 3x3 grid of 256px tiles -> 768x768 (we crop height)
var RADAR_TILE = 256;
var RADAR_W = RADAR_TILES * RADAR_TILE;   // 768
var RADAR_H = 384;               // show a 768x384 letterbox centered vertically
var RADAR_MAPS_URL = 'https://api.rainviewer.com/public/weather-maps.json';
var RADAR_MAPS_TTL = 5 * 60 * 1000;       // cache weather-maps.json ~5 min
var RADAR_FRAME_MS = 500;                 // animation frame interval
var RADAR_ALPHA = 0.7;                    // radar layer opacity

/* ---- slippy-map tile math ---------------------------------------------- */
// Fractional tile coords let us center the canvas exactly on the place.
function radarLonToTileX(lon, z) {
  return (lon + 180) / 360 * Math.pow(2, z);
}
function radarLatToTileY(lat, z) {
  var r = lat * Math.PI / 180;
  return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z);
}

/* ---- localStorage cache (weather-maps.json) ---------------------------- */
function radarLoadMaps() {
  // returns a Promise<mapsJson>; uses a fresh cached copy when available.
  try {
    var raw = localStorage.getItem('radar:maps');
    if (raw) {
      var c = JSON.parse(raw);
      if (c && c.v && (Date.now() - c.t) < RADAR_MAPS_TTL) {
        return Promise.resolve(c.v);
      }
    }
  } catch (e) { /* ignore bad cache */ }

  return fetch(RADAR_MAPS_URL).then(function (r) {
    if (!r.ok) throw new Error('maps ' + r.status);
    return r.json();
  }).then(function (v) {
    try { localStorage.setItem('radar:maps', JSON.stringify({ t: Date.now(), v: v })); } catch (e) {}
    return v;
  });
}

/* ---- image loader (CORS-enabled) --------------------------------------- */
function radarLoadImg(url) {
  return new Promise(function (resolve) {
    var img = new Image();
    img.crossOrigin = 'anonymous';     // required to composite onto canvas
    img.onload = function () { resolve(img); };
    img.onerror = function () { resolve(null); };   // missing tile -> skip, don't reject
    img.src = url;
  });
}

/* ---- main render -------------------------------------------------------- */
function renderRadar(fc, el) {
  // Guard: never throw.
  try {
    if (!fc || !fc.place) { radarFail(el, 'no location'); return; }
  } catch (e) { radarFail(el, 'unavailable'); return; }

  var place = fc.place;
  var z = RADAR_Z;

  // Fractional center tile for the place.
  var cx = radarLonToTileX(place.lon, z);
  var cy = radarLatToTileY(place.lat, z);

  // Top-left tile index of the 3x3 grid (place sits in the center tile).
  var x0 = Math.floor(cx) - Math.floor(RADAR_TILES / 2);
  var y0 = Math.floor(cy) - Math.floor(RADAR_TILES / 2);

  // Pixel offset so the place lands at the canvas center.
  // Position of the grid's origin (x0,y0) in canvas px, then shift to center place.
  var placePxX = (cx - x0) * RADAR_TILE;                 // place x within the 768px grid
  var placePxY = (cy - y0) * RADAR_TILE;                 // place y within the 768px grid
  var offX = RADAR_W / 2 - placePxX;                     // pan so place -> horiz center
  var offY = RADAR_H / 2 - placePxY;                     // pan so place -> vert center

  // Build DOM shell.
  el.innerHTML = '';
  var wrap = document.createElement('div');
  wrap.className = 'radar-wrap';

  var canvas = document.createElement('canvas');
  canvas.className = 'radar-canvas';
  canvas.width = RADAR_W;
  canvas.height = RADAR_H;
  wrap.appendChild(canvas);

  // Controls overlay (play/pause + timestamp).
  var bar = document.createElement('div');
  bar.className = 'radar-bar';
  var btn = document.createElement('button');
  btn.className = 'radar-btn';
  btn.type = 'button';
  btn.textContent = '▶';       // play triangle
  btn.setAttribute('aria-label', 'Play radar animation');
  var stamp = document.createElement('span');
  stamp.className = 'radar-stamp muted';
  stamp.textContent = '…';
  bar.appendChild(btn);
  bar.appendChild(stamp);
  wrap.appendChild(bar);

  var status = document.createElement('div');
  status.className = 'radar-status hint';
  status.textContent = 'loading radar…';
  wrap.appendChild(status);

  el.appendChild(wrap);

  var ctx = canvas.getContext('2d');
  ctx.fillStyle = '#0b0e13';
  ctx.fillRect(0, 0, RADAR_W, RADAR_H);

  // State shared across async steps + animation.
  var state = {
    baseImgs: [],      // {img, dx, dy}
    frames: [],        // { time, path, tiles:[{img,dx,dy}] }
    idx: 0,            // current frame index
    timer: null,
    fmt: null
  };

  // Timestamp formatter in the place's timezone.
  try {
    state.fmt = new Intl.DateTimeFormat('en-US', {
      timeZone: place.tz, hour: 'numeric', minute: '2-digit', hour12: true,
      weekday: 'short'
    });
  } catch (e) {
    state.fmt = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  /* -- draw base (CARTO dark) tiles into the canvas once ------------------ */
  function drawBase() {
    for (var i = 0; i < state.baseImgs.length; i++) {
      var b = state.baseImgs[i];
      if (b.img) ctx.drawImage(b.img, b.dx, b.dy, RADAR_TILE, RADAR_TILE);
    }
  }

  /* -- draw a single radar frame + center dot over the (already drawn) base */
  function drawFrame(fi) {
    // Repaint base first (cheap: images already decoded), then radar, then dot.
    ctx.fillStyle = '#0b0e13';
    ctx.fillRect(0, 0, RADAR_W, RADAR_H);
    drawBase();

    var f = state.frames[fi];
    if (f && f.tiles) {
      ctx.globalAlpha = RADAR_ALPHA;
      for (var i = 0; i < f.tiles.length; i++) {
        var t = f.tiles[i];
        if (t.img) ctx.drawImage(t.img, t.dx, t.dy, RADAR_TILE, RADAR_TILE);
      }
      ctx.globalAlpha = 1;
    }

    // Center dot for the place.
    ctx.beginPath();
    ctx.arc(RADAR_W / 2, RADAR_H / 2, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#4ea1ff';
    ctx.globalAlpha = 0.9;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#ffffff';
    ctx.stroke();

    // Update timestamp label.
    if (f && f.time && state.fmt) {
      try { stamp.textContent = state.fmt.format(new Date(f.time * 1000)); } catch (e) {}
    }
  }

  /* -- tile URL builders -------------------------------------------------- */
  function baseUrl(tx, ty) {
    return 'https://basemaps.cartocdn.com/dark_all/' + z + '/' + tx + '/' + ty + '.png';
  }
  function radarUrl(host, path, tx, ty) {
    return host + path + '/' + RADAR_TILE + '/' + z + '/' + tx + '/' + ty + '/4/1_1.png';
  }

  // Per-tile draw offset within the canvas (grid col/row -> px, then pan).
  function tileOffsets() {
    var out = [];
    var maxTile = Math.pow(2, z);
    for (var gx = 0; gx < RADAR_TILES; gx++) {
      for (var gy = 0; gy < RADAR_TILES; gy++) {
        var tx = x0 + gx, ty = y0 + gy;
        // wrap x, drop out-of-world y (top/bottom edges)
        var wx = ((tx % maxTile) + maxTile) % maxTile;
        if (ty < 0 || ty >= maxTile) continue;
        out.push({
          gx: gx, gy: gy, tx: wx, ty: ty,
          dx: gx * RADAR_TILE + offX,
          dy: gy * RADAR_TILE + offY
        });
      }
    }
    return out;
  }

  var offsets = tileOffsets();

  /* -- load base tiles, then radar frames --------------------------------- */
  var baseP = offsets.map(function (o) {
    return radarLoadImg(baseUrl(o.tx, o.ty)).then(function (img) {
      return { img: img, dx: o.dx, dy: o.dy };
    });
  });

  Promise.all(baseP).then(function (baseImgs) {
    state.baseImgs = baseImgs;
    drawBase();

    return radarLoadMaps();
  }).then(function (maps) {
    if (!maps || !maps.host || !maps.radar) throw new Error('bad maps');
    var host = maps.host;
    var past = maps.radar.past || [];
    var nowcast = maps.radar.nowcast || [];
    var seq = past.concat(nowcast);           // ~13 past + a few nowcast
    if (!seq.length) throw new Error('no frames');

    // Preload every frame's tiles (composite-ready). Each frame's tiles array is
    // built in offset order so draw order is stable across frames.
    var framePromises = seq.map(function (fr) {
      var frame = { time: fr.time, path: fr.path, tiles: new Array(offsets.length) };
      var tp = offsets.map(function (o, oi) {
        return radarLoadImg(radarUrl(host, fr.path, o.tx, o.ty)).then(function (img) {
          frame.tiles[oi] = { img: img, dx: o.dx, dy: o.dy };
        });
      });
      return Promise.all(tp).then(function () { return frame; });
    });

    return Promise.all(framePromises);
  }).then(function (frames) {
    state.frames = frames;
    // Default to the most recent frame overall (latest observation / nowcast).
    state.idx = frames.length - 1;
    drawFrame(state.idx);
    if (status && status.parentNode) status.remove();

    // Wire play/pause.
    function stop() {
      if (state.timer) { clearInterval(state.timer); state.timer = null; }
      btn.textContent = '▶';
      btn.setAttribute('aria-label', 'Play radar animation');
    }
    function start() {
      if (state.timer) return;
      btn.textContent = '⏸';    // pause
      btn.setAttribute('aria-label', 'Pause radar animation');
      state.timer = setInterval(function () {
        state.idx = (state.idx + 1) % state.frames.length;
        drawFrame(state.idx);
      }, RADAR_FRAME_MS);
    }
    btn.addEventListener('click', function () {
      if (state.timer) stop(); else start();
    });

    // Clean up interval if the container is torn out of the DOM.
    if (typeof MutationObserver !== 'undefined') {
      try {
        var mo = new MutationObserver(function () {
          if (!document.body.contains(canvas)) { stop(); mo.disconnect(); }
        });
        mo.observe(document.body, { childList: true, subtree: true });
      } catch (e) {}
    }
  }).catch(function (err) {
    // Any failure past base tiles: keep whatever base we drew, show muted note.
    if (status && status.parentNode) {
      status.className = 'radar-status muted';
      status.textContent = 'radar unavailable';
    } else {
      radarFail(el, 'radar unavailable');
    }
  });
}

/* ---- failure helper ----------------------------------------------------- */
function radarFail(el, msg) {
  try {
    el.innerHTML = '<div class="radar-status muted">' + (msg || 'radar unavailable') + '</div>';
  } catch (e) {}
}