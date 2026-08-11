/* quad-app.js — the three figures on the four-player MWPA site.
 *
 * Front page: the tracker, inside [data-tracker], and offense against defense,
 *             inside [data-offdef] — a scatter of both halves of every
 *             player-match, with a binned panel per player under it.
 * Match page: the win-probability curve, inside [data-match-figure].
 * Hand-built SVG, no library, no build step, no network. Every page opens off
 * disk and reads its numbers out of window.QUAD, which build.py inlines.
 *
 * WHY THE TRACKER IS THE RUNNING IMPACT PER MATCH.
 * At a player's match i the line is cumulative MWPA / (i + 1) — the headline
 * metric computed on the matches played so far. EACH LINE THEREFORE ENDS ON
 * THAT PLAYER'S HEADLINE NUMBER, which is the number that player's own card
 * prints and the number in their legend key here. No figure is written into
 * this comment: the payload is refreshed on a schedule and every one of them
 * moves when it is.
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
  var LONG_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December"];
  /* The arrows are gone. Every signed format on this site carries a printed +
     or -, so the glyph was a fourth spelling of a fact the number, the colour
     and the mark's position already carry three times. Same as build.py, which
     keeps zero (a middot) and none (an em dash) because those two say something
     no digit does. */
  var GLYPH = { pos: "", neg: "" };
  var EM = "—";       // NOT MEASURED
  var MID = "·";      // an exact measured zero — build.py's own two glyphs, same meanings
  var uidN = 0;
  function uid(p) { uidN += 1; return p + "-" + uidN; }

  /* HOW A PERSON IS WRITTEN, and it is build.py's rule in the other medium. A focal player is
     somebody the reader knows, so the Riot tag comes off and one of them takes an initialism;
     an OPPONENT is a pseudonym whose tag IS the identity — six `Anonymous` rows in one match
     are told apart by nothing else — so those names pass through whole. The map is built from
     whichever payload blocks this page carries, which is why nothing here names an opponent. */
  var SHORT_NAME = { MartinLutherKing: "MLK" };
  var NAME = {};
  function who(name) { return name ? (NAME[name] || String(name)) : EM; }

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

  /* The name map, from whichever payload blocks this page carries. A row with no `short` is
     an opponent and is not entered, so `who` returns it whole. */
  [(SITE && SITE.players) || [], (MATCH && MATCH.players) || [], PLAYER ? [PLAYER] : []]
    .forEach(function (list) {
      list.forEach(function (p) {
        if (!p || !p.short || !p.name) return;
        var base = String(p.name).split("#")[0];
        NAME[p.name] = SHORT_NAME[base] || base;
      });
    });

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
  /* WHAT A TOKEN IS CALLED, and it is build.py's `node_type_label` in the other medium. An
     action's type is a payload enum — `kill`, `timer_expired` — and the round panel beside this
     figure prints it through meta.dict first and a humanised fallback second. Printing the raw
     enum here made the same node read `kill` on the curve and `Kill` in the table under it. */
  function humanize(token) { return String(token).replace(/_/g, " "); }
  function typeLabel(token) {
    if (!token) return EM;
    var e = spec(token);
    if (e && e.label) return e.label;
    var t = humanize(token);
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  function sgn(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "zero"; }
  /* Sign, three ways: the + or - the format spec prints, the colour class from
     sgn(), and the mark's own position against the 50% rule. GLYPH.pos and
     GLYPH.neg are empty, so this returns "" for every value; it stays because
     move() is the one place a glyph would go back in. */
  function glyph(v) { return v > 0 ? GLYPH.pos : v < 0 ? GLYPH.neg : ""; }
  /* THE THREE STATES OF A SIGNED NUMBER, and this is build.py's `signed_text` in the other
     medium. Absent is an em dash. An EXACT ZERO is a middot — measured, and neither direction —
     never `+0.00%`, which claims a direction the number does not have. A value smaller than its
     own format can write prints as less-than the smallest printable magnitude, with no sign and
     no direction colour. Without this the figure wrote `0.00%` for the same node the round
     panel under it wrote `·` for, six inches apart on one page. */
  function step(key, fallback) {
    var m = /\.(\d+)([f%])$/.exec((spec(key) && spec(key).format) || fallback || "");
    return m ? Math.pow(10, -(Number(m[1]) + (m[2] === "%" ? 2 : 0))) : null;
  }
  function move(key, v, fallback) {
    if (v === null || v === undefined || v !== v) return EM;
    if (v === 0) return MID;
    var st = step(key, fallback);
    if (st !== null && Math.abs(v) < st) {
      return "<" + num(st, ((spec(key) && spec(key).format) || fallback || "").replace("+", ""));
    }
    var g = glyph(v);
    return (g ? g + " " : "") + val(key, v, fallback);
  }
  /* No direction colour on a value the format cannot resolve, for the same reason. */
  function sgnOf(key, v, fallback) {
    var st = step(key, fallback);
    if (v && st !== null && Math.abs(v) < st) return "under";
    return sgn(v);
  }

  /* MONTH FIRST, in both lengths, because build.py writes `August 6` on every date it
     renders and a value that changes format the moment a key is pressed reads as a different
     value. The short form is for an axis tick, where five characters is the whole budget. */
  function day(iso) {
    var d = new Date(iso);
    return MONTHS[d.getUTCMonth()] + " " + d.getUTCDate();
  }
  function longDay(iso) {
    var d = new Date(iso);
    return LONG_MONTHS[d.getUTCMonth()] + " " + d.getUTCDate();
  }
  function fullDay(iso) {
    return longDay(iso) + " " + new Date(iso).getUTCFullYear();
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
        /* The same long date build.py renders into this element on the server. */
        span("", longDay(row.started_at) + " · " + row.map,
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
           exactly, which is the number the legend key beside it prints. */
        return { x: order[r.match_id], r: r, m: r.cumulative / (r.i + 1) };
      }).filter(function (d) { return d.x !== undefined; });
      if (rows.length) series.push({ p: p, rows: rows, shape: SHAPE[p.short] || "circle" });
    });
    if (!series.length) return;

    host.textContent = "";
    host.classList.add("fig", "fig-tracker");

    /* THE Y AXIS IS scale.impact, the payload's fixed headline axis: the
       maximum of the twelve headline numbers, four players by three endpoints,
       so no season line and no interval endpoint can leave the box. It is the
       one axis this figure shares with the capped span on a player's card.
       House rule 3: read, never recomputed.

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
    /* ML holds the widest y tick. `impact` prints two decimals now, so `+10.00%` is 44.3
       units against the 38 the old gutter left: both signed gridlines were rendering as an
       unsigned `10.00%` with the + or - clipped off by the viewBox — the axis losing exactly
       the non-colour sign channel house rule 2 requires it to carry. */
    var W = 960, H = 424, ML = 60, MR = 138, MT = 22, MB = 46;
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
      return who(s.p.name) + ": " + val("impact", last.m, MOVE) + " "
        + ((spec("impact") && spec("impact").unit) || "per match")
        + " over " + s.rows.length + " matches, first on " + fullDay(s.rows[0].r.started_at)
        + ", last on " + fullDay(last.r.started_at) + ".";
    }).join(" ") + " Each line ends on that player's headline number, and pointing at a match "
      + "moves the four figures on the right to their value at that match. Every match's own "
      + label("mwpa", "MWPA") + " is in the table under the figure and in the index below it.";

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

      /* THE PER-MATCH MARKS ARE OFF THIS FIGURE. One hundred and eighty-six of them, four
         series deep, drew a raw datum four times as wide as any season mean over the four
         lines that are the finding — and the reader's question here is what a season did, not
         what one match did. Every one of those values is still exact in the hover table below,
         in the offense/defense figure under it, and as a row in the index. The lines are the
         figure now; `SHAPE` survives because the legend key and that scatter still use it. */

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
    /* THE END LABEL IS A READOUT, NOT A CAPTION. It printed where the line finished, which
       is the one value the reader can already see by looking at where the line finished. Under
       the pointer it prints the line's height AT that match instead — the running impact per
       match on the matches played so far — so the four numbers on the right and the four lines
       on the left are the same object at the same moment. The leader follows the value; the
       label's own y does not, because four labels re-solving their collisions on every
       pointermove is motion carrying no finding. At rest they are the headline again. */
    ends.forEach(function (e) {
      var ge = sv("g", { class: "series end p-" + e.s.p.short }, svg);
      e.leader = sv("line", { class: "leader", x1: e.x + 5, x2: ML + PW + 14,
                              y1: Y(e.v), y2: e.y }, ge);
      text(ML + PW + 20, e.y - 1, who(e.s.p.name), "end-name", ge);
      e.label = text(ML + PW + 20, e.y + 13, val("impact", e.v, MOVE),
                     "end-val " + sgn(e.v), ge);
    });

    /* `at` is a match index, or null for the rest state. A player who had not played by then
       has no running mean yet: the label goes to an em dash rather than to their final number,
       which would be a value from that player's future. */
    function paintEnds(at) {
      ends.forEach(function (e) {
        var hit = null;
        if (at !== null) {
          e.s.rows.forEach(function (row) { if (row.x <= at) hit = row; });
        } else {
          hit = e.s.rows[e.s.rows.length - 1];
        }
        if (!hit) {
          e.label.textContent = EM;
          e.label.setAttribute("class", "end-val none");
          e.leader.setAttribute("visibility", "hidden");
          return;
        }
        e.label.textContent = val("impact", hit.m, MOVE);
        e.label.setAttribute("class", "end-val " + sgn(hit.m));
        e.leader.setAttribute("visibility", "visible");
        e.leader.setAttribute("y1", Y(hit.m));
      });
    }

    /* ---- one crosshair, every live series ------------------------------ */
    var gCross = sv("g", { class: "cross", visibility: "hidden" }, svg);
    var band = sv("rect", { class: "band", y: MT, height: PH, width: Math.max(PW / N, 6) }, gCross);
    var crossV = sv("line", { class: "cross-v", y1: MT, y2: MT + PH }, gCross);
    svg.setAttribute("tabindex", "0");

    /* THE READOUT IS A TABLE, not a sentence with middots in it. Four players at three
       quantities each was eleven separators on one wrapping line, and a reader comparing two
       of them had to compare two substrings of a paragraph. One row per player, one column
       per quantity, so the comparison is a scan down a column — the same argument the match
       index's cross-tab is built on. It is `role="status"`, so a screen reader still gets it
       read out on change; the caption carries which match the rows belong to. */
    var readout = el("div", "fig-readout tracker-read", host);
    readout.setAttribute("role", "status");
    readout.setAttribute("aria-live", "polite");

    function rest() {
      gCross.setAttribute("visibility", "hidden");
      paintEnds(null);
      readout.textContent = "";
      el("p", "tracker-rest", readout,
         label("impact", "Impact per match") + " as a line, ending on that player's headline "
         + "number. Point anywhere for every player in that match, and the figures on the "
         + "right move to that match.");
    }
    function say(i) {
      var m = matches[i];
      if (!m) return;
      gCross.setAttribute("visibility", "visible");
      paintEnds(i);
      band.setAttribute("x", X(i) - Math.max(PW / N, 6) / 2);
      crossV.setAttribute("x1", X(i));
      crossV.setAttribute("x2", X(i));
      readout.textContent = "";

      var tb = el("table", "tracker-tbl", readout);
      el("caption", null, tb, m.map + " · " + longDay(m.started_at)
        + (m.score ? " · " + m.score[0] + "–" + m.score[1] : ""));
      var hr = el("tr", null, el("thead", null, tb));
      [["Player", "l"], [label("mwpa", "MWPA"), "n"],
       [label("impact", "Impact per match"), "n"], [label("matches", "Matches"), "n"]]
        .forEach(function (h) {
          el("th", h[1], hr, h[0]).setAttribute("scope", "col");
        });
      var body = el("tbody", null, tb);
      var any = false;
      series.forEach(function (s) {
        var hit = null;
        s.rows.forEach(function (row) { if (row.x === i) hit = row; });
        if (!hit) return;
        any = true;
        var tr = el("tr", "p-" + s.p.short, body);
        el("th", "l hue", tr, who(s.p.name)).setAttribute("scope", "row");
        /* The mark's exact value, whether or not it fitted on the axis, so a caret at the
           edge never costs the reader the number. Then the line's height at this match, and
           the count that makes the two comparable across players. */
        el("td", "n " + sgn(hit.r.mwpa), tr, val("mwpa", hit.r.mwpa));
        el("td", "n", tr, val("impact", hit.m, MOVE));
        el("td", "n", tr, String(hit.r.i + 1));
      });
      if (!any) {
        var tr0 = el("tr", null, body);
        el("td", "na", tr0, EM + " none of the four played this match").colSpan = 4;
      }
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
      el("span", "who", b, who(s.p.name));
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

  /* ==== offense against defense ========================================== */
  /* ONE POINT PER PLAYER-MATCH, its attack half against its defense half. The
     two halves sum to that match's own MWPA — the mark the tracker above plots
     — so this figure is that mark taken apart and not a new quantity. A point's
     signed distance from the diagonal IS its MWPA.

     WHY THE BOX IS SQUARE AND THE AXES ARE SYMMETRIC. Both halves are the same
     unit measured on two halves of one match, so equal units in both directions
     is the only geometry in which x = -y is a true 45 degrees and each quadrant
     is a true quarter. The null is the centre of both.

     TWO LAYERS ON ONE PLANE, and they answer two questions. The marks answer WHICH MATCH
     and die in the middle, where the seasons overplot. The blob under them answers WHAT A
     PLAYER LOOKS LIKE — a soft field, densest where their matches pile up, fading to nothing
     where they have none. This replaced four binned small multiples: those answered the second
     question on a plane the reader had to carry the first question's shape across from memory,
     and a 4x4 grid was as fine as the smallest season could be cut before every cell was one
     match. A field has no cells to be too coarse.

     THE BLOB IS A SUM OF SPLATS, so the alpha is continuous and no contour level is a
     threshold anybody has to defend, and its bandwidth is pooled across all four for the
     reason the panels shared one ramp: a per-player bandwidth would draw the smoothing rather
     than the player. Four translucent fields over one plane are four fields over one plane, so
     the legend isolates, and isolating is how this figure is read. */
  function drawOffenseDefense(host) {
    var OD = (Q && Q.od) || (SITE && SITE.od) || null;
    if (!OD || !SITE || !SITE.players) return;

    var SHARE = ".0%";    /* the dict names no share; a fallback in the sense PCT and MOVE are */

    var series = [];
    SITE.players.forEach(function (p) {
      var rows = (OD[p.short] || []).filter(function (r) {
        return r && typeof r.a === "number" && typeof r.d === "number";
      });
      if (rows.length) series.push({ p: p, rows: rows, shape: SHAPE[p.short] || "circle" });
    });
    if (!series.length) return;

    /* THE AXIS IS scale.match_mwpa, the payload's fixed axis for one match's own
       MWPA — which is the unit both halves are measured in. Read, never
       recomputed (house rule 3), and used symmetrically about the null. Four of
       the 151 player-matches sit outside it; they are drawn as carets at the
       edge, exactly as the tracker draws the same fact, and counted in the
       description rather than quietly rescaling the box around them. */
    var AX = (typeof SCALE.match_mwpa === "number" && SCALE.match_mwpa > 0) ? SCALE.match_mwpa : 0;
    if (!AX) {
      series.forEach(function (s) {
        s.rows.forEach(function (r) { AX = Math.max(AX, Math.abs(r.a), Math.abs(r.d)); });
      });
    }
    if (!AX) return;

    var ATK = label("attack_mwpa", "Attack MWPA");
    var DEF = label("defense_mwpa", "Defense MWPA");
    /* "Attack MWPA" -> "attack": the side, taken off the dict label rather than
       written out here a second time. */
    function sideOf(lab) { return String(lab).split(" ")[0].toLowerCase(); }
    var A_ = sideOf(ATK), D_ = sideOf(DEF);

    var total = 0, off = 0;
    series.forEach(function (s) {
      s.rows.forEach(function (r) {
        total += 1;
        if (Math.abs(r.a) > AX || Math.abs(r.d) > AX) off += 1;
      });
    });
    function meanOf(s, key) {
      var sum = 0;
      s.rows.forEach(function (r) { sum += r[key]; });
      return sum / s.rows.length;
    }

    host.textContent = "";
    host.classList.add("fig", "od-fig");
    var only = "";

    /* The legend is one control for both figures below it, so it is built first
       and isolates a player in the scatter and the panels together. */
    var legend = el("div", "fig-legend", host);
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "Series, and a button to isolate each one");

    /* ---- the scatter ----------------------------------------------------- */
    var W = 640, ML = 66, MR = 24, MT = 34, MB = 54;
    var PW = W - ML - MR, PH = PW, H = MT + PH + MB;
    function X(v) { return ML + (v + AX) / (2 * AX) * PW; }
    function Y(v) { return MT + PH - (v + AX) / (2 * AX) * PH; }

    var plot = el("div", "od-plot", host);
    var svg = sv("svg", {
      class: "od-scatter", viewBox: "0 0 " + W + " " + H,
      preserveAspectRatio: "xMidYMid meet", role: "img", tabindex: "0"
    }, plot);
    var tId = uid("od"), dId = uid("od");
    svg.setAttribute("aria-labelledby", tId + " " + dId);
    sv("title", { id: tId }, svg).textContent =
      "Every match of every player: its " + A_ + " half across, its " + D_ + " half up, on one "
      + "symmetric axis with the null at the centre of both.";
    sv("desc", { id: dId }, svg).textContent = series.map(function (s) {
      return who(s.p.name) + ": " + s.rows.length + " matches, mean " + A_ + " "
        + val("attack_mwpa", meanOf(s, "a")) + ", mean " + D_ + " "
        + val("defense_mwpa", meanOf(s, "d")) + ".";
    }).join(" ") + " The two halves sum to the match's own " + label("mwpa", "MWPA") + ", so the "
      + "diagonal is every match worth " + val("mwpa", 0) + ". "
      + (off ? off + " of the " + total + " player-matches fall outside the axis and are drawn "
             + "as carets at its edge, pointing the way they went. " : "")
      + "The same matches are in the cross-tab below, with a link to each.";

    var g = sv("g", { class: "grid" }, svg);
    ticks(-AX, AX, 8).forEach(function (t) {
      if (!t) return;                    /* the null is drawn last, over everything */
      sv("line", { class: "gridline", x1: ML, x2: ML + PW, y1: Y(t), y2: Y(t) }, g);
      sv("line", { class: "gridline", y1: MT, y2: MT + PH, x1: X(t), x2: X(t) }, g);
      text(ML - 8, Y(t) + 3.5, val("defense_mwpa", t), "tick", g, "end");
      text(X(t), MT + PH + 18, val("attack_mwpa", t), "tick", g, "middle");
    });
    text(ML, MT - 14, DEF, "axis-title", g, "start");
    text(ML + PW, MT + PH + 38, ATK, "axis-title", g, "end");

    /* The locus of a match worth nothing. It is a property of the plane and not
       a fifth series, so it is a --rule hairline under every mark, labelled in
       the empty upper-left where no season lives. */
    sv("line", { class: "od-guide", x1: X(-AX), y1: Y(AX), x2: X(AX), y2: Y(-AX) }, g);
    text(ML + PW * 0.12 + 8, MT + PH * 0.12 + 16,
         A_ + " + " + D_ + " = " + val("mwpa", 0), "od-guide-lab", g, "start");

    /* What each corner means, in words, because a quadrant nobody names is a
       quadrant the reader has to derive from two axis titles every time. */
    var quad = sv("g", { class: "od-quad" }, svg);
    text(ML + 10, MT + 18, D_ + " up, " + A_ + " down", null, quad, "start");
    text(ML + PW - 10, MT + 18, "up on both sides", null, quad, "end");
    text(ML + 10, MT + PH - 10, "down on both sides", null, quad, "start");
    text(ML + PW - 10, MT + PH - 10, A_ + " up, " + D_ + " down", null, quad, "end");

    var nulls = sv("g", {}, svg);
    sv("line", { class: "axis-zero", x1: ML, x2: ML + PW, y1: Y(0), y2: Y(0) }, nulls);
    sv("line", { class: "axis-zero", y1: MT, y2: MT + PH, x1: X(0), x2: X(0) }, nulls);

    /* ---- the density, as a blob per player ------------------------------ */
    /* WHAT THE FOUR PANELS USED TO DO, done in place. A binned panel answered "what does this
       player look like" but could not be laid over the scatter, so the reader carried a shape
       between two figures by memory. This is the same question answered on the same plane: one
       soft field per player, densest where their matches pile up and fading to nothing where
       they have none, so a hill and a trough are visible without a grid to read them off.

       IT IS A SUM OF SPLATS, NOT A CONTOUR. Each match is one radial gradient from the
       player's hue at the centre to fully transparent at the bandwidth, and overlapping splats
       accumulate — which IS a kernel density estimate, drawn rather than computed. No contour
       levels means no threshold anybody has to defend, and the alpha is continuous, so the
       fade is the probability rather than a step in it.

       ONE BANDWIDTH FOR ALL FOUR, from the pooled spread, for the reason the panels shared one
       ramp: a per-player bandwidth would make a tight season and a loose one draw the same
       sized blob and the reader would be seeing the smoothing, not the player. Silverman on
       the pooled sample, floored so eight matches still read as a shape. */
    var pooled = [], bw;
    series.forEach(function (s) {
      s.rows.forEach(function (r) { pooled.push(r.a); pooled.push(r.d); });
    });
    (function () {
      var n = pooled.length, mean = 0, i;
      for (i = 0; i < n; i++) mean += pooled[i];
      mean /= n;
      var varsum = 0;
      for (i = 0; i < n; i++) varsum += (pooled[i] - mean) * (pooled[i] - mean);
      var sd = Math.sqrt(varsum / Math.max(1, n - 1));
      /* Silverman's rule on the pooled halves, in data units, then into view units. Floored at
         6% of the axis so the smallest season is a blob and not four dots with haloes. */
      bw = Math.max(1.06 * sd * Math.pow(n, -0.2), AX * 0.06);
    }());
    var bwPx = bw / (2 * AX) * PW * 1.9;   /* the splat reaches ~2 bandwidths before it dies */

    var defs = sv("defs", {}, svg);
    /* UNDER THE FURNITURE, and this is placement rather than paint order by accident: the
       group is created here but moved above the quadrant labels, the two null rules and every
       mark, so a translucent field never tints the words, never softens the value that means
       no claim, and never sits on top of a datum. */
    var gBlob = sv("g", { class: "od-blobs" }, svg);
    svg.insertBefore(gBlob, quad);
    series.forEach(function (s) {
      var id = uid("odk");
      var grad = sv("radialGradient", { id: id, class: "od-kernel p-" + s.p.short }, defs);
      /* The stops take the hue from the class on the gradient itself, so nothing here names a
         colour and the whole ramp moves with the theme. Three stops rather than two: a linear
         fade reads as a disc with an edge, and this reads as a field. */
      sv("stop", { offset: "0%", "stop-opacity": 0.36 }, grad);
      sv("stop", { offset: "45%", "stop-opacity": 0.13 }, grad);
      sv("stop", { offset: "100%", "stop-opacity": 0 }, grad);
      var gp = sv("g", { class: "od-blob p-" + s.p.short }, gBlob);
      s.rows.forEach(function (r) {
        var cx = Math.max(-AX, Math.min(AX, r.a)), cy = Math.max(-AX, Math.min(AX, r.d));
        sv("circle", { cx: X(cx), cy: Y(cy), r: bwPx, fill: "url(#" + id + ")" }, gp);
      });
    });
    /* The plot box clips them: a season near the edge would otherwise paint over the ticks. */
    var clip = uid("odc");
    sv("rect", { x: ML, y: MT, width: PW, height: PH },
       sv("clipPath", { id: clip }, defs));
    gBlob.setAttribute("clip-path", "url(#" + clip + ")");

    var marks = [];
    series.forEach(function (s) {
      var gp = sv("g", { class: "od-series p-" + s.p.short }, svg);
      s.rows.forEach(function (r) {
        var cx = Math.max(-AX, Math.min(AX, r.a)), cy = Math.max(-AX, Math.min(AX, r.d));
        var x = X(cx), y = Y(cy), ang;
        if (cx !== r.a || cy !== r.d) {
          /* Off the axis: the tracker's caret, turned to point the way the value
             went. A series marker sitting on the boundary would read as a match
             that stopped there, which is the one thing it must not say. */
          ang = Math.atan2(r.a - cx, r.d - cy) * 180 / Math.PI;
          sv("path", { class: "od-dot is-off", d: caretPath(x, y, 4.4, 1),
                       transform: "rotate(" + ang.toFixed(1) + " " + x + " " + y + ")" }, gp);
        } else {
          sv("path", { class: "od-dot", d: markerPath(s.shape, x, y, 3.6) }, gp);
        }
        marks.push({ s: s, r: r, x: x, y: y });
      });
    });
    var ring = sv("circle", { class: "od-focus", r: 9, visibility: "hidden" }, svg);

    var read = el("div", "fig-readout od-read", host);
    read.setAttribute("role", "status");
    read.setAttribute("aria-live", "polite");

    function quantity(key, v) {
      var w = el("span", "od-q", read);
      el("span", "od-k", w, label(key, key) + " ");
      el("span", "od-v " + sgn(v), w, val(key, v));
    }

    /* Stepping order is the attack axis, left to right. There is no time in this
       cloud, so the only order it suggests is the one you read it in. */
    var seq = marks.slice().sort(function (a, b) { return a.r.a - b.r.a; });
    var cur = null;
    function live() {
      return only ? seq.filter(function (m) { return m.s.p.short === only; }) : seq;
    }
    function restScatter() {
      /* An aria-live region that rewrites itself with the same sentence
         re-announces it, so rest is a no-op once it is already at rest. */
      if (!cur && read.firstChild) return;
      cur = null;
      ring.setAttribute("visibility", "hidden");
      svg.setAttribute("class", "od-scatter");
      read.textContent = "";
      el("p", "od-rest", read,
         "One point is one player's match. Right of the vertical null they gained on " + A_
         + ", above the horizontal null they gained on " + D_ + ", and the diagonal is a match "
         + "worth " + val("mwpa", 0) + ". Point at a match, or press Enter on one to open it.");
    }
    function show(m) {
      cur = m;
      ring.setAttribute("cx", m.x);
      ring.setAttribute("cy", m.y);
      ring.setAttribute("visibility", "visible");
      svg.setAttribute("class", "od-scatter is-live");
      read.textContent = "";
      var head = el("span", "od-q", read);
      el("b", "hue p-" + m.s.p.short, head, who(m.s.p.name));
      el("span", "od-k", head, " " + m.r.map + " · " + m.r.date
        + (typeof m.r.won === "boolean" ? " · " + (m.r.won ? "won" : "lost") : ""));
      quantity("attack_mwpa", m.r.a);
      quantity("defense_mwpa", m.r.d);
      quantity("mwpa", typeof m.r.m === "number" ? m.r.m : m.r.a + m.r.d);
    }
    function step(d) {
      var list = live(), i;
      if (!list.length) return;
      i = list.indexOf(cur);
      i = i < 0 ? (d > 0 ? 0 : list.length - 1)
                : Math.max(0, Math.min(list.length - 1, i + d));
      show(list[i]);
    }
    function openMatch() {
      if (cur && cur.r.id) location.href = (host.getAttribute("data-offdef") || "m/")
        + cur.r.id + ".html";
    }
    svg.addEventListener("pointermove", function (evt) {
      var box = svg.getBoundingClientRect(), k = box.width / W || 1;
      var vx = (evt.clientX - box.left) / k, vy = (evt.clientY - box.top) / k;
      var list = live(), best = null, near = 900, i, dx, dy, q;
      for (i = 0; i < list.length; i++) {
        dx = list[i].x - vx; dy = list[i].y - vy; q = dx * dx + dy * dy;
        if (q < near) { near = q; best = list[i]; }
      }
      if (best && best !== cur) show(best);
      else if (!best && cur) restScatter();
    });
    svg.addEventListener("pointerleave", restScatter);
    svg.addEventListener("blur", restScatter);
    svg.addEventListener("click", openMatch);
    svg.addEventListener("keydown", function (evt) {
      var d = evt.key === "ArrowRight" ? 1 : evt.key === "ArrowLeft" ? -1 : 0, list;
      if (d) { evt.preventDefault(); step(d); return; }
      if (evt.key === "Home" || evt.key === "End") {
        evt.preventDefault();
        list = live();
        if (list.length) show(evt.key === "Home" ? list[0] : list[list.length - 1]);
        return;
      }
      if (evt.key === "Enter") { evt.preventDefault(); openMatch(); }
    });

    /* The legend keys isolate a player — which on this figure is the whole reading, because
       four translucent fields over one plane are four fields over one plane. Each key carries
       that player's exposure and the mean of each half, which is where their blob is centred. */
    series.forEach(function (s) {
      var b = el("button", "legend-key p-" + s.p.short, legend), key;
      b.type = "button";
      b.setAttribute("aria-pressed", "false");
      key = sv("svg", { class: "swatch", viewBox: "0 0 26 14", "aria-hidden": "true" }, null);
      b.appendChild(key);
      sv("path", { class: "dot", d: markerPath(s.shape, 13, 7, 4.2) }, key);
      el("span", "who", b, who(s.p.name));
      el("span", "exposure", b, s.rows.length + " matches · " + A_ + " "
        + val("attack_mwpa", meanOf(s, "a")) + " · " + D_ + " "
        + val("defense_mwpa", meanOf(s, "d")));
      b.addEventListener("click", function () {
        var on = only === s.p.short;
        only = on ? "" : s.p.short;
        host.setAttribute("data-only", only);
        Array.prototype.forEach.call(legend.children, function (o) {
          o.setAttribute("aria-pressed", String(!on && o === b));
        });
        restScatter();
      });
    });

    restScatter();
  }

  /* THE MATCH FIGURE. One continuous match win probability curve; the vertical
     at a credited action IS that action's match impact, so the chart and the
     metric are one object.

     TWO X AXES, one toggle. Round mode is the payload's own continuous `x`,
     where every round is equal width. Time mode is the summed round clock. The
     toggle moves a datum's x and nothing else.

     ROUND WIN PROBABILITY IS NOT ON THIS FIGURE. Two probabilities in one
     readout, one of them scoped to a round that ends in seconds, made the
     reader decide which number the mark referred to. Everything here is in
     match win probability. */
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
      /* THE ANCHOR THE PAGE ACTUALLY PUBLISHES, which is `#rN` — build.py ids every panel
         `r<number>` and the round index links to that. This wrote `#round-N`, which resolved to
         no element on the page, so a copied URL landed nowhere and the browser had nothing to
         scroll to. Not written on the opening call: a plain load keeps a clean URL, and the
         fragment appears only once the reader has chosen a round. replaceState never fires
         hashchange, so the page's own controller is not re-entered. */
      if (!opening_) {
        try { history.replaceState(null, "", "#r" + n); } catch (e) {}
      }
    }

    /* Both spellings on the way IN, because the page links `#r7` and an older copied URL may
       say `#round-7`; an inbound link this missed would collapse the panels onto a round the
       reader did not ask for. `opening_` is true while the first, unasked-for selection runs. */
    var opening_ = false;
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
      opening_ = true; select(opening(), true); opening_ = false;
      return;
    }

    host.textContent = "";
    host.classList.add("fig", "fig-match");

    /* ---- the header ---------------------------------------------------- */
    /* Both teams named with their live percentage, updating on hover and
       showing the final at rest. HTML, not SVG text, so the numbers scale with
       the reader's font size and take the page's contrast tokens. */
    var head = el("div", "wp-head", host);
    var headTop = el("div", "wp-head-top", head);
    el("span", "lab", headTop, label("p", "Match win probability"));
    var headWhen = el("span", "wp-when", headTop, "");
    var teamRows = el("div", "wp-teams", head);

    /* THE SCORE MOVES WITH THE PROBABILITY. It was written once, at the final, while the
       percentage beside it tracked the pointer — so hovering round 4 of a 13-11 match printed
       `Blue 13 · 71.2%`, a scoreline that had not happened yet against a probability from
       before it did. Both now say the same moment. */
    function teamRow(team, cls) {
      var row = el("div", "wp-team " + cls, teamRows);
      el("span", "wp-name", row, team ? team.team_id : EM);
      var score = el("span", "wp-score", row, team ? String(team.rounds_won) : EM);
      var pct = el("b", "wp-pct", row, "");
      return { pct: pct, score: score, team: team };
    }
    var focalSide = teamRow(focal, "is-focal");
    var otherSide = teamRow(other, "is-other");
    var focalPct = focalSide.pct, otherPct = otherSide.pct;

    /* ---- geometry ------------------------------------------------------ */
    /* The reference component's defaults: margin 40 all round, 2/1 aspect. The
       viewBox is taller than the plot box by BELOW, because the bottom margin
       is fully spent by the tick row and the axis title sits under it. */
    var W = 960, H = 480, M = 40, BELOW = 18;
    var PW = W - M * 2, PH = H - M * 2;
    var VH = H + BELOW;
    /* The null comes from meta.gate, not from this file. Nothing in the view
       decides the value that means "no claim". */
    var TOP = M, BOT = M + PH;
    var EVEN = (META.gate && typeof META.gate.null_probability === "number")
      ? META.gate.null_probability : 0.5;

    /* ---- THE TWO X AXES ------------------------------------------------ */
    /* `t` is milliseconds from the START OF THE ROUND — meta.dict says so and
       the payload agrees, every round's first node is t 0 — so a match clock
       has to be summed. The summand is each round's horizon, its last node's
       `t`, which is exactly the denominator the payload's own `x` divides by:
       the two modes therefore agree on every round boundary, and the toggle
       moves a datum's x and never its value.

       ROUNDS ABUT. Nothing in the payload times the gap between a round ending
       and the next being priced, so a buy phase would be a duration this file
       invented. The axis is round clock, not wall clock, and it says so. */
    function buildClock() {
      var off = {}, dur = {}, total = 0;
      rounds.forEach(function (r) {
        var last = 0;
        (nodesBy[r.round_number] || []).forEach(function (n) { if (n.t > last) last = n.t; });
        off[r.round_number] = total;
        dur[r.round_number] = last;
        total += last;
      });
      return { off: off, dur: dur, total: total || 1 };
    }
    var CLOCK = buildClock();
    var MODE = "round";

    function Xn(n) {
      if (MODE === "time") return M + ((CLOCK.off[n.r] || 0) + n.t) / CLOCK.total * PW;
      return M + (n.x / R) * PW;
    }
    function Xb(i) {                                 // a round boundary, 0..R
      if (MODE !== "time") return M + (i / R) * PW;
      if (i >= R) return M + PW;
      return M + (CLOCK.off[rounds[i].round_number] || 0) / CLOCK.total * PW;
    }
    function Y(p) { return BOT - p * PH; }           // fixed 0..1 domain, never data-fitted
    /* m:ss. secs() stays what it is — meta.dict calls `t` time INTO the round
       and the readout means exactly that — but a match clock past ten minutes
       is not readable in tenths of a second. */
    function mmss(ms) {
      var s = Math.round(ms / 1000), r = s % 60;
      return Math.floor(s / 60) + ":" + (r < 10 ? "0" : "") + r;
    }

    /* WHICH OF THE FOUR ACTUALLY ACTED HERE. One list, read once, and the
       coloured verticals, the markers and the legend keys are all keyed off it,
       so the legend cannot name a hue the chart does not draw. */
    var actShorts = [], actWho = {}, actN = {};
    series.forEach(function (n) {
      if (n.kind !== "action") return;
      var p = byPuuid[n.actor];
      if (!p || !p.short) return;
      if (!actWho[p.short]) { actWho[p.short] = p; actN[p.short] = 0; actShorts.push(p.short); }
      actN[p.short] += 1;
    });
    /* THE INITIAL HAS TO BE UNIQUE OR IT IS NOT A CHANNEL. `themarias` and
       `trzzcko` both begin with a T, so a one-letter initial silently merged
       two of the four wherever both played. The shortest prefix that separates
       the players ACTUALLY on this figure is one letter on every match in the
       act and grows only if that pair ever share one. */
    var INIT = {};
    (function () {
      for (var len = 1; len <= 4; len++) {
        var seen = {}, clash = false, i;
        for (i = 0; i < actShorts.length; i++) {
          var k = actShorts[i].slice(0, len).toUpperCase();
          if (seen[k]) { clash = true; break; }
          seen[k] = 1;
        }
        if (!clash) {
          actShorts.forEach(function (s) { INIT[s] = s.slice(0, len).toUpperCase(); });
          return;
        }
      }
      actShorts.forEach(function (s) { INIT[s] = s.slice(0, 2).toUpperCase(); });
    })();

    /* ---- WHICH ACTIONS GET A MARK, decided once ------------------------- */
    /* THE TICK LEVEL IS GONE, and that is the readability fix. Measured over
       the 83 match payloads: a median match carries 174 credited actions, of
       which 26 are one of the four and 0 clear the payload's p99 gate — so 145
       of them, 83% of every mark on the figure, were 2px ticks at a median 3.5
       units apart on an 880-unit plot. That is a carpet, and it was drawing a
       fact the line already carries: an action's node and the clock node before
       it share an x, so THE VERTICAL IN THE LINE IS ALREADY THE MARK. Nothing
       measured was lost with them; every one of those actions is still on the
       curve, still in the tooltip, still a row in the table.

       Two levels remain, and the freed room pays for their size:
         filled hue mark + initial   one of the four
         hollow neutral ring         anyone else, past the payload's gate

       House rule 3 is untouched: the radius is |dp| against a FIXED axis the
       payload carries, so a mark of a given size means the same number of match
       win probability points on all 68 pages, and anything at or past the axis
       is clamped and ringed rather than allowed to grow. */
    var AXIS = markerAxis(), GATE_DP = markerGate();
    /* 2.6 / 9.0 / 4.6 before. The ratio is unchanged and so is the rule; only
       the room is new. R_FOCAL is a floor, not a size: an 11px initial needs
       about 13 units of mark to clear its own type, and a mark whose whole job
       is to say who did it that is too small to say who did it has failed.
       R_WIDE is that floor for a two-character initial. */
    var R_MIN = 4.0, R_MAX = 11.0, R_FOCAL = 6.6, R_WIDE = 8.4;
    function radius(dp) {
      if (!AXIS) return 6.0;
      return R_MIN + (R_MAX - R_MIN) * Math.sqrt(Math.min(1, Math.abs(dp) / AXIS));
    }
    function floorR(short) { return INIT[short] && INIT[short].length > 1 ? R_WIDE : R_FOCAL; }
    var marks = [], marked = 0, ringed = 0;
    series.forEach(function (n) {
      if (n.kind !== "action") return;
      var hue = hueOf(n.actor);
      var p = byPuuid[n.actor];
      if (!hue && !(GATE_DP && Math.abs(n.dp) >= GATE_DP)) return;
      marks.push({ n: n, hue: hue, r: Math.max(radius(n.dp), hue ? floorR(p.short) : 0),
                   init: hue ? INIT[p.short] : null,
                   over: !!(AXIS && Math.abs(n.dp) >= AXIS) });
      if (hue) marked += 1; else ringed += 1;
    });
    /* Biggest first, so the smallest lands on top. A third of adjacent marks
       graze at these sizes and a seventh cover each other's centre; painted
       this way the small one keeps its whole face and the large one loses an
       arc, which is the cheaper loss. Order is paint order only — the marks
       take no pointer events, nearest() does. */
    marks.sort(function (a, b) { return b.r - a.r; });

    /* ---- the control bar: what the line means, and what x measures ------ */
    var bar = el("div", "wpx-bar", host);
    var legend = el("div", "fig-legend is-static", bar);
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "What each part of the line means, and who moved it");
    /* Each swatch is drawn by the same class as the path it stands for, so the
       legend cannot drift away from the chart. The second phrase each key used
       to carry is gone: the dict label already names the claim, and the
       definition is on the node's own tooltip. */
    [["wp-line", label("kind_action", "Action") + " · " + label("kind_clock", "Clock")],
     ["wp-econ", label("kind_round_start", "Round start")],
     ["wp-term", label("kind_terminal", "Terminal")]].forEach(function (key) {
      var item = el("span", "legend-key is-static", legend);
      var sw = sv("svg", { class: "swatch wpfig", viewBox: "0 0 26 14", "aria-hidden": "true" }, item);
      sv("path", { class: key[0] + (key[0] === "wp-line" ? "" : " wp-free"), d: "M1 7h24" }, sw);
      el("span", "who", item, key[1]);
    });
    /* One key per focal player who acted. The swatch now draws BOTH channels
       the plot uses — the hued vertical and the marker with its initial in it —
       because the marker is the thing the reader was failing to read, and a key
       that shows only half of a mark teaches only half of it. */
    actShorts.forEach(function (s) {
      var item = el("span", "legend-key is-static p-" + s, legend);
      var sw = sv("svg", { class: "swatch wpx-key wpfig", viewBox: "0 0 34 20",
                           "aria-hidden": "true" }, item);
      sv("path", { class: "wp-line wp-act p-" + s, d: "M6 2v16" }, sw);
      sv("path", { class: "ev p-" + s, d: markerPath("circle", 22, 10, floorR(s)) }, sw);
      text(22, 13.8, INIT[s], "ev-init", sw, "middle");
      el("span", "who", item, who(actWho[s].name || s));
      el("span", "exposure", item, actN[s] + (actN[s] === 1 ? " action" : " actions"));
    });

    /* THE TOGGLE. Two states, two buttons, the page's own .chip vocabulary and
       aria-pressed — the same control the site uses everywhere else something
       is either on or off. */
    var modes = el("div", "wpx-modes", bar);
    modes.setAttribute("role", "group");
    modes.setAttribute("aria-label", "What the horizontal axis measures");
    /* Two literals, and they are the view's own words on purpose: meta.dict's
       `t` is time INTO a round, and the act has no entry for a summed match
       clock, so borrowing that label would name the axis wrongly. */
    var modeBtn = {};
    [["round", "Rounds"], ["time", "Time"]].forEach(function (m) {
      var b = el("button", "chip wpx-mode", modes, m[1]);
      b.type = "button";
      b.setAttribute("aria-pressed", m[0] === MODE ? "true" : "false");
      b.addEventListener("click", function () { setMode(m[0]); });
      modeBtn[m[0]] = b;
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

    /* The paint order IS the argument, so the groups are appended once, in it,
       and the five that depend on x are emptied and refilled by paint(). */
    var gGrid = sv("g", { class: "grid" }, svg);        // y only, drawn once
    var gBound = sv("g", { class: "bounds" }, svg);
    var gArea = sv("g", { class: "area" }, svg);
    var gNull = sv("g", { class: "null" }, svg);
    var band = sv("rect", { class: "wp-band", x: M, y: TOP, width: 0, height: PH }, svg);
    var gCurve = sv("g", { class: "curve" }, svg);
    var gMarks = sv("g", { class: "marks" }, svg);
    var gClose = sv("g", { class: "closes" }, svg);

    /* ---- grid: horizontal only, five rows ------------------------------ */
    var gi;
    for (gi = 0; gi < 5; gi++) {
      var gp = gi / 4, gy = Y(gp);
      /* The null is NOT drawn here. It is the heaviest horizontal on the figure
         and it is drawn after the wash and before the curve. */
      if (gp === EVEN) continue;
      sv("line", { class: "gridline", x1: M, x2: M + PW, y1: gy, y2: gy }, gGrid);
      text(M + 3, gy - 4, num(gp, PCT), "tick", gGrid, "start");
    }

    /* ---- THE NULL, second instance ------------------------------------- */
    /* meta.gate.null_probability: the point at which we cannot say who wins.
       Full-strength ink, heavier than any datum, over the wash and UNDER the
       curve — drawn last it would erase the data it is judging at exactly the
       moment the match was closest to even. It carries no label: every match
       opens here, so the words sat under the line on most pages. */
    sv("line", { class: "even", x1: M, x2: M + PW, y1: Y(EVEN), y2: Y(EVEN) }, gNull);

    /* ---- the side switches, which do not depend on the axis ------------- */
    var swAt = [];
    rounds.forEach(function (r, i) {
      var next = rounds[i + 1];
      if (!next || !sideBy[r.round_number] || sideBy[r.round_number] === sideBy[next.round_number]) return;
      swAt.push(i + 1);
    });
    var regulation = swAt.length ? [swAt[0]] : [];
    var overtime = swAt.slice(1);
    var opensOn = sideBy[rounds[0].round_number];

    /* ---- everything that depends on which axis is showing --------------- */
    function paintBounds() {
      gBound.textContent = "";
      var k;
      /* 4px ticks, down from 7. Every round boundary is drawn in both modes —
         in time mode their spacing IS the finding — but at 7px against a
         labelled tick they were a picket fence competing with the data. */
      for (k = 0; k <= R; k++) {
        sv("line", { class: "bound", x1: Xb(k), x2: Xb(k), y1: BOT, y2: BOT + 4 }, gBound);
      }
      if (MODE === "time") {
        /* The axis is a clock, so it is ticked in minutes and NOT in round
           numbers: a four-second round is three units wide here and a number
           under it would be a label pointing at nothing. Which round the reader
           is on comes from the band, the crosshair and the readout, all of
           which are correct in both modes. */
        ticks(0, CLOCK.total / 60000, 6).forEach(function (mn) {
          var x = M + (mn * 60000) / CLOCK.total * PW;
          if (x < M - 1 || x > M + PW + 1) return;
          sv("line", { class: "bound wpx-major", x1: x, x2: x, y1: BOT, y2: BOT + 9 }, gBound);
          text(x, BOT + 22, mmss(mn * 60000), "tick", gBound, "middle");
        });
      } else {
        var stepR = Math.max(1, Math.round(R / 12));
        rounds.forEach(function (r, j) {
          if (j % stepR !== 0 && j !== R - 1) return;
          text((Xb(j) + Xb(j + 1)) / 2, BOT + 22, String(r.round_number), "tick", gBound, "middle");
        });
      }
      /* One full-height rule for the regulation side switch, because it is the
         one boundary a reader cannot infer from the line. Overtime alternates
         sides EVERY round, so six more verticals would say nothing a bracket
         under the axis does not; the bracket is drawn once and counted. */
      regulation.forEach(function (j) {
        sv("line", { class: "switch", x1: Xb(j), x2: Xb(j), y1: TOP, y2: BOT }, gBound);
        text(Xb(j), TOP - 8, "sides swap", "switch-lab", gBound, "middle");
      });
      if (overtime.length) {
        var x0 = Xb(overtime[0]), x1 = Xb(R);
        sv("path", { class: "ot-bracket",
                     d: "M" + x0 + " " + (BOT + 30) + "v6h" + (x1 - x0) + "v-6" }, gBound);
        text((x0 + x1) / 2, BOT + 46, "overtime · sides swap every round · "
          + overtime.length + " more", "switch-lab", gBound, "middle");
      }
      /* The axis names its own unit and nothing else. In time mode it used to also explain
         that the buy phases are untimed and that the rounds therefore abut, which ran the line
         past the right edge of the viewBox on every match — a caption that clipped itself. The
         fact survives on the <desc>, where a reader who cannot see the spacing needs it. */
      text(M, BOT + 46, (MODE === "time"
          ? mmss(CLOCK.total) + " of round clock, rounds at their real length"
          : R + " rounds, equal width")
        + (opensOn ? " · " + focal.team_id + " opens on " + opensOn : "")
        + " · " + swAt.length + (swAt.length === 1 ? " side switch" : " side switches"),
        "axis-title", gBound, "start");
    }

    function paintCurve() {
      gArea.textContent = "";
      gCurve.textContent = "";
      gClose.textContent = "";
      /* ONE neutral wash between the curve and the null, on both sides. It
         carries no side meaning: it means distance from the null, which is the
         thing this figure is about. */
      var areaD = "M" + Xn(series[0]) + " " + Y(EVEN);
      series.forEach(function (n) { areaD += "L" + Xn(n) + " " + Y(n.p); });
      areaD += "L" + Xn(series[series.length - 1]) + " " + Y(EVEN) + "Z";
      sv("path", { class: "area-wash", d: areaD }, gArea);

      /* THREE paths, because the line makes three different claims and two of
         them land on the same pixel column.
           wp-line  solid. The part a player did: the round opens, the clock
                    drifts, actions jump.
           wp-term  the model's own calibration gap at the terminal.
           wp-econ  the buy, priced before anyone acts.
         Every terminal shares its x with the round's last action, so the
         terminal gap is always vertical and always at the round boundary,
         exactly where the NEXT round's economy move is drawn. One dashed path
         for both rendered the boundary as a single move of unattributable
         value; they are separated here, and a short rule at the resolved value
         marks where one hands over to the other. */
      var lineD = "", econD = "", termD = "", closeD = "";
      series.forEach(function (n, i) {
        var prev = i ? series[i - 1] : null;
        if (n.kind === "round_start") {
          /* Round one opens at W(0,0); dp measures back to it, so the first
             economy move is drawn from a value the payload carries rather than
             from an assumed 50%. */
          var from = prev ? prev.p : n.p - n.dp;
          econD += "M" + Xn(n) + " " + Y(from) + "L" + Xn(n) + " " + Y(n.p);
          lineD += "M" + Xn(n) + " " + Y(n.p);
        } else if (n.kind === "terminal") {
          if (prev) termD += "M" + Xn(prev) + " " + Y(prev.p) + "L" + Xn(n) + " " + Y(n.p);
          closeD += "M" + (Xn(n) - 4) + " " + Y(n.p) + "h8";
        } else {
          lineD += (lineD ? "L" : "M") + Xn(n) + " " + Y(n.p);
        }
      });
      sv("path", { class: "wp-free wp-term", d: termD }, gCurve);
      sv("path", { class: "wp-free wp-econ", d: econD }, gCurve);
      sv("path", { class: "wp-line", d: lineD }, gCurve);

      /* THE SAME LINE, HUED WHERE ONE OF THE FOUR MOVED IT. dP/dq == L to
         3.6e-11, so the vertical AT an action is that action's match impact
         drawn to scale; colouring the jump itself puts the hue on the quantity
         instead of on a disc beside it. A segment is only drawn where dp is
         non-zero — a zero-length vertical under a round linecap renders as a
         dot on a value nobody moved. */
      var actD = {};
      series.forEach(function (n) {
        if (n.kind !== "action" || !n.dp) return;
        var p = byPuuid[n.actor];
        if (!p || !p.short) return;
        actD[p.short] = (actD[p.short] || "")
          + "M" + Xn(n) + " " + Y(n.p - n.dp) + "L" + Xn(n) + " " + Y(n.p);
      });
      actShorts.forEach(function (s) {
        if (actD[s]) sv("path", { class: "wp-line wp-act p-" + s, d: actD[s] }, gCurve);
      });

      /* Last, so it is not buried: a terminal shares its x with the round's
         last action and usually its value too, so this rule would otherwise sit
         under that action's marker. */
      sv("path", { class: "wp-free wp-close", d: closeD }, gClose);
    }

    function paintMarks() {
      gMarks.textContent = "";
      marks.forEach(function (m) {
        var n = m.n, x = Xn(n), y = Y(n.p), shape = evShape(n.type);
        sv("path", {
          class: "ev " + n.type + m.hue + (n.actor ? (m.hue ? "" : " other") : " no-actor")
            + (m.over ? " over" : ""),
          d: markerPath(shape, x, y, m.r)
        }, gMarks);
        /* The initial, on EVERY focal mark now that the floor guarantees the
           room. It is the figure's only per-player secondary channel and the
           palette measures 10.2 at deutan — the hue is legal ONLY because this
           channel exists. A triangle carries its mass low, so its glyph sits
           lower in the shape; everything else is centred on the mark. */
        if (!m.init) return;
        text(x, y + (shape === "triangle" ? 4.4 : 3.8), m.init, "ev-init", gMarks, "middle");
      });
    }

    function paint() { paintBounds(); paintCurve(); paintMarks(); }

    function setMode(m) {
      if (m === MODE || !modeBtn[m]) return;
      MODE = m;
      modeBtn.round.setAttribute("aria-pressed", MODE === "round" ? "true" : "false");
      modeBtn.time.setAttribute("aria-pressed", MODE === "time" ? "true" : "false");
      paint();
      if (selected !== null) placeBand(selected);
      /* The reader keeps the node they were on. Only its x moved, so refocusing
         the same index is the whole update — nothing is recomputed from a
         value. */
      var keep = at;
      at = -1;
      if (keep >= 0) focusAt(keep); else blurAll();
    }

    /* ---- THE RISER ------------------------------------------------------ */
    /* At the selected action the vertical move is drawn as an engineering
       dimension line: serifs at both ends, the value in a box on a leader. On
       any other site a chart is a view of a metric and a dimension line would be
       decoration. Here an action's dp is its ledger credit times leverage to
       2.0e-16 over 10,113 nodes — the chart and the metric are the same object,
       and this is the only mark that says so. */
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
      var x = Xn(n), y0 = Y(n.p - n.dp), y1 = Y(n.p);
      var mid = (y0 + y1) / 2;
      var side = x > M + PW * 0.72 ? -1 : 1;
      var lead = x + side * 16;
      var lab = move("dp", n.dp, MOVE);
      var w = lab.length * 6.6 + 10;
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
      riserVal.textContent = lab;
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

    /* THE NODE TABLE UNDER THE FIGURE IS GONE. It listed the selected round node by node —
       which is exactly what the round panel below already does, from build.py, in the emitted
       HTML, with the site's own three-state signed cells and without a script. Two tables of
       one round with different columns, a different row filter and a different rendering of an
       exact zero is how two views of one number stop agreeing. The figure selects the panel;
       the panel is the table. */

    /* ---- text ---------------------------------------------------------- */
    function fmtActor(puuid) {
      var p = byPuuid[puuid];
      if (!p) return EM;
      return who(p.name) + (p.agent ? " (" + p.agent + ")" : "");
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
    /* What a node is, in the payload's own words. meta.dict names all four kinds and defines
       them; the view adds only what the node itself measured — the event type, the terminal,
       and who won the round. The terminal keeps its token lowercase, because the round panel's
       own facts line prints `Won by Blue · timer expired`. */
    function happened(n) {
      if (n.kind === "action") return typeLabel(n.type);
      if (n.kind === "terminal") {
        return label("kind_terminal", "Terminal") + " · "
          + (n.terminal_type ? humanize(n.terminal_type) : EM)
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
      /* The score entering the node's own round, or the final at rest. A team the payload
         does not carry keeps its em dash in both states. */
      var r = n && roundBy[n.r];
      focalSide.score.textContent = !focalSide.team ? EM
        : String(r ? r.own : focal.rounds_won);
      otherSide.score.textContent = !otherSide.team ? EM
        : String(r ? r.other : other.rounds_won);
      headWhen.textContent = n
        ? "Round " + n.r + " · " + secs(n.t)
        : "Final · " + MATCH.map + ", " + longDay(MATCH.started_at);
    }

    function restText() {
      readout.textContent = "";
      el("span", null, readout,
        "Point at the line. Click or Enter opens that round; arrows step it.");
    }

    /* ROUND WIN PROBABILITY IS GONE FROM THIS SENTENCE, as it is from the
       tooltip and the table. Two probabilities in one line left the reader
       deciding which one the mark under their cursor referred to; the figure is
       in match win probability and now says only that. */
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
      el("span", null, readout, " · " + val("p", n.p, PCT) + " · ");
      el("span", sgnOf("dp", n.dp, MOVE), readout, move("dp", n.dp, MOVE));
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
        var w = el("div", "wp-tip-who", tip);
        if (n.actor) el("span", ("hue" + hueOf(n.actor)).trim(), w, fmtActor(n.actor));
        else el("span", "na", w, EM + " no actor");
        if (n.victim) el("span", null, w, " → " + fmtActor(n.victim));
      } else if (n.kind === "round_start") {
        el("div", "wp-tip-who na", tip, EM + " the economy, not a player");
      } else if (n.kind === "terminal") {
        el("div", "wp-tip-who na", tip, EM + " booked to a team side, not a player");
      }
      var rws = el("dl", "wp-tip-rows", tip);
      function row(k, v, cls) {
        var d = el("div", null, rws);
        el("dt", null, d, k);
        el("dd", cls || null, d, v);
      }
      row(label("p", "Match win"), val("p", n.p, PCT));
      row(label("dp", "Move"), move("dp", n.dp, MOVE), sgnOf("dp", n.dp, MOVE));
      var r = roundBy[n.r];
      if (r) row(label("leverage", "Leverage"), val("leverage", r.leverage)
        + " (" + val("li", r.li, LI) + "×)");
    }

    function placeTip(n) {
      var box = plot.getBoundingClientRect();
      var svgBox = svg.getBoundingClientRect();
      var scale = svgBox.width / W || 1;
      var left = (svgBox.left - box.left) + Xn(n) * scale;
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
      crossX.setAttribute("x1", Xn(n));
      crossX.setAttribute("x2", Xn(n));
      crossDot.setAttribute("cx", Xn(n));
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

    /* Snap to the nearest node: x first, because the axis is time either way,
       then the closest of the handful that share that x — which is what makes
       the top and the bottom of an action's vertical jump separately reachable.
       Xn is monotone in both modes, so the search is unchanged by the toggle. */
    function nearest(px, py) {
      var lo = 0, hi = series.length - 1, mid;
      while (lo < hi) {
        mid = (lo + hi) >> 1;
        if (Xn(series[mid]) < px) lo = mid + 1; else hi = mid;
      }
      var best = lo, bestD = Infinity;
      for (var i = Math.max(0, lo - 8); i < Math.min(series.length, lo + 9); i++) {
        var dx = Xn(series[i]) - px, dy = Y(series[i].p) - py;
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
    function placeBand(n) {
      var i = rounds.map(function (r) { return r.round_number; }).indexOf(n);
      if (i < 0) return;
      var x0 = Xb(i), x1 = Xb(i + 1);
      band.setAttribute("x", x0);
      /* A floor of 2, because this band is a locator for the ledger below and
         is documented as not being a value: in time mode a four-second round is
         three units wide and a reader who cannot see where they are has lost
         the control. */
      band.setAttribute("width", Math.max(2, x1 - x0));
    }
    chart = { select: placeBand };

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
       is otherwise carried by colour alone. */
    dsc.textContent = "The line starts at " + num(series[0].p - series[0].dp, PCT)
      + " and ends at " + num(finalP, PCT) + "; " + focal.team_id + " won " + focal.rounds_won
      + " rounds against " + (other ? other.rounds_won : EM) + ". "
      + series.filter(function (n) { return n.kind === "action"; }).length
      + " credited actions sit on the line as verticals, each one that action's match "
      + "impact drawn to scale. " + marked + " are marked, drawn in that player's hue with "
      + "their initial in the mark, and " + ringed + " by anyone else above the act's top "
      + "hundredth as a hollow ring."
      + (actShorts.length ? " Marked for " + actShorts.map(function (s) {
          return who(actWho[s].name || s) + " (" + actN[s] + ")";
        }).join(", ") + "." : "")
      + (biggest ? " Largest single move: a " + biggest.type + " in round " + biggest.r
          + ", " + num(biggest.dp, MOVE) + "." : "")
      + " The horizontal axis is round number by default and can be switched to "
      + mmss(CLOCK.total) + " of summed round clock."
      + " Selecting a round opens that round, node by node, in the panel below."
      + " The x axis can be read two ways: every round at equal width, or at its real length"
      + " on the round clock, in which case the rounds abut, because nothing in this data"
      + " times a buy phase.";

    /* ---- wire up ------------------------------------------------------- */
    paint();
    tabs = wireTabs(host, rounds, function (n) { select(n, false); });
    paintHead(null);
    restText();
    opening_ = true; select(opening(), true); opening_ = false;
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
     heading is its button, so "which of these were close" is still
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
      /* The two text keys sort as text; everything else is a number. `map` joined them when
         the date came out of the match cell and got a column of its own. */
      if (key === "player") return tr.getAttribute("data-player") || "";
      if (key === "date") return tr.getAttribute("data-date") || "";
      if (key === "map") return tr.getAttribute("data-map") || "";
      /* A MISSING ATTRIBUTE IS NOT A ZERO. The cross-tab has an empty cell
         wherever a player did not play a match, and `Number(null)` is 0 —
         which would file thirty matches TheMarias was never in among the ones
         where she was measured at nothing. Absent returns NaN and sortBy files
         it last in both directions, so the empty cells leave the sort rather
         than joining it at the null. */
      var raw = tr.getAttribute("data-" + key);
      return raw === null ? NaN : Number(raw);
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
        var xg = x !== x, yg = y !== y;   /* NaN: this player was not in this match */
        if (xg || yg) return xg && yg ? 0 : xg ? 1 : -1;
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
       to be the row at the bottom of the table. The sort runs here rather
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
    var o = document.querySelector("[data-offdef]");
    if (o) drawOffenseDefense(o);
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
