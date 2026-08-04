/* quad-app.js — the two figures on the four-player MWPA site.
 *
 * Front page: the tracker, inside [data-tracker].
 * Match page: the win-probability curve, inside [data-match-figure].
 * Hand-built SVG, no library, no build step, no network. Every page opens off
 * disk and reads its numbers out of window.QUAD, which build.py inlines.
 *
 * WHY THE TRACKER IS THE RUNNING IMPACT PER MATCH.
 * At a player's match i the line is cumulative MWPA / (i + 1) — the headline
 * metric computed on the matches played so far. EACH LINE THEREFORE ENDS ON
 * THAT PLAYER'S HEADLINE NUMBER. The +6.4%, +1.1%, +0.8% and -0.2% the rail
 * at the top of this page prints are literally where the four lines
 * terminate, so the chart and the ranking are one object seen twice — the
 * same relation the match figure below has with its own round ledger.
 *
 * The running SUM this replaced could not be read across players, which is
 * the defect that started this. SN0RLAX climbed to +0.489 over 60 matches and
 * Trzzcko stopped at +0.510 over 8, and the figure invited a reader to
 * compare a long line with a short one when most of the difference between
 * them was the length. A sum rewards volume. The headline metric stopped
 * doing that, so the figure stopped too.
 *
 * The cost is real and is not smoothed away: a mean over one match IS that
 * match, so the left of every line is wild by construction. That is the same
 * fact the intervals carry — all four cover zero — drawn instead of stated.
 * No window, no smoothing, no dropped early points.
 *
 * A rolling MEAN, the other shape considered, would draw form that is not in
 * the data. meta.cav records a per-round MWPA standard deviation of 0.0452 in
 * this act, so a 50-round window carries a standard error near 0.64 per 100
 * rounds — against a spread of 0.76 between the four season rates. The
 * window's own noise is the size of the entire result. Every wiggle would be
 * legible and none of it would mean anything.
 *
 * WHY MARKER SHAPE AND DASH PATTERN, NOT ONLY HUE. Four series need four
 * colours, and four colours do not survive dichromacy: run the palette through
 * contrast.py's simulation and martin/trzzcko separate by 1.15 under
 * deuteranopia, martin/themarias by 1.09 under light-theme protanopia. Amber
 * and cyan hold up because they sit on the blue-yellow axis; violet and pink
 * do not. So each series carries a marker shape and a stroke pattern as well,
 * and every line is labelled at its right end.
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var Q = window.QUAD;
  if (!Q) return;

  /* The four shorts are fixed by the payload contract, so a per-player marker
     is a palette entry rather than a hardcoded count. Anything else falls back
     to a circle in --muted, which is also what the CSS does. */
  var SHAPE = { martin: "circle", snorlax: "square", themarias: "triangle", trzzcko: "diamond" };
  var THEME_KEY = "rwpa-theme";   // shared with the sibling dashboard: one preference, both sites
  var ICONS_KEY = "rwpa-icons";   // this site only: the sibling ships no imagery
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  /* The arrows are gone. Every signed format on this site carries a printed +
     or -, so the glyph was a fourth spelling of a fact the number, the colour
     and the mark's position already carry three times. Same as build.py, which
     keeps zero (a middot) and none (an em dash) because those two say something
     no digit does. */
  var GLYPH = { pos: "", neg: "" };
  var EM = "—";
  var uidN = 0;
  function uid(p) { uidN += 1; return p + "-" + uidN; }

  /* ---- payload -------------------------------------------------------- */
  /* build.py inlines one payload per page and may or may not wrap it, so find
     the block that carries the fields a figure needs rather than assuming a
     nesting. Root first, then one level down. */
  function block(test) {
    var cand = [Q], k;
    for (k in Q) if (Q[k] && typeof Q[k] === "object" && !Array.isArray(Q[k])) cand.push(Q[k]);
    for (var i = 0; i < cand.length; i++) { try { if (test(cand[i])) return cand[i]; } catch (e) {} }
    return null;
  }
  var SITE = block(function (o) { return o && o.tracker && o.matches && o.players; });
  var MATCH = block(function (o) {
    return o && o.rounds && o.teams && (o.wp_series || o.match_wp);
  });
  var PLAYER = block(function (o) { return o && o.rank_track && o.matches && o.headline; });
  var META = block(function (o) { return o && o.dict && o.gate; }) || {};
  /* The fixed bar axes build.py derives once from the act's own distribution
     and inlines on every page. Read here, never recomputed — house rule 3. */
  var SCALE = (Q && Q.scale) || (SITE && SITE.scale) || {};

  /* ---- numbers -------------------------------------------------------- */
  /* Formats come from meta.dict. The fallback exists because the dict does not
     name every field a figure prints; it never overrides one that is present.
     EVERY PROBABILITY ON THIS SITE PRINTS TO ONE DECIMAL — 97.6%, never 98% —
     so PCT and MOVE are the two fallbacks, and a dict entry for `p`, `q` or
     `dp` takes over the moment the payload grows one. */
  var PCT = ".1%";          // a probability level
  var MOVE = "+.1%";        // a move in probability, in points, signed
  var LI = ".2f";           // the leverage index, matching build.py's own fallback

  function spec(key) { return (META.dict && META.dict[key]) || null; }
  function label(key, fallback) { var s = spec(key); return (s && s.label) || fallback || key; }

  function num(v, format) {
    var m = /^([+]?)\.(\d+)([f%])$/.exec(format || "");
    if (v === null || v === undefined || v !== v) return EM;
    if (!m) return String(v);
    var dp = Number(m[2]);
    var x = m[3] === "%" ? v * 100 : v;
    var r = Number(x.toFixed(dp));            // sign of what is printed, not of the input
    /* Zero is neither: a `+` in front of a value that printed as zero would
       claim a direction the number does not have. */
    var sign = r < 0 ? "-" : (m[1] && r > 0) ? "+" : "";
    return sign + Math.abs(r).toFixed(dp) + (m[3] === "%" ? "%" : "");
  }
  function val(key, v, fallback) { return num(v, (spec(key) && spec(key).format) || fallback); }
  function sgn(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "zero"; }
  /* Sign, three ways: the + or - the format spec prints, the colour class from
     sgn(), and the mark's own position against the 50% rule. GLYPH.pos and
     GLYPH.neg are empty, so this returns "" for every value; it stays because
     move() is the one place a glyph would go back in. */
  function glyph(v) { return v > 0 ? GLYPH.pos : v < 0 ? GLYPH.neg : ""; }
  function move(key, v, fallback) {
    var g = glyph(v);
    return (g ? g + " " : "") + val(key, v, fallback);
  }

  function day(iso) {
    var d = new Date(iso);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()];
  }
  function fullDay(iso) {
    var d = new Date(iso);
    return day(iso) + " " + d.getUTCFullYear();
  }
  function secs(ms) { return (ms / 1000).toFixed(1) + "s"; }

  /* ---- dom ------------------------------------------------------------ */
  function el(tag, cls, parent, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function sv(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag), k;
    for (k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(x, y, s, cls, parent, anchor) {
    var n = sv("text", { x: x, y: y, "text-anchor": anchor || "start", class: cls }, parent);
    n.textContent = s;
    return n;
  }

  /* ---- scales --------------------------------------------------------- */
  function ticks(lo, hi, want) {
    var span = (hi - lo) || 1;
    var raw = span / Math.max(1, want);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var n = raw / mag;
    var step = (n >= 5 ? 10 : n >= 2 ? 5 : n >= 1 ? 2 : 1) * mag;
    var out = [], t = Math.ceil(lo / step) * step;
    for (; t <= hi + step * 1e-9; t += step) out.push(Math.abs(t) < step * 1e-9 ? 0 : t);
    return out;
  }

  function markerPath(shape, x, y, r) {
    if (shape === "square") return "M" + (x - r * .9) + " " + (y - r * .9) + "h" + (r * 1.8) + "v" + (r * 1.8) + "h" + (-r * 1.8) + "Z";
    if (shape === "triangle") return "M" + x + " " + (y - r * 1.2) + "L" + (x + r * 1.15) + " " + (y + r * .82) + "L" + (x - r * 1.15) + " " + (y + r * .82) + "Z";
    if (shape === "diamond") return "M" + x + " " + (y - r * 1.3) + "L" + (x + r * 1.15) + " " + y + "L" + x + " " + (y + r * 1.3) + "L" + (x - r * 1.15) + " " + y + "Z";
    return "M" + (x - r) + " " + y + "a" + r + " " + r + " 0 1 0 " + (r * 2) + " 0a" + r + " " + r + " 0 1 0 " + (-r * 2) + " 0";
  }

  /* A datum that is off the axis, drawn as a filled chevron at the edge with
     its apex pointing the way the value went. `dir` is +1 for a body hanging
     below a top edge, -1 for one standing on a bottom edge. It is deliberately
     not any of the four series marker shapes: a clamped value drawn as a
     normal mark sitting on the boundary reads as a match that stopped there,
     which is the one thing it must not say. */
  function caretPath(x, y, r, dir) {
    var base = y + dir * r * 1.35, notch = y + dir * r * 0.62;
    return "M" + (x - r) + " " + base + "L" + x + " " + y + "L" + (x + r) + " " + base
      + "L" + x + " " + notch + "Z";
  }

  /* ---- theme ---------------------------------------------------------- */
  /* Same attribute and same storage key as the sibling dashboard, so the two
     sites are one preference. Every colour in both figures comes from a CSS
     custom property, so switching themes repaints without a redraw. */
  function initTheme() {
    var root = document.documentElement;
    if (!root.getAttribute("data-theme")) {
      var t = null;
      try { t = localStorage.getItem(THEME_KEY); } catch (e) {}
      if (!t) t = (window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
      root.setAttribute("data-theme", t);
    }
    var btn = document.querySelector("[data-theme-toggle], .theme-toggle");
    if (!btn) return;
    function paint() {
      var dark = root.getAttribute("data-theme") !== "light";
      btn.textContent = dark ? "◐ light" : "◑ dark";
      btn.setAttribute("aria-label", dark ? "Switch to the light theme" : "Switch to the dark theme");
    }
    paint();
    btn.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      paint();
    });
  }

  /* ---- the identity control ------------------------------------------- */
  /* The same mechanism as the theme toggle — one attribute on the root, one
     storage key — and the whole defence of the imagery on this site. Flip it
     and not one fact leaves the page, because every picture sits beside the
     word it illustrates and none of them carries a measurement. An image that
     survives this switch being thrown is doing identification work; an image
     that would leave a hole was carrying meaning it should never have had.

     THREE FAMILIES NOW, one switch. Agent portraits, division badges and weapon
     silhouettes are all hidden by the same attribute, including the badges that
     live inside the trajectory figure as an SVG <image> — quad-site.css lists
     every family by class, so a family that is NOT listed is a family that
     survives the switch, which is exactly the bug this control exists to catch.
     The label says "icons" and not "agent icons" for the same reason.

     It hides rather than unloads, so it is a reader control and not a data
     saver, and the memo says so rather than implying otherwise. */
  function initIcons() {
    var root = document.documentElement;
    if (!root.getAttribute("data-icons")) root.setAttribute("data-icons", "on");
    var btn = document.querySelector("[data-icons-toggle]");
    if (!btn) return;
    function paint() {
      var on = root.getAttribute("data-icons") !== "off";
      btn.textContent = on ? "icons on" : "icons off";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.setAttribute("aria-label",
        on ? "Hide the agent, division and weapon artwork"
           : "Show the agent, division and weapon artwork");
    }
    paint();
    btn.addEventListener("click", function () {
      var next = root.getAttribute("data-icons") === "off" ? "on" : "off";
      root.setAttribute("data-icons", next);
      try { localStorage.setItem(ICONS_KEY, next); } catch (e) {}
      paint();
    });
  }

  /* ---- the rank trajectory --------------------------------------------- */
  /* build.py emits the whole figure as SVG, so this adds a crosshair and a
     readout to an object that is already complete and already legible with no
     script at all. It reads the geometry off the marks themselves rather than
     off a second copy of the numbers: one source, and no way for the two to
     disagree about which match is under the cursor. */
  function wireTrack(fig) {
    var player = PLAYER;
    var svg = fig.querySelector("[data-track-fig]");
    var cross = fig.querySelector("[data-track-cross]");
    var out = fig.querySelector("[data-track-readout]");
    if (!player || !player.rank_track || !svg || !cross || !out) return;
    var hits = [].slice.call(svg.querySelectorAll("[data-track-hit]"));
    if (!hits.length) return;
    var byMatch = {};
    player.matches.forEach(function (row) { byMatch[row.match_id] = row; });
    var opening = out.innerHTML;   /* build.py opened it on the demotion; that is the rest state */

    /* WHERE THE REST STATE IS, read off the crosshair build.py already drew.
       The controller has to start where the line is. Starting it at -1 meant
       the first arrow key stepped from nowhere: on a page whose crosshair sat
       visibly on match 27, one press of Right moved the reader to match 1 and
       moved the line with it — a step of twenty-six matches, drawn as if it
       were one. The index is recovered from the mark's own geometry rather
       than from a second copy of the number, so the two cannot disagree. */
    function centre(i) {
      return parseFloat(hits[i].getAttribute("x"))
           + parseFloat(hits[i].getAttribute("width")) / 2;
    }
    var restAt = 0, restX = parseFloat(cross.getAttribute("x1")), gap = Infinity, hi;
    for (hi = 0; hi < hits.length; hi++) {
      if (Math.abs(centre(hi) - restX) < gap) { gap = Math.abs(centre(hi) - restX); restAt = hi; }
    }
    var at = restAt;

    function span(before, value, after) {
      return "<span>" + before + "<b>" + value + "</b>" + after + "</span>";
    }

    function show(i) {
      var step = player.rank_track[i], row = step && byMatch[step.match_id];
      if (!row) return;
      at = i;
      var x = centre(i);
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      out.innerHTML = [
        span(label("match_id", "match").toLowerCase() + " ", i + 1,
             " of " + player.rank_track.length),
        /* The ISO date, not the tracker's "14 Jul": build.py renders this same
           line into the same element on the server, and a value that changes
           format the moment a key is pressed reads as a different value. */
        span("", row.started_at.slice(0, 10) + " · " + row.map,
             " · " + (row.won ? "won" : "lost")),
        /* Never the platform's queue name and never an em dash: the em dash on
           this site means NOT MEASURED, and this is measured. */
        span(label("tier", "division").toLowerCase() + " ",
             step.tier || (step.state + ", no rank issued"), ""),
        span(label("mwpa", "MWPA") + " ", val("mwpa", row.mwpa), "")
      ].join("");
    }

    hits.forEach(function (rect, i) {
      rect.addEventListener("pointerenter", function () { show(i); });
    });
    /* The pointer leaving restores the WHOLE rest state, line included. It used
       to restore only the sentence, which left the crosshair standing on the
       match the pointer happened to exit over while the readout underneath it
       named a different one — the figure's two halves reading two matches. */
    svg.addEventListener("pointerleave", function () {
      at = restAt;
      cross.setAttribute("x1", restX);
      cross.setAttribute("x2", restX);
      out.innerHTML = opening;
    });
    svg.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { show(Math.min(hits.length - 1, at + 1)); e.preventDefault(); }
      if (e.key === "ArrowLeft") { show(Math.max(0, at - 1)); e.preventDefault(); }
    });
  }

  /* ==== the tracker ===================================================== */
  /* One mark per match per player at that match's own MWPA, one staircase per
     player at the running impact per match, on a shared x axis of every match
     in the act in the order they were played. The shared axis is the point: a
     per-player ordinal would stretch eight matches across the same width as
     sixty and make a single evening look like a season.

     THE MARK AND THE LINE ARE THE SAME QUANTITY AT DIFFERENT n. One match's
     MWPA is that player's impact per match measured on one match, so the two
     share one y axis honestly and the mark is the raw datum under the mean.

     Both take their format and the axis its title from meta.dict's `impact`
     entry, which is a percentage — the axis is no longer in raw points. */
  function drawTracker(host) {
    if (!SITE) return;
    var matches = SITE.matches, N = matches.length;
    if (!N) return;
    var order = {}, i;
    for (i = 0; i < N; i++) order[matches[i].match_id] = i;

    var series = [];
    SITE.players.forEach(function (p) {
      var rows = (SITE.tracker[p.short] || []).map(function (r) {
        /* `m` is the headline metric on the matches played so far: MWPA
           divided by matches. r.i is the player's own zero-based match
           ordinal, so the last row of every series is site.players[].impact
           exactly — verified at +6.371%, +1.090%, +0.814%, -0.184%, which is
           the +6.4%, +1.1%, +0.8%, -0.2% the rail above prints. */
        return { x: order[r.match_id], r: r, m: r.cumulative / (r.i + 1) };
      }).filter(function (d) { return d.x !== undefined; });
      if (rows.length) series.push({ p: p, rows: rows, shape: SHAPE[p.short] || "circle" });
    });
    if (!series.length) return;

    host.textContent = "";
    host.classList.add("fig", "fig-tracker");

    /* THE Y AXIS IS scale.impact, the payload's fixed headline axis — the same
       0.2331 build.py lays the front-page rail on, so the rail's x and this
       figure's y are one ruler and either can be laid over the other. House
       rule 3: read, never recomputed.

       Fitting the box to the marks instead was the alternative and one datum
       kills it. A single match at -70.7% would set the domain, the four lines
       would live inside the middle quarter of it, and ticks() would put their
       nearest gridline at -50% — an axis on which three of the four seasons
       are the same pixel. The axis is WIDENED if a running mean would ever
       leave the box and never narrowed, so a line cannot clip. */
    var AX = (typeof SCALE.impact === "number" && SCALE.impact > 0) ? SCALE.impact : 0;
    var lo = -AX, hi = AX, pad;
    series.forEach(function (s) {
      s.rows.forEach(function (d) { lo = Math.min(lo, d.m); hi = Math.max(hi, d.m); });
    });
    if (!AX) {
      /* No payload axis. Fall back to the marks, which is the only thing left
         to measure against, rather than inventing a number here. */
      series.forEach(function (s) {
        s.rows.forEach(function (d) { lo = Math.min(lo, d.r.mwpa); hi = Math.max(hi, d.r.mwpa); });
      });
      pad = (hi - lo) * 0.08 || 0.1;
      lo -= pad; hi += pad;
    }
    /* 19 of 108 single-match values sit outside that axis: the raw datum is
       four times as wide as any season mean, which is the finding and not a
       rendering fault. Those are drawn as carets at the edge and counted in
       the description, and every one of them keeps its exact value in the
       readout and a row in the match index below. */
    var clamped = 0;
    series.forEach(function (s) {
      s.rows.forEach(function (d) { if (d.r.mwpa > hi || d.r.mwpa < lo) clamped += 1; });
    });

    var W = 960, H = 424, ML = 46, MR = 138, MT = 22, MB = 46;
    var PW = W - ML - MR, PH = H - MT - MB;
    function X(i) { return ML + (N > 1 ? i * PW / (N - 1) : PW / 2); }
    function Y(v) { return MT + PH - (v - lo) / (hi - lo) * PH; }

    /* legend first: it is a real control strip, and it explains the marks
       before the reader meets them */
    var legend = el("div", "fig-legend", host);
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "Series, and a button to isolate each one");

    var scroll = el("div", "fig-scroll", host);
    /* A figure that scrolls sideways and cannot be reached by keyboard hides
       half a season from anyone not using a mouse. Same treatment the tables
       already had. */
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "The season, match by match — scrolls sideways");
    var svg = sv("svg", {
      class: "tracker", viewBox: "0 0 " + W + " " + H,
      preserveAspectRatio: "xMidYMid meet", role: "img"
    }, scroll);
    var tId = uid("t"), dId = uid("d");
    svg.setAttribute("aria-labelledby", tId + " " + dId);
    var ttl = sv("title", { id: tId }, svg);
    var dsc = sv("desc", { id: dId }, svg);
    ttl.textContent = label("impact", "Impact per match") + " by player, recomputed after every "
      + "match they played, across every match"
      + (META.act ? " of act " + String(META.act).toUpperCase() : "") + " in the order they were played.";
    dsc.textContent = series.map(function (s) {
      var last = s.rows[s.rows.length - 1];
      return s.p.name + ": " + val("impact", last.m, MOVE) + " "
        + ((spec("impact") && spec("impact").unit) || "per match")
        + " over " + s.rows.length + " matches, first on " + fullDay(s.rows[0].r.started_at)
        + ", last on " + fullDay(last.r.started_at) + ".";
    }).join(" ") + " Each line ends on that player's headline number. Each match's own "
      + label("mwpa", "MWPA") + " is a mark on the same axis"
      + (clamped ? ", and " + clamped + " of those fall outside it and are drawn as carets at its edge" : "")
      + ". The same matches are listed under the figure with a link to each.";

    /* grid, zero rule, axes */
    var g = sv("g", { class: "grid" }, svg);
    ticks(lo, hi, 6).forEach(function (t) {
      var y = Y(t);
      sv("line", { class: t === 0 ? "axis-zero" : "gridline", x1: ML, x2: ML + PW, y1: y, y2: y }, g);
      text(ML - 8, y + 3.5, val("impact", t, MOVE), "tick", g, "end");
    });
    /* One scale carries the marks and the lines, so the axis is named by the
       unit rather than by either. It is the impact unit now, not raw points. */
    text(ML, MT - 8, (spec("impact") && spec("impact").unit) || "impact per match",
         "axis-title", g, "start");

    var xg = sv("g", { class: "grid" }, svg);
    var stepX = Math.max(1, Math.round(N / 6));
    for (i = 0; i < N; i += stepX) {
      text(X(i), MT + PH + 18, day(matches[i].started_at), "tick", xg, "middle");
    }
    sv("line", { class: "axis", x1: ML, x2: ML + PW, y1: MT + PH, y2: MT + PH }, xg);
    text(ML, MT + PH + 36, matches.length + " matches, oldest first", "axis-title", xg, "start");

    /* one group per player: staircase, then dots on top of it */
    var ends = [];
    series.forEach(function (s) {
      var gp = sv("g", { class: "series p-" + s.p.short }, svg);
      /* The line STARTS at the first match's own value and not at zero. A mean
         over no matches does not exist, and nothing unmeasured is drawn as a
         value on this site. At i = 0 the line and the mark are the same point,
         which is the cheapest available statement of what one match is worth.
         Between a player's matches the mean does not move, so the step is flat
         to the next match and vertical at it. The class stays `cum` because
         quad-site.css owns the name. */
      var d = "M" + X(s.rows[0].x) + " " + Y(s.rows[0].m);
      s.rows.forEach(function (row, k) {
        if (!k) return;
        d += "L" + X(row.x) + " " + Y(s.rows[k - 1].m) + "L" + X(row.x) + " " + Y(row.m);
      });
      sv("path", { class: "cum", d: d }, gp);

      /* The dots are the data and they stay. What went is the 99 individual
         12px hit circles that used to sit on top of them: 87 of 99 had a
         neighbour inside 24px, every one was tabindex="-1", and the whole set
         was a mouse-only affordance pretending to be a control. One nearest-
         index crosshair band replaces them — the same layer the match figure
         already has — and every match stays addressable as a real link in the
         list under the figure and in the index below it. */
      var dots = sv("g", { class: "dots" }, gp);
      s.rows.forEach(function (row) {
        var v = row.r.mwpa, dd;
        if (v > hi) dd = caretPath(X(row.x), MT + 3, 4.2, 1);
        else if (v < lo) dd = caretPath(X(row.x), MT + PH - 3, 4.2, -1);
        else dd = markerPath(s.shape, X(row.x), Y(v), 3.2);
        sv("path", { class: "dot", d: dd }, dots);
      });

      var last = s.rows[s.rows.length - 1];
      ends.push({ s: s, x: X(last.x), y: Y(last.m), v: last.m });
    });

    /* end labels, pushed apart rather than overlapped, then lifted back inside
       the box if four players finished within thirty pixels of each other */
    ends.sort(function (a, b) { return a.y - b.y; });
    for (i = 1; i < ends.length; i++) {
      if (ends[i].y - ends[i - 1].y < 30) ends[i].y = ends[i - 1].y + 30;
    }
    var spill = ends.length ? ends[ends.length - 1].y - (H - 16) : 0;
    if (spill > 0) ends.forEach(function (e) { e.y -= Math.min(spill, ends[0].y - MT); });
    ends.forEach(function (e) {
      var ge = sv("g", { class: "series end p-" + e.s.p.short }, svg);
      sv("line", { class: "leader", x1: e.x + 5, x2: ML + PW + 14, y1: Y(e.v), y2: e.y }, ge);
      text(ML + PW + 20, e.y - 1, e.s.p.name.split("#")[0], "end-name", ge);
      text(ML + PW + 20, e.y + 13, val("impact", e.v, MOVE), "end-val " + sgn(e.v), ge);
    });

    /* ---- one crosshair, every live series ------------------------------ */
    var gCross = sv("g", { class: "cross", visibility: "hidden" }, svg);
    var band = sv("rect", { class: "band", y: MT, height: PH, width: Math.max(PW / N, 6) }, gCross);
    var crossV = sv("line", { class: "cross-v", y1: MT, y2: MT + PH }, gCross);
    svg.setAttribute("tabindex", "0");

    var readout = el("p", "fig-readout", host);
    readout.setAttribute("role", "status");
    readout.setAttribute("aria-live", "polite");

    function rest() {
      gCross.setAttribute("visibility", "hidden");
      /* The one sentence the noisy left edge gets. It is a property of a mean,
         not a caveat about the data, so it is stated once and not repeated. */
      readout.textContent = label("impact", "Impact per match") + " as a line, ending on that "
        + "player's headline number; each match's own " + label("mwpa", "MWPA") + " as a mark. "
        + "One match in, the line is that match. "
        + "Point anywhere for every player in that match.";
    }
    function say(i) {
      var m = matches[i];
      if (!m) return;
      gCross.setAttribute("visibility", "visible");
      band.setAttribute("x", X(i) - Math.max(PW / N, 6) / 2);
      crossV.setAttribute("x1", X(i));
      crossV.setAttribute("x2", X(i));
      readout.textContent = "";
      el("b", null, readout, m.map + " · " + day(m.started_at));
      var any = false;
      series.forEach(function (s) {
        var hit = null;
        s.rows.forEach(function (row) { if (row.x === i) hit = row; });
        if (!hit) return;
        any = true;
        el("span", null, readout, " · ");
        el("span", "hue p-" + s.p.short, readout, s.p.name.split("#")[0] + " ");
        el("span", sgn(hit.r.mwpa), readout, val("mwpa", hit.r.mwpa));
        /* The mark's exact value is printed here whether or not it fitted on
           the axis, so a caret at the edge never costs the reader the number.
           The mean beside it is the line's height at this match, and the count
           is what makes the two comparable across players. */
        el("span", null, readout, " (" + val("impact", hit.m, MOVE) + " over "
          + (hit.r.i + 1) + (hit.r.i ? " matches)" : " match)"));
      });
      if (!any) el("span", "na", readout, " · " + EM + " none of the four played this match");
    }
    var atX = -1;
    function point(evt) {
      var box = svg.getBoundingClientRect();
      var scale = box.width / W || 1;
      var vx = (evt.clientX - box.left) / scale;
      var i = N > 1 ? Math.round((vx - ML) / (PW / (N - 1))) : 0;
      i = Math.max(0, Math.min(N - 1, i));
      if (i !== atX) { atX = i; say(i); }
    }
    svg.addEventListener("pointermove", point);
    svg.addEventListener("pointerleave", function () { atX = -1; rest(); });
    svg.addEventListener("focus", function () { if (atX < 0) { atX = N - 1; say(atX); } });
    svg.addEventListener("blur", function () { atX = -1; rest(); });
    svg.addEventListener("keydown", function (evt) {
      var d = evt.key === "ArrowRight" ? 1 : evt.key === "ArrowLeft" ? -1
        : evt.key === "Home" ? -N : evt.key === "End" ? N : 0;
      if (!d) return;
      evt.preventDefault();
      atX = Math.max(0, Math.min(N - 1, (atX < 0 ? 0 : atX) + d));
      say(atX);
    });
    rest();

    /* the legend buttons isolate a series. With four staircases and every
       match of the act on one axis they are the only way to follow one
       player, so they are real buttons and not a colour key. */
    series.forEach(function (s) {
      var b = el("button", "legend-key p-" + s.p.short, legend);
      b.type = "button";
      b.setAttribute("aria-pressed", "false");
      var sw = sv("svg", { class: "swatch", viewBox: "0 0 26 14", "aria-hidden": "true" }, null);
      b.appendChild(sw);
      sv("line", { class: "cum", x1: 1, x2: 25, y1: 7, y2: 7 }, sw);
      sv("path", { class: "dot", d: markerPath(s.shape, 13, 7, 3.6) }, sw);
      el("span", "who", b, s.p.name.split("#")[0]);
      /* The exposure and the headline number, which is where this key's line
         ends. The season total used to sit here and it was the one number on
         the figure that still ranked on volume. */
      var last = s.rows[s.rows.length - 1];
      el("span", "exposure", b, s.rows.length + " matches · " + val("impact", last.m, MOVE));
      b.addEventListener("click", function () {
        var on = host.getAttribute("data-only") === s.p.short;
        host.setAttribute("data-only", on ? "" : s.p.short);
        Array.prototype.forEach.call(legend.children, function (o) {
          o.setAttribute("aria-pressed", String(!on && o === b));
        });
      });
    });

    /* THE ONE THING REMOVED IN THE LAST PASS.
       This used to end with a <details> holding all ninety-nine matches as
       links, four <h3> blocks deep, because the SVG's dots were a mouse-only
       affordance and something had to carry the keyboard and the reader who
       wants a list. Both jobs now have better owners on the same page: the
       crosshair reads every live series aloud through an aria-live readout,
       and the sortable match index directly below is the same data as one
       table, in any order the reader asks for, with the whole row as the link.
       A second, worse index of exactly the same matches, three hundred pixels
       above the good one, was the last thing on this page that existed only
       because it used to be needed. */
  }

  /* ==== the match figure ================================================ */
  /* ONE CONTINUOUS MATCH WIN PROBABILITY CURVE, and the reason it is one line
     rather than the two stacked panels this replaced.
     ---------------------------------------------------------------------
     `wp_series` conditions on how the current round ends. With the score at
     (a, b) and the focal side holding round-win probability q:

         P(match) = W(a, b+1) + q · L(a, b)

     so the round model the ledger already produces is affinely mapped onto the
     match by that round's own leverage. Two consequences drive every choice
     below, and the payload's docstring records them as measured, not assumed:

       dP/dq == L to 3.6e-11. THE SLOPE OF THIS LINE IS THE LEVERAGE, so an
       action node's `dp` IS that event's raw match impact in match win
       probability points. A kill that moves the line 3.4 points moved the
       match 3.4 points. The chart and the metric are one object seen twice.

       Each round's terminal node equals the next round's wp_before exactly
       (0.0e+00), so nothing is stitched and no boundary is approximated.

     FOUR NODE KINDS ARE FOUR DIFFERENT CLAIMS AND ARE DRAWN AS FOUR THINGS.

       round_start  the buy, priced before anyone acts. Round-start q has an
                    sd of 0.153 across the act, so an eco round opens with the
                    match already leaning away — a real move, usually the
                    largest one nobody made. Attributable to the ECONOMY and
                    never to a player, so it is a dashed vertical at the round
                    boundary and it never gets an event marker.
       clock        drift between credited actions, the alive-clock component.
                    Plain sloped line.
       action       a kill, plant or defuse. The marker, sized by |dp|.
       terminal     the round resolves. The gap from the last action to here is
                    the model's calibration error at the terminal, which the
                    ledger books to a team side rather than to a player. Drawn
                    dashed like the economy move, and never smoothed away.

     WHY THE INTERPOLATION IS LINEAR AND NOT A CURVE. An action node shares its
     `t` with the clock node before it, so the segment between them is exactly
     vertical and a straight join is already the honest step/linear hybrid:
     clock segments slope, actions jump. This is the one place the reference
     component's default is wrong for this data — curveNatural would round the
     corners off the exact jump the chart exists to show, and would overshoot
     past 0 and 1 on a bounded axis besides. Do not "smooth" it. */
  function drawMatchFigure(host) {
    if (!MATCH) return;
    var rounds = MATCH.rounds;
    if (!rounds || !rounds.length) return;

    var focal = null, other = null;
    MATCH.teams.forEach(function (t) { if (t.focal) focal = t; else other = t; });
    if (!focal) { focal = MATCH.teams[0]; other = MATCH.teams[1] || null; }

    var byPuuid = {}, roundBy = {}, sideBy = {}, nodesBy = {};
    (MATCH.players || []).forEach(function (p) { byPuuid[p.puuid] = p; });
    rounds.forEach(function (r) {
      roundBy[r.round_number] = r;
      nodesBy[r.round_number] = [];
      /* Which side the focal team played in this round is in the payload's own
         buy block, so the half switch below is read rather than assumed at 12
         — which is also what makes it right in overtime. */
      (r.buy || []).forEach(function (b) {
        if (b.team_id === focal.team_id) sideBy[r.round_number] = b.side;
      });
    });

    var R = rounds.length;
    var series = (MATCH.wp_series || []).filter(function (n) { return nodesBy[n.r]; });
    series.forEach(function (n) { nodesBy[n.r].push(n); });

    var chart = null, tabs = null, selected = null;

    function showPanel(n) {
      var panels = document.querySelectorAll("[data-round-panel]");
      if (!panels.length) return;
      document.documentElement.classList.add("js-tabs");
      Array.prototype.forEach.call(panels, function (p) {
        var on = String(p.getAttribute("data-round-panel")) === String(n);
        p.classList.toggle("is-on", on);
        p.setAttribute("aria-hidden", on ? "false" : "true");
      });
    }

    /* The round ledger below the figure is another agent's markup and has its
       own controller, so the figure announces which round it is on and does not
       reach into it. showPanel stays as the fallback for a page whose
       controller never ran; both do the same thing and neither fights. */
    function publish(n) {
      if (typeof CustomEvent !== "function") return;
      document.dispatchEvent(new CustomEvent("quad:round", { detail: { round_number: n } }));
    }

    function select(n, fromFigure) {
      if (!roundBy[n]) return;
      selected = n;
      if (tabs) { tabs.mark(n); if (fromFigure) tabs.reveal(n); }
      if (chart) chart.select(n);
      showPanel(n);
      publish(n);
      /* The anchor form the round index already uses, so a copied URL lands on
         the same round the figure is showing. replaceState never fires
         hashchange, so the page's own controller is not re-entered. */
      try { history.replaceState(null, "", "#round-" + n); } catch (e) {}
    }

    /* Both spellings, because the round index links `#round-7` and an older
       page linked `#r7`, and an inbound link that this misses would collapse
       the panels onto a round the reader did not ask for. */
    function opening() {
      var start = /^#(?:round-|r)(\d+)$/.exec(location.hash || "");
      return start && roundBy[Number(start[1])] ? Number(start[1]) : rounds[0].round_number;
    }

    /* Without wp_series there is no curve to draw and nothing honest to put in
       its place, so the container keeps the sentence build.py wrote into it and
       the round tabs are wired anyway — otherwise showPanel would collapse the
       panels with no control left to reopen them. */
    if (!series.length) {
      tabs = wireTabs(host, rounds, function (n) { select(n, false); });
      select(opening(), true);
      return;
    }

    host.textContent = "";
    host.classList.add("fig", "fig-match");

    /* ---- the header, in the ESPN layout -------------------------------- */
    /* Both teams named with their live percentage, at one decimal, updating on
       hover and showing the final at rest. It is HTML rather than SVG text so
       the numbers scale with the reader's font size and take the page's
       contrast tokens rather than a fill. */
    var head = el("div", "wp-head", host);
    var headTop = el("div", "wp-head-top", head);
    el("span", "lab", headTop, label("p", "Match win probability"));
    var headWhen = el("span", "wp-when", headTop, "");
    var teamRows = el("div", "wp-teams", head);

    function teamRow(team, cls) {
      /* No swatch. There is nothing left for it to stand for: the two area
         fills it keyed are gone, and one neutral wash needs no legend. */
      var row = el("div", "wp-team " + cls, teamRows);
      el("span", "wp-name", row, team ? team.team_id : EM);
      el("span", "wp-score", row, team ? String(team.rounds_won) : EM);
      var pct = el("b", "wp-pct", row, "");
      return pct;
    }
    var focalPct = teamRow(focal, "is-focal");
    var otherPct = teamRow(other, "is-other");

    /* ---- geometry ------------------------------------------------------ */
    /* The reference component's defaults: margin 40 all round, 2/1 aspect.
       The viewBox is taller than the plot box by BELOW, because the bottom
       margin is fully spent by the tick row and the axis title sits under it at
       BOT + 44 -- outside a 480-tall box, where `overflow: hidden` on .wpfig
       clipped it. The plot keeps the reference geometry exactly (880 x 400 at
       margin 40); only the room for the furniture beneath it is bought. */
    var W = 960, H = 480, M = 40, BELOW = 18;
    var PW = W - M * 2, PH = H - M * 2;
    var VH = H + BELOW;
    /* The null comes from meta.gate, not from this file. Nothing in the view
       decides the value that means "no claim". */
    var TOP = M, BOT = M + PH;
    var EVEN = (META.gate && typeof META.gate.null_probability === "number")
      ? META.gate.null_probability : 0.5;
    /* x is the payload's own continuous x: integers are round boundaries, so
       every round is the same width and events sit inside it by time. */
    function X(x) { return M + (x / R) * PW; }
    function Y(p) { return BOT - p * PH; }          // fixed 0..1 domain, never data-fitted

    /* WHICH OF THE FOUR ACTUALLY ACTED HERE. One list, read once, and both the
       coloured verticals below and the legend keys above them are keyed off it,
       so the legend cannot name a hue the chart does not draw. Payload order,
       which is time order, so the key list reads in the order the reader met
       the players on the line. */
    var actShorts = [], actWho = {}, actN = {};
    series.forEach(function (n) {
      if (n.kind !== "action") return;
      var p = byPuuid[n.actor];
      if (!p || !p.short) return;
      if (!actWho[p.short]) { actWho[p.short] = p; actN[p.short] = 0; actShorts.push(p.short); }
      actN[p.short] += 1;
    });

    /* ---- what each segment on the line means --------------------------- */
    /* Static keys, not the tracker's isolate buttons: there is nothing to
       toggle here, so nothing takes a button's affordance. Each swatch is drawn
       by the same class as the path it stands for, so the legend cannot drift
       away from the chart — restyle the line and the key follows. */
    var legend = el("div", "fig-legend is-static", host);
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "What each segment on the line means, and who moved it");
    [["wp-line", label("kind_action", "Action") + " and " + label("kind_clock", "clock").toLowerCase(),
      "a player's"],
     ["wp-econ", label("kind_round_start", "Round start"), "the economy"],
     ["wp-term", label("kind_terminal", "Terminal"), "the model's gap"]].forEach(function (key) {
      var item = el("span", "legend-key is-static", legend);
      var sw = sv("svg", { class: "swatch wpfig", viewBox: "0 0 26 14", "aria-hidden": "true" }, item);
      sv("path", { class: key[0] + (key[0] === "wp-line" ? "" : " wp-free"),
                   d: "M1 7h24" }, sw);
      el("span", "who", item, key[1]);
      el("span", "exposure", item, key[2]);
    });
    /* One key per focal player who acted, because the vertical at their actions
       is drawn in their hue and a colour nobody names is decoration. The swatch
       is a vertical stroke and not a rule, because a vertical is the only thing
       the hue paints. Static like the three above it — nothing here toggles. */
    actShorts.forEach(function (s) {
      var item = el("span", "legend-key is-static p-" + s, legend);
      var sw = sv("svg", { class: "swatch wpfig", viewBox: "0 0 26 14", "aria-hidden": "true" }, item);
      sv("path", { class: "wp-line wp-act p-" + s, d: "M13 1v12" }, sw);
      el("span", "who", item, String(actWho[s].name || s).split("#")[0]);
      el("span", "exposure", item, actN[s] + (actN[s] === 1 ? " action" : " actions"));
    });

    var plot = el("div", "wp-plot", host);
    var scroll = el("div", "fig-scroll", plot);
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "The win probability curve — scrolls sideways");
    var svg = sv("svg", {
      class: "wpfig", viewBox: "0 0 " + W + " " + VH,
      preserveAspectRatio: "xMidYMid meet", role: "img", tabindex: "0"
    }, scroll);
    var tId = uid("t"), dId = uid("d");
    svg.setAttribute("aria-labelledby", tId + " " + dId);
    var ttl = sv("title", { id: tId }, svg);
    var dsc = sv("desc", { id: dId }, svg);

    /* ---- grid: horizontal only, five rows ------------------------------ */
    var gGrid = sv("g", { class: "grid" }, svg);
    var rows = 5, gi;
    for (gi = 0; gi < rows; gi++) {
      var p = gi / (rows - 1);
      var gy = Y(p);
      /* The null is NOT drawn here. It is the heaviest horizontal on the
         figure and it is drawn after the wash and before the curve — see
         below. Drawn last, as a rule that heavy, it would erase the data it
         is judging at exactly the moment the match was closest to even. */
      if (p === EVEN) continue;
      sv("line", { class: "gridline", x1: M, x2: M + PW, y1: gy, y2: gy }, gGrid);
      /* Inside the plot, above the line: "100.0%" at one decimal does not fit
         in a 40px margin, and the margin is the reference component's. */
      text(M + 3, gy - 4, num(p, PCT), "tick", gGrid, "start");
    }

    /* ---- round boundaries and the side switch -------------------------- */
    /* 7px ticks at the axis, not 24 to 32 full-height rules. Every round is
       drawn to equal width, so the boundaries ARE the x axis and they have to
       be there — but at full height, at the 3:1 they need to be legible, they
       turned the plot into a barcode drawn over its own data. */
    var gBound = sv("g", { class: "bounds" }, svg);
    var stepR = Math.max(1, Math.round(R / 12));
    var k;
    for (k = 0; k <= R; k++) {
      sv("line", { class: "bound", x1: X(k), x2: X(k), y1: BOT, y2: BOT + 7 }, gBound);
    }
    rounds.forEach(function (r, i) {
      if (i % stepR === 0 || i === R - 1) {
        text((X(i) + X(i + 1)) / 2, BOT + 20, String(r.round_number), "tick", gBound, "middle");
      }
    });
    /* Marked more strongly than a round boundary because the sides swap here,
       which is the one boundary the reader cannot infer from the line. Every
       switch gets a rule; the LABEL is dropped when the last one is closer than
       its own width, because overtime swaps every round and four labels on top
       of each other say less than one. The count below the axis is what keeps
       the unlabelled ones from going unsaid. */
    /* One full-height rule for the regulation side switch, because it is the
       one boundary a reader cannot infer from the line. Overtime alternates
       sides EVERY round, so six more verticals would say nothing a bracket
       under the axis does not; the bracket is drawn once and counted. */
    var swAt = [];
    rounds.forEach(function (r, i) {
      var next = rounds[i + 1];
      if (!next || !sideBy[r.round_number] || sideBy[r.round_number] === sideBy[next.round_number]) return;
      swAt.push(i + 1);
    });
    var regulation = swAt.length ? [swAt[0]] : [];
    var overtime = swAt.slice(1);
    regulation.forEach(function (i) {
      sv("line", { class: "switch", x1: X(i), x2: X(i), y1: TOP, y2: BOT }, gBound);
      text(X(i), TOP - 8, "sides swap", "switch-lab", gBound, "middle");
    });
    if (overtime.length) {
      var x0 = X(overtime[0]), x1 = X(R);
      sv("path", { class: "ot-bracket",
                   d: "M" + x0 + " " + (BOT + 26) + "v6h" + (x1 - x0) + "v-6" }, gBound);
      text((x0 + x1) / 2, BOT + 44, "overtime · sides swap every round · "
        + overtime.length + " more", "switch-lab", gBound, "middle");
    }
    text(M, BOT + 44, R + " rounds, equal width"
      + (sideBy[rounds[0].round_number]
         ? " · " + focal.team_id + " starts on " + sideBy[rounds[0].round_number] : "")
      + " · " + swAt.length + (swAt.length === 1 ? " side switch" : " side switches"),
      "axis-title", gBound, "start");

    /* ---- the area, and what it is NOT ---------------------------------- */
    /* ONE neutral wash between the curve and the null, on both sides, and it
       carries no side meaning at all: it means distance from the null, which
       is the thing this figure is about. The two tokens it replaced tinted
       toward the leader, which put a green swatch labelled "Red" and a maroon
       swatch labelled "Blue" on the 30 red-focal pages of a site whose two
       teams are literally named Red and Blue. Position against the rule and
       the two header percentages already say who leads, twice. */
    var areaD = "M" + X(series[0].x) + " " + Y(EVEN);
    series.forEach(function (n) { areaD += "L" + X(n.x) + " " + Y(n.p); });
    areaD += "L" + X(series[series.length - 1].x) + " " + Y(EVEN) + "Z";
    sv("path", { class: "area-wash", d: areaD }, svg);

    /* ---- THE NULL, second instance ------------------------------------- */
    /* meta.gate.null_probability: the point at which we cannot say who wins.
       Full-strength ink, heavier than any datum on the figure, drawn over the
       wash and UNDER the curve. */
    var gNull = sv("g", { class: "null" }, svg);
    sv("line", { class: "even", x1: M, x2: M + PW, y1: Y(EVEN), y2: Y(EVEN) }, gNull);
    /* THE RULE CARRIES NO LABEL. The chip that named it was the only in-plot
       label sitting at a value the line is guaranteed to visit — every match
       opens at the null, so on 52 of the 68 pages the curve ran straight
       through the words. It is the heaviest horizontal on the figure, halfway
       up an axis whose 0, 25, 75 and 100 per cent ARE labelled, and the header
       prints both sides' live percentage above it: the height is already said
       three ways. Those four tick labels stay under the data, because none of
       them is where a match starts. */

    /* The selected round's band sits over the tint and under the curve: it is
       a place marker for the ledger below, not a value. */
    var band = sv("rect", { class: "wp-band", x: M, y: TOP, width: 0, height: PH }, svg);

    /* ---- the curve ----------------------------------------------------- */
    /* THREE paths, because the line makes three different claims and two of
       them land on the same pixel column.
         wp-line  solid. The part a player did: the round opens, the clock
                  drifts, actions jump.
         wp-term  the model's own calibration gap at the terminal.
         wp-econ  the buy, priced before anyone acts.
       Measured on this payload, all 1,368 terminal nodes share their `x` with
       the round's last action — `horizon` is the last timestamp there is — so
       the terminal gap is always vertical and always sits at the round
       boundary, exactly where the NEXT round's economy move is drawn. The two
       are contiguous rather than overlapping (a terminal's `p` is the value the
       following round_start measures its own `dp` from, at 0.0e+00), so one
       6,4-dashed path for both rendered the boundary as a single move of
       unattributable value with no way to see where the round finished and the
       next buy began. They are separated here: a dash for the economy, a fine
       dot for the calibration gap, and a short rule at the resolved value where
       one hands over to the other. */
    var lineD = "", econD = "", termD = "", closeD = "";
    series.forEach(function (n, i) {
      var prev = i ? series[i - 1] : null;
      if (n.kind === "round_start") {
        /* Round one opens at W(0,0); dp measures back to it, so the first
           economy move is drawn from a value the payload carries rather than
           from an assumed 50%. */
        var from = prev ? prev.p : n.p - n.dp;
        econD += "M" + X(n.x) + " " + Y(from) + "L" + X(n.x) + " " + Y(n.p);
        lineD += "M" + X(n.x) + " " + Y(n.p);
      } else if (n.kind === "terminal") {
        if (prev) termD += "M" + X(prev.x) + " " + Y(prev.p) + "L" + X(n.x) + " " + Y(n.p);
        /* The round resolved here. This is the value the contract pins to the
           next round's wp_before, so the tick is a measured boundary and not a
           decoration — and it is what stops the two dashed claims above and
           below it from reading as one. */
        closeD += "M" + (X(n.x) - 4) + " " + Y(n.p) + "h8";
      } else {
        lineD += (lineD ? "L" : "M") + X(n.x) + " " + Y(n.p);
      }
    });
    sv("path", { class: "wp-free wp-term", d: termD }, svg);
    sv("path", { class: "wp-free wp-econ", d: econD }, svg);
    sv("path", { class: "wp-line", d: lineD }, svg);

    /* ---- the same line, hued where one of the four moved it ------------- */
    /* dP/dq == L to 3.6e-11, so the vertical AT an action is that action's
       match impact drawn to scale. Colouring the marker alone left the reader
       matching a disc to a jump; colouring the jump itself puts the hue on the
       quantity. One path per player, over the neutral line, and a segment is
       only drawn where dp is non-zero — a zero-length vertical under a round
       linecap renders as a dot on a value nobody moved. */
    var actD = {};
    series.forEach(function (n) {
      if (n.kind !== "action" || !n.dp) return;
      var p = byPuuid[n.actor];
      if (!p || !p.short) return;
      actD[p.short] = (actD[p.short] || "")
        + "M" + X(n.x) + " " + Y(n.p - n.dp) + "L" + X(n.x) + " " + Y(n.p);
    });
    actShorts.forEach(function (s) {
      if (actD[s]) sv("path", { class: "wp-line wp-act p-" + s, d: actD[s] }, svg);
    });

    /* There is no entry animation. A line that draws itself in is a line whose
       final value is not on screen when the reader arrives, and on a site
       whose result is a null nothing may perform its own uncertainty. */

    /* ---- action markers ------------------------------------------------ */
    /* House rule 3: the radius is |dp| against a FIXED axis carried in the
       payload, never against the biggest move in this match. A mark of a given
       size therefore means the same number of match win probability points on
       all 68 match pages. Anything at or past the axis is drawn at full size and
       ringed, so a clamped mark does not read as one that stopped on its own. */
    /* THREE LEVELS, because 256 discs at 1.16px minimum separation is a carpet
       and not a set of marks. The vertical in the line is ALREADY the mark, so
       a marker is only worth drawing where it says something the line does not:
       whose action it was, or that it was one of the act's biggest.

         filled hue disc + initial   one of the four
         hollow neutral ring         anyone else, above the payload's gate
         2px tick                    everything else

       The gate is `scale.marker_gate`, the act's p99 of |dp|, carried in the
       payload. p90 — what the magnitude bars use — clips a tenth of its own
       distribution by construction, which is survivable for a bar with its
       number printed beside it and a lie for a mark with no number at all. */
    var AXIS = markerAxis(), GATE_DP = markerGate();
    /* 2.0 to 6.0 before. At 6.0 the biggest mark on the figure was 12px across
       in a 960-wide viewBox that renders near 700 on the page — under 9 real
       pixels, with a 7px initial inside it. The range moves, the RULE does not:
       the radius is still |dp| against scale.marker_gate, so the same size
       still means the same number of points on every match page, and anything at
       or past the axis is still clamped and ringed rather than allowed to grow.
       R_FOCAL is a floor, not a size: an initial needs about 9px of disc to
       clear its own type, and a mark whose whole job is to say who did it that
       is too small to say who did it is a mark that failed. */
    var R_MIN = 2.6, R_MAX = 9.0, R_FOCAL = 4.6;
    function radius(dp) {
      if (!AXIS) return 4.2;
      return R_MIN + (R_MAX - R_MIN) * Math.sqrt(Math.min(1, Math.abs(dp) / AXIS));
    }
    var gMarks = sv("g", { class: "marks" }, svg);
    var marked = 0, ringed = 0;
    series.forEach(function (n) {
      if (n.kind !== "action") return;
      var hue = hueOf(n.actor), big = GATE_DP && Math.abs(n.dp) >= GATE_DP;
      if (!hue && !big) {
        sv("line", { class: "ev-tick", x1: X(n.x), x2: X(n.x),
                     y1: Y(n.p) - 1, y2: Y(n.p) + 1 }, gMarks);
        return;
      }
      var over = AXIS && Math.abs(n.dp) >= AXIS;
      var r = Math.max(radius(n.dp), hue ? R_FOCAL : 0);
      sv("path", {
        class: "ev " + n.type + hue + (n.actor ? (hue ? "" : " other") : " no-actor")
          + (over ? " over" : ""),
        d: markerPath(evShape(n.type), X(n.x), Y(n.p), r)
      }, gMarks);
      if (hue) {
        marked += 1;
        /* The per-player initial inside the disc, on EVERY focal mark now that
           R_FOCAL guarantees the room. It is the figure's only per-player
           secondary channel, and the palette measures 10.2 at deutan — the hue
           is legal ONLY because this channel exists, so dropping it on the
           small marks dropped it exactly where it was needed most. */
        var who = byPuuid[n.actor];
        text(X(n.x), Y(n.p) + 2.5, (who.short || "?").charAt(0).toUpperCase(),
             "ev-init", gMarks, "middle");
      } else { ringed += 1; }
    });

    /* Last, so it is not buried: a terminal shares its x with the round's last
       action and usually its value too — the median gap is four hundredths of a
       point — so this rule would otherwise sit under that action's marker,
       which is the one place it has to stay readable. */
    sv("path", { class: "wp-free wp-close", d: closeD }, svg);

    /* ---- THE RISER ------------------------------------------------------ */
    /* At the selected action the vertical move is drawn as an engineering
       dimension line: serifs at both ends, the value in a box on a leader. On
       any other site a chart is a view of a metric and a dimension line would
       be decoration. Here PLAN §10 measured an action's dp against its ledger
       credit x leverage at 2.0e-16 over 10,113 nodes — the chart and the
       metric are the same object, and this is the only mark that says so. The
       number in the box is the number the ledger row below credits, to the
       last digit, because it is the same number. */
    var gRiser = sv("g", { class: "riser-g", visibility: "hidden" }, svg);
    var riserLine = sv("line", { class: "riser" }, gRiser);
    var riserTop = sv("line", { class: "riser-serif" }, gRiser);
    var riserBot = sv("line", { class: "riser-serif" }, gRiser);
    var riserLead = sv("line", { class: "riser" }, gRiser);
    var riserBox = sv("rect", { class: "riser-box", rx: 1, height: 16 }, gRiser);
    var riserVal = sv("text", { class: "riser-val" }, gRiser);

    function drawRiser(n) {
      if (!n || n.kind !== "action" || !n.dp) {
        gRiser.setAttribute("visibility", "hidden");
        return;
      }
      var x = X(n.x), y0 = Y(n.p - n.dp), y1 = Y(n.p);
      var mid = (y0 + y1) / 2;
      var side = x > M + PW * 0.72 ? -1 : 1;
      var lead = x + side * 16;
      var label = move("dp", n.dp, MOVE);
      var w = label.length * 6.6 + 10;
      riserLine.setAttribute("x1", x); riserLine.setAttribute("x2", x);
      riserLine.setAttribute("y1", y0); riserLine.setAttribute("y2", y1);
      [[riserTop, y0], [riserBot, y1]].forEach(function (pair) {
        pair[0].setAttribute("x1", x - 5); pair[0].setAttribute("x2", x + 5);
        pair[0].setAttribute("y1", pair[1]); pair[0].setAttribute("y2", pair[1]);
      });
      riserLead.setAttribute("x1", x); riserLead.setAttribute("x2", lead);
      riserLead.setAttribute("y1", mid); riserLead.setAttribute("y2", mid);
      riserBox.setAttribute("x", side > 0 ? lead : lead - w);
      riserBox.setAttribute("y", mid - 8);
      riserBox.setAttribute("width", w);
      riserVal.setAttribute("x", (side > 0 ? lead : lead - w) + w / 2);
      riserVal.setAttribute("y", mid + 4);
      riserVal.setAttribute("text-anchor", "middle");
      riserVal.textContent = label;
      gRiser.setAttribute("visibility", "visible");
    }

    /* ---- crosshair and tooltip ----------------------------------------- */
    var gCross = sv("g", { class: "cross", visibility: "hidden" }, svg);
    var crossX = sv("line", { class: "cross-v", y1: TOP, y2: BOT }, gCross);
    var crossDot = sv("circle", { class: "cross-dot", r: 4.2 }, gCross);
    /* The tooltip hangs off .wp-plot rather than off the scroller, so a
       horizontal scroll cannot clip it and it never adds a scrollbar of its
       own. getBoundingClientRect already carries the scroll offset. */
    var tip = el("div", "wp-tip", plot);
    tip.setAttribute("role", "presentation");
    tip.hidden = true;

    var readout = el("p", "fig-readout", host);
    readout.setAttribute("role", "status");
    readout.setAttribute("aria-live", "polite");
    readout.setAttribute("aria-atomic", "true");
    /* The standing "Arrow keys step the line" paragraph is folded into the
       readout's rest state below. It was a permanent row under the figure for
       a hint that has done its job the moment the reader points at the line,
       and the rest state is exactly the moment it is still worth saying. */

    var det = el("details", "fig-data", host);
    var detSum = el("summary", null, det, "");
    var detWrap = el("div", "table-wrap", det);
    detWrap.tabIndex = 0;
    detWrap.setAttribute("role", "region");
    detWrap.setAttribute("aria-label", "Every node of the selected round — scrolls sideways");

    /* ---- text ---------------------------------------------------------- */
    function fmtActor(puuid) {
      var p = byPuuid[puuid];
      if (!p) return EM;
      return p.name + (p.agent ? " (" + p.agent + ")" : "");
    }
    function hueOf(puuid) {
      var p = byPuuid[puuid];
      return p && p.short ? " p-" + p.short : "";
    }
    function evShape(type) {
      return (type === "plant" || type === "detonate") ? "square"
        : type === "defuse" ? "diamond"
        : type === "revive" ? "triangle" : "circle";
    }
    function scoreAt(n) {
      var r = roundBy[n.r];
      return r ? r.own + "–" + r.other : EM;
    }
    /* What a node is, in the payload's own words. meta.dict names all four
       kinds and defines them; the view adds only what the node itself measured
       — the event type, the terminal, and who won the round. */
    function happened(n) {
      if (n.kind === "action") return n.type;
      if (n.kind === "terminal") {
        return label("kind_terminal", "Terminal") + " · " + (n.terminal_type || EM)
          + " · " + (n.won ? focal.team_id : (other ? other.team_id : EM)) + " wins the round";
      }
      return label("kind_" + n.kind, n.kind);
    }
    function why(n) {
      var s = spec("kind_" + n.kind);
      return (s && s.definition) || null;
    }

    /* ---- the readout, the header and the tooltip ----------------------- */
    var finalP = series[series.length - 1].p;

    function paintHead(n) {
      var p = n ? n.p : finalP;
      focalPct.textContent = num(p, (spec("p") && spec("p").format) || PCT);
      otherPct.textContent = num(1 - p, (spec("p") && spec("p").format) || PCT);
      focalPct.className = "wp-pct " + (p > EVEN ? "ahead" : p < EVEN ? "behind" : "level");
      otherPct.className = "wp-pct " + (p < EVEN ? "ahead" : p > EVEN ? "behind" : "level");
      headWhen.textContent = n
        ? "Round " + n.r + " · " + secs(n.t)
        : "Final · " + MATCH.map + ", " + fullDay(MATCH.started_at);
    }

    /* The four sentences that used to be here spelled out what solid, dotted
       and dashed mean. The legend sits immediately above the chart and says it
       already, in the same ink as the paths themselves. */
    function restText() {
      readout.textContent = "";
      el("span", null, readout,
        "Point at the line for the state at that moment; click, or press Enter, to open that "
        + "round below. Arrow keys step it.");
    }

    function sayNode(n) {
      readout.textContent = "";
      el("b", null, readout, "Round " + n.r);
      el("span", null, readout, " · " + scoreAt(n) + " · " + secs(n.t) + " · " + happened(n));
      if (n.kind === "action" && n.actor) {
        el("span", null, readout, " · ");
        el("span", ("hue" + hueOf(n.actor)).trim(), readout, fmtActor(n.actor));
        if (n.victim) el("span", null, readout, " → " + fmtActor(n.victim));
      } else if (n.kind === "action") {
        el("span", "na", readout, " · " + EM + " no actor, so the ledger credits nobody");
      }
      /* A one-line readout is a sentence, not a set of labelled cells: the
         tooltip and the table under the figure carry meta.dict's own labels
         for these two, and repeating them here would take the line past the
         width it has. */
      el("span", null, readout, " · round " + val("q", n.q, PCT)
        + " · match " + val("p", n.p, PCT) + " · ");
      el("span", sgn(n.dp), readout, move("dp", n.dp, MOVE));
      el("span", null, readout, " " + (n.kind === "action"
        ? "match impact" : n.kind === "round_start" ? "from the economy"
        : n.kind === "terminal" ? "at the terminal" : "of clock drift"));
    }

    function paintTip(n) {
      tip.textContent = "";
      tip.hidden = false;
      var h = el("div", "wp-tip-head", tip);
      el("b", null, h, "Round " + n.r);
      el("span", null, h, " " + scoreAt(n) + " · " + secs(n.t));
      var what = el("div", "wp-tip-what kind-" + n.kind, tip, happened(n));
      if (why(n)) what.title = why(n);
      if (n.kind === "action") {
        var who = el("div", "wp-tip-who", tip);
        if (n.actor) el("span", ("hue" + hueOf(n.actor)).trim(), who, fmtActor(n.actor));
        else el("span", "na", who, EM + " no actor");
        if (n.victim) el("span", null, who, " → " + fmtActor(n.victim));
      } else if (n.kind === "round_start") {
        el("div", "wp-tip-who na", tip, EM + " the economy, not a player");
      } else if (n.kind === "terminal") {
        el("div", "wp-tip-who na", tip, EM + " booked to a team side, not a player");
      }
      var rows = el("dl", "wp-tip-rows", tip);
      function row(k, v, cls) {
        var d = el("div", null, rows);
        el("dt", null, d, k);
        el("dd", cls || null, d, v);
      }
      row(label("q", "Round win"), val("q", n.q, PCT));
      row(label("p", "Match win"), val("p", n.p, PCT));
      row(label("dp", "Move"), move("dp", n.dp, MOVE), sgn(n.dp));
      var r = roundBy[n.r];
      if (r) row(label("leverage", "Leverage"), val("leverage", r.leverage)
        + " (" + val("li", r.li, LI) + "×)");
    }

    function placeTip(n) {
      var box = plot.getBoundingClientRect();
      var svgBox = svg.getBoundingClientRect();
      var scale = svgBox.width / W || 1;
      var left = (svgBox.left - box.left) + X(n.x) * scale;
      var top = (svgBox.top - box.top) + Y(n.p) * scale;
      var w = tip.offsetWidth, hgt = tip.offsetHeight;
      var flip = left + 14 + w > box.width;
      tip.style.left = Math.max(0, Math.min(flip ? left - w - 14 : left + 14, box.width - w)) + "px";
      tip.style.top = Math.max(0, Math.min(top - hgt / 2, box.height - hgt)) + "px";
    }

    /* ---- focus, crosshair, keyboard ------------------------------------ */
    var at = -1;

    function focusAt(i) {
      if (i < 0 || i >= series.length) return;
      if (i === at) return;
      at = i;
      var n = series[i];
      gCross.setAttribute("visibility", "visible");
      crossX.setAttribute("x1", X(n.x));
      crossX.setAttribute("x2", X(n.x));
      crossDot.setAttribute("cx", X(n.x));
      crossDot.setAttribute("cy", Y(n.p));
      paintHead(n);
      sayNode(n);
      drawRiser(n);
      paintTip(n);
      placeTip(n);
    }
    function blurAll() {
      at = -1;
      gCross.setAttribute("visibility", "hidden");
      gRiser.setAttribute("visibility", "hidden");
      tip.hidden = true;
      paintHead(null);
      restText();
    }

    /* Snap to the nearest node: x first, because the axis is time, then the
       closest of the handful that share that x — which is what makes the top
       and the bottom of an action's vertical jump separately reachable. */
    function nearest(px, py) {
      var lo = 0, hi = series.length - 1, mid;
      while (lo < hi) {
        mid = (lo + hi) >> 1;
        if (X(series[mid].x) < px) lo = mid + 1; else hi = mid;
      }
      var best = lo, bestD = Infinity;
      for (var i = Math.max(0, lo - 8); i < Math.min(series.length, lo + 9); i++) {
        var dx = X(series[i].x) - px, dy = Y(series[i].p) - py;
        var d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    }
    function toView(evt) {
      var box = svg.getBoundingClientRect();
      var scale = box.width / W || 1;
      return { x: (evt.clientX - box.left) / scale, y: (evt.clientY - box.top) / scale };
    }

    svg.addEventListener("pointermove", function (evt) {
      var v = toView(evt);
      focusAt(nearest(v.x, v.y));
    });
    svg.addEventListener("pointerleave", blurAll);
    svg.addEventListener("click", function (evt) {
      var v = toView(evt);
      var i = nearest(v.x, v.y);
      focusAt(i);
      select(series[i].r, true);
    });
    svg.addEventListener("focus", function () {
      if (at < 0) focusAt(firstOf(selected) >= 0 ? firstOf(selected) : 0);
    });
    svg.addEventListener("blur", blurAll);
    svg.addEventListener("keydown", function (evt) {
      var i = at < 0 ? 0 : at, n = series[i], j = null;
      if (evt.key === "ArrowRight") j = i + 1;
      else if (evt.key === "ArrowLeft") j = i - 1;
      else if (evt.key === "Home") j = 0;
      else if (evt.key === "End") j = series.length - 1;
      else if (evt.key === "ArrowUp" || evt.key === "ArrowDown") {
        var step = evt.key === "ArrowUp" ? 1 : -1;
        var t = firstOf(n.r + step);
        j = t >= 0 ? t : i;
      } else if (evt.key === "Enter" || evt.key === " " || evt.key === "Spacebar") {
        evt.preventDefault();
        select(series[i].r, true);
        return;
      } else return;
      evt.preventDefault();
      focusAt(Math.max(0, Math.min(series.length - 1, j)));
    });

    function firstOf(round) {
      for (var i = 0; i < series.length; i++) if (series[i].r === round) return i;
      return -1;
    }

    /* ---- the selected round -------------------------------------------- */
    chart = {
      select: function (n) {
        var i = rounds.map(function (r) { return r.round_number; }).indexOf(n);
        if (i < 0) return;
        band.setAttribute("x", X(i));
        band.setAttribute("width", PW / R);
        buildRoundTable(roundBy[n], nodesBy[n] || []);
      }
    };

    function buildRoundTable(r, ns) {
      detWrap.textContent = "";
      var acts = ns.filter(function (n) { return n.kind === "action"; });
      var drift = ns.reduce(function (a, n) { return a + (n.kind === "clock" ? n.dp : 0); }, 0);
      detSum.textContent = "Round " + r.round_number + ", node by node ("
        + acts.length + " credited actions)";

      var tb = el("table", null, detWrap);
      var cap = el("caption", null, tb);   // first child: a caption is not a trailing note
      var head = el("tr", null, el("thead", null, tb));
      [[label("t", "Time"), "n"], [label("kind", "What"), "l"], ["Player", "l"],
       ["Against", "l"], [label("q", "Round win"), "n"], [label("p", "Match win"), "n"],
       [label("dp", "Move"), "n"]].forEach(function (h) {
        el("th", h[1], head, h[0]).setAttribute("scope", "col");
      });
      var body = el("tbody", null, tb);
      ns.forEach(function (n) {
        if (n.kind === "clock") return;      // the drift is the line, and it is summed in the caption
        var tr = el("tr", "kind-" + n.kind, body);
        el("td", "n", tr, secs(n.t));
        var what = el("td", "l", tr, happened(n));
        if (why(n)) what.title = why(n);
        /* Rule 1: no cell invents a name to fill itself. An em dash, and the
           reason is the payload's own definition of the kind. */
        var who = el("td", "l" + (n.actor ? (hueOf(n.actor) ? " hue" + hueOf(n.actor) : "") : " na"),
                     tr, n.actor ? fmtActor(n.actor) : EM);
        if (!n.actor) who.title = why(n) || "No actor is credited for this node.";
        el("td", "l" + (n.victim ? "" : " na"), tr, n.victim ? fmtActor(n.victim) : EM);
        el("td", "n", tr, val("q", n.q, PCT));
        el("td", "n", tr, val("p", n.p, PCT));
        el("td", "n " + sgn(n.dp), tr, move("dp", n.dp, MOVE));
      });
      /* Two values, no lesson. What leverage IS belongs on methods.html; the
         caption's job is to account for the rows that are not in the table. */
      cap.textContent = label("kind_clock", "Clock") + " drift " + move("dp", drift, MOVE)
        + ", spread along the line rather than booked to an event, so it has no row. "
        + label("leverage", "Leverage") + " " + val("leverage", r.leverage)
        + ", " + val("li", r.li, LI) + "× the act mean.";
    }

    /* ---- descriptions -------------------------------------------------- */
    var biggest = null;
    series.forEach(function (n) {
      if (n.kind === "action" && (!biggest || Math.abs(n.dp) > Math.abs(biggest.dp))) biggest = n;
    });
    ttl.textContent = "Match win probability for " + focal.team_id + " across " + R
      + " rounds on " + MATCH.map + ", " + fullDay(MATCH.started_at)
      + ", moving continuously inside every round.";
    /* The only description a reader who cannot see the figure gets, so it names
       every channel the figure uses — including the hue on the verticals, which
       is otherwise carried by colour alone and would leave that reader with a
       count of marks and no way to know whose they were. */
    dsc.textContent = "The line starts at " + num(series[0].p - series[0].dp, PCT)
      + " and ends at " + num(finalP, PCT) + "; " + focal.team_id + " won " + focal.rounds_won
      + " rounds against " + (other ? other.rounds_won : EM) + ". "
      + series.filter(function (n) { return n.kind === "action"; }).length
      + " credited actions sit on the line: " + marked + " by one of the four, drawn in that "
      + "player's hue with their initial, " + ringed + " by anyone else above the act's top "
      + "hundredth, drawn as a hollow ring, the rest as the vertical in the line."
      + (actShorts.length ? " Hued by " + actShorts.map(function (s) {
          return String(actWho[s].name || s).split("#")[0] + " (" + actN[s] + ")";
        }).join(", ") + "." : "")
      + (biggest ? " Largest single move: a " + biggest.type + " in round " + biggest.r
          + ", " + num(biggest.dp, MOVE) + "." : "")
      + " Every node of the selected round is listed as a table under the figure.";

    /* ---- wire up ------------------------------------------------------- */
    /* `host`, not an intermediate wrapper. wireTabs only appends a strip when
       the page shipped none, and every match page ships one, so the wrapper
       was an element that was empty on all 68 pages that exist. */
    tabs = wireTabs(host, rounds, function (n) { select(n, false); });
    paintHead(null);
    restText();
    select(opening(), true);
  }

  /* House rule 3 again, in one place: the marker axis is a fixed number the
     payload carries, so no mark's size is a function of the biggest value in
     view. `wp_move` is the name to add if a per-move axis is ever derived;
     until then `round_mwpa` is the right stand-in — the same unit, match win
     probability points, at the same corpus percentile, identical on all 68
     match pages. If the payload carries neither, the marks go one size rather than
     inventing a scale. */
  function markerAxis() {
    var names = ["marker_gate", "wp_move", "action_dp", "event_mwpa", "round_mwpa", "match_mwpa"];
    for (var i = 0; i < names.length; i++) {
      var v = SCALE[names[i]];
      if (typeof v === "number" && v > 0) return v;
    }
    return null;
  }

  /* The gate a non-focal action has to clear before it gets a mark of its own.
     Carried in the payload as the act's p99 of |dp|; if it is not there, no
     gate, and every action keeps a mark rather than the view inventing a
     threshold. */
  function markerGate() {
    var v = SCALE.marker_gate;
    return (typeof v === "number" && v > 0) ? v : null;
  }

  /* The round index is emitted by build.py. Read whatever it emitted, and only
     build one if the page has none — the figure has to work either way, and
     neither of us owns the other's file.
     ---------------------------------------------------------------------
     It is no longer the figure's tab bar. The curve is continuous and selects
     a round itself; this strip is the page's index into the ledger panels, and
     the page ships its own controller for them. So three kinds of control get
     three different treatments, and an anchor gets none of a button's:

       role="tab"   aria-selected and a roving tabindex
       <a>          aria-current, the browser's own navigation left alone —
                    no preventDefault, and no arrow-key roving, because
                    swallowing the arrow keys on a focused link takes away
                    scrolling and gives nothing back
       <button>     aria-pressed

     Marking `is-on` alongside the page's controller is idempotent: both write
     the same value from the same round number, so whichever runs second agrees
     with the first. */
  function wireTabs(host, rounds, onPick) {
    var numbers = rounds.map(function (r) { return r.round_number; });
    var strip = document.querySelector("[data-round-tabs], .round-tabs");
    var btns = strip
      ? Array.prototype.slice.call(strip.querySelectorAll("button, [role='tab'], a[data-round]"))
      : Array.prototype.slice.call(document.querySelectorAll("button[data-round], button[data-round-number]"));

    if (!btns.length) {
      strip = el("div", "round-tabs", host);
      strip.setAttribute("data-round-tabs", "");
      strip.setAttribute("role", "tablist");
      strip.setAttribute("aria-label", "Rounds");
      btns = rounds.map(function (r) {
        var b = el("button", "round-tab", strip, String(r.round_number));
        b.type = "button";
        b.setAttribute("role", "tab");
        b.setAttribute("data-round", r.round_number);
        b.setAttribute("aria-label", "Round " + r.round_number);
        return b;
      });
    }

    var kind = btns[0].getAttribute("role") === "tab" ? "tab"
      : btns[0].tagName.toLowerCase() === "a" ? "link" : "button";
    var map = btns.map(function (b, i) {
      var raw = b.getAttribute("data-round") || b.getAttribute("data-round-number") || b.textContent;
      var n = parseInt(String(raw).replace(/[^0-9-]/g, ""), 10);
      return numbers.indexOf(n) >= 0 ? n : numbers[Math.min(i, numbers.length - 1)];
    });

    btns.forEach(function (b, i) {
      b.addEventListener("click", function (e) {
        if (kind !== "link") e.preventDefault();
        onPick(map[i]);
      });
      if (kind === "link") return;
      b.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1
          : e.key === "Home" ? -btns.length : e.key === "End" ? btns.length : 0;
        if (!d) return;
        e.preventDefault();
        var j = Math.max(0, Math.min(btns.length - 1, i + d));
        btns[j].focus();
        onPick(map[j]);
      });
    });

    return {
      mark: function (n) {
        btns.forEach(function (b, i) {
          var on = map[i] === n;
          b.classList.toggle("is-on", on);
          if (kind === "tab") {
            b.setAttribute("aria-selected", String(on));
            b.setAttribute("tabindex", on ? "0" : "-1");
          } else if (kind === "link") {
            if (on) b.setAttribute("aria-current", "true");
            else b.removeAttribute("aria-current");
          } else {
            b.setAttribute("aria-pressed", String(on));
          }
        });
      },
      reveal: function (n) {
        var i = map.indexOf(n);
        if (i < 0 || !btns[i].scrollIntoView) return;
        var box = btns[i].getBoundingClientRect();
        var par = btns[i].parentNode.getBoundingClientRect();
        if (box.left < par.left || box.right > par.right) {
          btns[i].scrollIntoView({ block: "nearest", inline: "center" });
        }
      }
    };
  }

  /* ==== the index ======================================================= */
  /* ONE ROW PER MATCH, sortable, filterable in place, and the whole row is the
     link. It carries the click-through the tracker's dots used to have — which
     is why those could be deleted rather than merely thinned — and it is the
     addressable index of every match, so no reader ever has to recognise a
     match by the silhouette of its curve.

     It used to be one row per player per match, which printed a match four
     times when four of them played it. So `data-player` is now a SPACE-
     SEPARATED LIST of shorts and the filter tests membership rather than
     equality.

     The margin COLUMN is gone — the score, the margin and the result were
     three spellings of one fact — but the margin SORT is not, because an
     ordering is not a spelling. `data-margin` rides on the row and the Result
     heading is its button, so "which of these sixty-eight were close" is still
     one click, on the cell that prints the two numbers it comes from.

     Everything it needs is already in the DOM as data attributes, so a page
     whose script never runs still has every row, each one a working link. This
     adds ordering, filtering and a keyboard cursor to something that worked. */
  function wireIndex(host) {
    var tbl = host.querySelector("table");
    if (!tbl) return;
    var body = tbl.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    var counter = document.querySelector("[data-idx-count]");
    var filters = Array.prototype.slice.call(document.querySelectorAll("[data-idx-filter]"));
    var only = "", cursor = -1;

    function value(tr, key) {
      if (key === "player") return tr.getAttribute("data-player") || "";
      if (key === "date") return tr.getAttribute("data-date") || "";
      return Number(tr.getAttribute("data-" + key));
    }
    /* Membership, not equality, and padded on both sides so `mar` cannot match
       `martin` and `snorlax` cannot match a short that ends in it. */
    function has(tr, short) {
      return (" " + (tr.getAttribute("data-player") || "") + " ")
        .indexOf(" " + short + " ") >= 0;
    }
    function shown() { return rows.filter(function (tr) { return !tr.hidden; }); }
    function paintCount() {
      if (!counter) return;
      var n = shown().length;
      counter.textContent = n + (n === 1 ? " row" : " rows") + (only ? ", one player" : "");
    }
    function apply() {
      rows.forEach(function (tr) { tr.hidden = !!only && !has(tr, only); });
      paintCount();
    }

    var heads = Array.prototype.slice.call(tbl.tHead.rows[0].cells);
    function sortBy(key, dir) {
      heads.forEach(function (th) {
        var b = th.querySelector("button.sort");
        if (b && b.getAttribute("data-sort") === key) {
          th.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
        } else {
          th.removeAttribute("aria-sort");
        }
      });
      rows.sort(function (a, b) {
        var x = value(a, key), y = value(b, key);
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
      rows.forEach(function (tr) { body.appendChild(tr); });
    }
    heads.forEach(function (th) {
      var btn = th.querySelector("button.sort");
      if (!btn) return;
      btn.addEventListener("click", function () {
        sortBy(btn.getAttribute("data-sort"),
               th.getAttribute("aria-sort") === "ascending" ? -1 : 1);
      });
    });

    filters.forEach(function (b) {
      b.addEventListener("click", function () {
        only = b.getAttribute("data-idx-filter");
        filters.forEach(function (o) {
          o.setAttribute("aria-pressed", String(o === b));
        });
        apply();
      });
    });

    /* j and k move a cursor; Enter opens the row it is on. The row was always
       a link — this is a second way to reach it, not the only one. */
    host.addEventListener("keydown", function (evt) {
      var live = shown();
      if (!live.length) return;
      var d = evt.key === "j" ? 1 : evt.key === "k" ? -1 : 0;
      if (d) {
        evt.preventDefault();
        cursor = Math.max(0, Math.min(live.length - 1, (cursor < 0 ? -1 : cursor) + d));
      } else if (evt.key === "Enter" && cursor >= 0) {
        var href = live[cursor].getAttribute("data-href");
        if (href) { location.href = href; return; }
      } else { return; }
      rows.forEach(function (tr) { tr.classList.remove("is-cursor"); });
      live[cursor].classList.add("is-cursor");
      if (live[cursor].scrollIntoView) live[cursor].scrollIntoView({ block: "nearest" });
    });

    /* NEWEST FIRST is the rest state. The act is in progress, so the match a
       reader arrives looking for is the one that was played last, and it used
       to be the row at the bottom of sixty-eight. The sort runs here rather
       than in build.py's row order so the aria-sort on the header is set too:
       a table that is ordered and does not say so is a table the reader cannot
       tell from an unordered one. */
    sortBy("date", -1);
    paintCount();
  }

  function boot() {
    initTheme();
    initIcons();
    var t = document.querySelector("[data-tracker]");
    if (t) drawTracker(t);
    var m = document.querySelector("[data-match-figure]");
    if (m) drawMatchFigure(m);
    var x = document.querySelector("[data-index]");
    if (x) wireIndex(x);
    var r = document.querySelector(".fig-track");
    if (r) wireTrack(r);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
