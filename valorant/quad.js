/* Four-player E11A4 view.
 *
 * WHY A SCATTER AND A ROLLING MEAN, NOT A CUMULATIVE RATE.
 * A cumulative per-100 rate is a lifetime average: by round 1,198 SN0RLAX's number cannot move,
 * so the line stops being about what is happening and becomes an artefact of how long he has
 * played. The scatter shows every round's actual credit; the line is a trailing mean over a
 * window you can change.
 *
 * WHAT THE LINE IS NOT. Per-round RWPA has sd 0.211 against a mean of +0.010 -- the round-level
 * noise is roughly twenty times the season signal. A 50-round window still carries a standard
 * error near +/-3.0 per 100, and the gap between the highest and lowest season rate here is
 * 0.72 per 100. So the wiggles are not form. The line answers "roughly where has this sat
 * lately", and nothing finer than that.
 *
 * DISJOINT LINES. A player's series exists only over rounds they played. Totals carry across an
 * absence; strokes do not. A window is only drawn once it is actually full.
 *
 * Nothing here ranks players.
 */
(function () {
  "use strict";
  var D = window.QUAD_DATA;
  if (!D) return;

  var COLOR = { martin: "--martin", snorlax: "--snorlax", themarias: "--themarias", trzzcko: "--trzzcko" };
  var SHORT = { martin: "Martin", snorlax: "SN0RLAX", themarias: "TheMarias", trzzcko: "Trzzcko" };
  var CT_LABEL = { kill_credit: "Kill credit", death_debit: "Death debit", plant: "Plant",
                   defuse: "Defuse", alive_clock: "Clock", duels: "Duels (kills − deaths)" };
  var ids = D.players.map(function (p) { return p.id; });
  var HALFLIFE = 25;   // rounds; weight halves every HALFLIFE rounds back
  /* Effective sample size of an exponential weighting with half-life h is (1+L)/(1-L) for
     L = 2^(-1/h), which is about 2.9h -- so a half-life of 50 rounds carries the precision of
     roughly 2.9x its span, against 1x for a flat window. Numbers below are
     sd/sqrt(ESS) at the measured per-round sd of 0.211, in per-100 units. */
  var SE_AT = { 25: 2.48, 50: 1.75, 100: 1.24 };

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function fmt(x, d) { return (x >= 0 ? "+" : "") + Number(x).toFixed(d === undefined ? 2 : d); }
  function sv(tag, a) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in a) if (a[k] !== null && a[k] !== undefined) n.setAttribute(k, a[k]);
    return n;
  }

  /* Every round of every match, solo queues included. */
  var SHARED = D.matches;
  var TL = [];
  SHARED.forEach(function (m) { m.rounds.forEach(function (r) { TL.push({ m: m, r: r }); }); });

  /* Scope is an X-AXIS CUT ONLY. The decayed mean below always walks a player's entire history,
     so switching scope never changes a number -- it changes where the drawing starts. Cutting
     the data instead would silently restate every value, which is the trap this avoids. */
  var FIRST = {};
  TL.forEach(function (t, i) {
    for (var k in t.r.p) if (FIRST[k] === undefined) FIRST[k] = i;
  });
  var SCOPES = [
    { id: "all", label: "All rounds", from: function () { return 0; } },
    { id: "martin", label: "From Martin's first", from: function () { return FIRST.martin || 0; } },
    { id: "trzzcko", label: "From Trzzcko's first", from: function () { return FIRST.trzzcko || 0; } },
  ];
  var SCOPE = "all";
  function scopeStart() {
    var s0 = SCOPES.filter(function (s) { return s.id === SCOPE; })[0];
    return s0 ? s0.from() : 0;
  }

  /* Index of every shared round, so a full-history walk knows which of its steps are drawable. */
  var TL_AT = {};
  TL.forEach(function (t, i) { TL_AT[t.m.i + ":" + t.r.r] = i; });

  /* FULL[pid] is every round that player played across ALL 65 matches, in play order -- including
     the solo queues the chart does not draw. The decayed mean is fed by all of it: a round still
     tells you something about a player's form even when nobody was there to be compared with.
     `i` is the position in the shared timeline, or null when the round is not drawn. */
  var FULL = {};
  ids.forEach(function (pid) {
    FULL[pid] = [];
    D.matches.forEach(function (m) {
      m.rounds.forEach(function (r) {
        var e = r.p[pid];
        if (e) FULL[pid].push({ i: TL_AT[m.i + ":" + r.r], v: e.t });
      });
    });
  });

  /* per player: the drawable rounds, as {i, v} against the shared-timeline index */
  var PTS = {};
  ids.forEach(function (pid) {
    PTS[pid] = FULL[pid].filter(function (q) { return q.i !== undefined; });
  });

  /* Exponentially decayed mean over the player's ENTIRE history to that point, half-life h.
     Bias-corrected: both numerator and denominator decay, so this is a true weighted mean from
     the very first round rather than something that has to warm up from zero.
     Nothing is drawn until the release's own exposure floor is met -- a decayed mean over four
     rounds is still a mean over four rounds. */
  function decayed(pid, h) {
    var lam = Math.pow(2, -1 / h), num = 0, den = 0, out = [];
    var floor = D.min_rounds_for_rate || 20;
    FULL[pid].forEach(function (q, j) {
      num = num * lam + q.v;
      den = den * lam + 1;
      if (q.i !== undefined && j + 1 >= floor) out.push({ i: q.i, y: 100 * num / den });
    });
    return out;
  }

  function drawChart() {
    var host = document.getElementById("quad-chart");
    if (!host) return;
    host.textContent = "";

    var W = 940, H = 400, ML = 54, MR = 132, MT = 16, MB = 42;
    var n = TL.length;
    var i0 = scopeStart();                 // first round drawn; values are unaffected
    var span = Math.max(n - 1 - i0, 1);

    var lines = {};
    ids.forEach(function (p) { lines[p] = decayed(p, HALFLIFE); });

    /* Scale to the LINES, not the scatter. Single-round RWPA ranges past +/-70 per 100 while
       every trailing mean sits inside a few points of zero, so scaling to the dots squeezes the
       lines into an unreadable band -- the figure would spend its whole height on outliers.
       The frame is the line range with generous headroom; dots outside it are clipped, and the
       count of clipped rounds is printed so nothing is silently dropped. */
    var lmin = Infinity, lmax = -Infinity;
    ids.forEach(function (p) {
      lines[p].forEach(function (q) {
        if (q.i < i0) return;
        if (q.y < lmin) lmin = q.y; if (q.y > lmax) lmax = q.y;
      });
    });
    if (!isFinite(lmin)) { lmin = -1; lmax = 1; }
    /* Frame the trailing means and nothing else. Single rounds reach past +/-70 per 100; letting
       them set the scale flattens every line into one band and hides the differences the chart
       exists to show. Dots outside are clipped and counted on the axis. */
    /* NB: not `span` -- that name is the x-axis round range above, and `var` gives them one
       binding. Overwriting it put every tick past the first at x = 28132 in a 940-wide box. */
    var ySpan = Math.max(lmax - lmin, 0.5), padY = ySpan * 0.14;
    var lo = lmin - padY, hi = lmax + padY;
    var clipped = 0;
    ids.forEach(function (p) {
      PTS[p].forEach(function (q) {
        if (q.i < i0) return;
        var v = 100 * q.v; if (v < lo || v > hi) clipped++;
      });
    });

    var x = function (i) { return ML + (i - i0) * (W - ML - MR) / span; };
    var y = function (v) { return MT + (hi - v) * (H - MT - MB) / (hi - lo || 1); };

    var svg = sv("svg", { viewBox: "0 0 " + W + " " + H, class: "quad-chart", role: "img",
      "aria-label": "Each round's win probability added for four players across " + n +
        " rounds, with an exponentially decayed mean per player at a " + HALFLIFE +
        "-round half-life." });
    var defs = sv("defs", {});
    var cp = sv("clipPath", { id: "plotclip" });
    cp.appendChild(sv("rect", { x: ML, y: MT, width: W - ML - MR, height: H - MT - MB }));
    defs.appendChild(cp);
    svg.appendChild(defs);

    for (var g = 0; g <= 5; g++) {
      var vv = lo + (hi - lo) * g / 5;
      svg.appendChild(sv("line", { class: "gridline", x1: ML, x2: W - MR, y1: y(vv), y2: y(vv) }));
      var t = sv("text", { class: "tick", x: ML - 8, y: y(vv) + 4, "text-anchor": "end" });
      t.textContent = vv.toFixed(0);
      svg.appendChild(t);
    }
    if (lo < 0 && hi > 0) svg.appendChild(sv("line", { class: "zero", x1: ML, x2: W - MR, y1: y(0), y2: y(0) }));
    svg.appendChild(sv("line", { class: "axis", x1: ML, x2: W - MR, y1: H - MB, y2: H - MB }));

    var acc = 0;
    SHARED.forEach(function (m, mi) {
      acc += m.rounds.length;
      if (mi < SHARED.length - 1 && acc < n && acc > i0)
        svg.appendChild(sv("line", { class: "matchsep", x1: x(acc), x2: x(acc), y1: MT, y2: H - MB }));
    });

    [i0, i0 + Math.floor(span / 3), i0 + Math.floor(2 * span / 3), n - 1].forEach(function (i) {
      var t = sv("text", { class: "tick", x: x(i), y: H - MB + 16, "text-anchor": "middle" });
      t.textContent = String(i + 1);
      svg.appendChild(t);
    });
    var xl = sv("text", { class: "tick", x: (ML + W - MR) / 2, y: H - 6, "text-anchor": "middle" });
    xl.textContent = "round, in play order across the act · dots are single rounds, lines " +
      "are a decayed mean, half-life " + HALFLIFE + " rounds" +
      (clipped ? " · " + clipped + " rounds fall outside this frame" : "");
    svg.appendChild(xl);

    var band = sv("rect", { class: "sel-band", x: -99, y: MT, width: 0, height: H - MT - MB });
    svg.appendChild(band);

    // scatter first, so the means read on top
    ids.forEach(function (pid) {
      var col = css(COLOR[pid]);
      var g = sv("g", { class: "scatter", "clip-path": "url(#plotclip)" });
      PTS[pid].forEach(function (q) {
        if (q.i < i0) return;
        g.appendChild(sv("circle", { cx: x(q.i), cy: y(100 * q.v), r: 1.5, fill: col }));
      });
      svg.appendChild(g);
    });

    // trailing means, broken wherever the player's own rounds are not adjacent in global index
    ids.forEach(function (pid) {
      var col = css(COLOR[pid]), pts = lines[pid], seg = [];
      var flush = function () {
        if (seg.length > 1) {
          svg.appendChild(sv("path", { class: "seg", stroke: col,
            d: seg.map(function (q, j) { return (j ? "L" : "M") + x(q.i) + " " + y(q.y); }).join(" ") }));
        } else if (seg.length === 1) {
          svg.appendChild(sv("circle", { class: "dot", cx: x(seg[0].i), cy: y(seg[0].y), r: 2.4, fill: col }));
        }
        seg = [];
      };
      /* Break on a gap in the GLOBAL round index, not the player's own index. Consecutive
         own-rounds either side of an absence are adjacent to the player but separated by every
         round they missed, and joining them draws a slope across matches they never played. */
      var prevI = null;
      pts.forEach(function (q) {
        if (q.i < i0) return;                       // scope cut: drawn range only
        if (prevI !== null && q.i !== prevI + 1) flush();
        seg.push(q); prevI = q.i;
      });
      flush();
    });

    var start = 0;
    SHARED.forEach(function (m) {
      if (start + m.rounds.length <= i0) { start += m.rounds.length; return; }
      var w = Math.max(x(start + m.rounds.length) - x(start), 2);
      var r = sv("rect", { class: "hit", x: x(start), y: MT, width: w, height: H - MT - MB,
        tabindex: "0", role: "button",
        "aria-label": "Match " + (m.i + 1) + ", " + m.map + ", " + m.rounds.length + " rounds" });
      r.addEventListener("click", function () { location.hash = "#/m/" + m.i; });
      r.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); location.hash = "#/m/" + m.i; }
      });
      svg.appendChild(r);
      start += m.rounds.length;
    });

    /* ---- end labels: who the line is, and where it finished ---- */
    /* Placed at each series' last point so a reader never has to trace a colour back to a
       legend. Collisions are nudged apart vertically rather than overlapped. */
    var ends = [];
    ids.forEach(function (pid) {
      var pts = lines[pid];
      if (!pts.length) return;
      var last = pts[pts.length - 1];
      ends.push({ pid: pid, x: x(last.i), y: y(last.y), v: last.y });
    });
    ends.sort(function (a, b) { return a.y - b.y; });
    /* Each label is two lines (name, then value), so the minimum separation is the height of
       both plus a gap -- 15px let the value of one sit on the name of the next. */
    var LABEL_H = 27;
    for (var e2 = 1; e2 < ends.length; e2++) {
      if (ends[e2].y - ends[e2 - 1].y < LABEL_H) ends[e2].y = ends[e2 - 1].y + LABEL_H;
    }
    // if nudging pushed the stack past the plot, shift the whole stack back up
    var overflow = ends.length ? (ends[ends.length - 1].y + 12) - (H - MB) : 0;
    if (overflow > 0) ends.forEach(function (e) { e.y -= overflow; });
    ends.forEach(function (e) {
      var col = css(COLOR[e.pid]);
      svg.appendChild(sv("circle", { cx: e.x, cy: y(e.v), r: 3, fill: col }));
      svg.appendChild(sv("line", { class: "endlead", x1: e.x + 4, x2: W - MR + 6,
                                   y1: y(e.v), y2: e.y, stroke: col }));
      var t1 = sv("text", { class: "endlab", x: W - MR + 10, y: e.y - 1, fill: col });
      t1.textContent = SHORT[e.pid];
      svg.appendChild(t1);
      var t2 = sv("text", { class: "endval", x: W - MR + 10, y: e.y + 11 });
      /* Say "latest": this is where the trailing mean ended, not the season rate on the cards
         above, and the two differ by design. Martin finishes at +0.6 here against +1.2 there. */
      t2.textContent = fmt(e.v, 1) + " latest";
      svg.appendChild(t2);
    });

    /* ---- hover: crosshair, a dot on each live series, and a content panel ---- */
    var cross = sv("line", { class: "crosshair", x1: 0, x2: 0, y1: MT, y2: H - MB, opacity: 0 });
    svg.appendChild(cross);
    var hdots = {};
    ids.forEach(function (pid) {
      hdots[pid] = sv("circle", { class: "hdot", r: 4, fill: css(COLOR[pid]), opacity: 0 });
      svg.appendChild(hdots[pid]);
    });
    var pill = sv("g", { class: "pill", opacity: 0 });
    var pillBg = sv("rect", { rx: 3, height: 17, y: H - MB + 3 });
    var pillTx = sv("text", { y: H - MB + 15, "text-anchor": "middle" });
    pill.appendChild(pillBg); pill.appendChild(pillTx);
    svg.appendChild(pill);

    // index the mean values by global round for O(1) lookup
    var byI = {};
    ids.forEach(function (pid) { byI[pid] = {}; lines[pid].forEach(function (q) { byI[pid][q.i] = q.y; }); });

    var panel = document.createElement("div");
    panel.className = "chart-tip";
    panel.hidden = true;
    host.appendChild(panel);

    function hoverOff() {
      cross.setAttribute("opacity", 0);
      pill.setAttribute("opacity", 0);
      ids.forEach(function (pid) { hdots[pid].setAttribute("opacity", 0); });
      panel.hidden = true;
    }
    function hoverAt(i) {
      i = Math.max(i0, Math.min(n - 1, i));
      var t = TL[i], px = x(i);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 1);
      var rows = "";
      ids.forEach(function (pid) {
        var yv = byI[pid][i];
        if (yv === undefined) { hdots[pid].setAttribute("opacity", 0); return; }
        hdots[pid].setAttribute("cx", px);
        hdots[pid].setAttribute("cy", y(yv));
        hdots[pid].setAttribute("opacity", 1);
        var rv = t.r.p[pid];
        rows += '<div class="tip-row"><span class="sw" style="background:var(' + COLOR[pid] + ')"></span>' +
          '<span class="nm">' + SHORT[pid] + "</span>" +
          '<span class="mn">' + fmt(yv, 1) + "</span>" +
          '<span class="rd">' + (rv ? fmt(100 * rv.t, 0) : "—") + "</span></div>";
      });
      if (!rows) { hoverOff(); return; }   /* before any window is full there is nothing to show */
      var lbl = "Match " + (t.m.i + 1) + " · round " + (t.r.r + 1);
      pillTx.textContent = lbl;
      var wpx = lbl.length * 5.6 + 14;
      pillBg.setAttribute("x", px - wpx / 2); pillBg.setAttribute("width", wpx);
      pillTx.setAttribute("x", px);
      pill.setAttribute("opacity", 1);
      panel.innerHTML =
        '<div class="tip-head">' + t.m.map + " · match " + (t.m.i + 1) + " · round " + (t.r.r + 1) + "</div>" +
        '<div class="tip-cols"><span></span><span></span><span>decayed</span><span>round</span></div>' + rows;
      panel.hidden = false;
      /* Clamp inside the chart rather than flipping at a fixed fraction: a fixed flip still
         overflows whenever the panel is wider than the remaining space. */
      panel.style.left = "0px";
      panel.style.transform = "none";
      var hb = host.getBoundingClientRect(), pb = panel.getBoundingClientRect();
      var want = ((i - i0) / span) * hb.width + 14;
      panel.style.left = Math.max(0, Math.min(want, hb.width - pb.width)) + "px";
    }
    var surface = sv("rect", { class: "hover-surface", x: ML, y: MT,
                               width: W - ML - MR, height: H - MT - MB });
    surface.addEventListener("mousemove", function (e) {
      var r = svg.getBoundingClientRect();
      var vx = ((e.clientX - r.left) / r.width) * W;
      hoverAt(i0 + Math.round((vx - ML) / ((W - ML - MR) / span)));
    });
    surface.addEventListener("mouseleave", hoverOff);
    svg.appendChild(surface);

    host.appendChild(svg);
    host._x = x; host._band = band;
  }

  function drawScopeControl() {
    var host = document.getElementById("quad-scope");
    if (!host) return;
    host.textContent = "";
    var lead = document.createElement("span");
    lead.className = "winlead";
    lead.textContent = "show";
    host.appendChild(lead);
    SCOPES.forEach(function (sc) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "winbtn" + (sc.id === SCOPE ? " on" : "");
      b.textContent = sc.label;
      b.setAttribute("aria-pressed", String(sc.id === SCOPE));
      b.addEventListener("click", function () { SCOPE = sc.id; drawScopeControl(); drawChart(); });
      host.appendChild(b);
    });
    var n0 = scopeStart();
    var note = document.createElement("span");
    note.className = "winnote";
    note.textContent = "round " + (n0 + 1) + "–" + TL.length + " of " + TL.length +
                       " · axis only, values unchanged";
    host.appendChild(note);
  }

  function drawWindowControl() {
    var host = document.getElementById("quad-window");
    if (!host) return;
    host.textContent = "";
    var lead = document.createElement("span");
    lead.className = "winlead";
    lead.textContent = "half-life";
    host.appendChild(lead);
    [25, 50, 100].forEach(function (k) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "winbtn" + (k === HALFLIFE ? " on" : "");
      b.textContent = k + " rounds";
      b.setAttribute("aria-pressed", String(k === HALFLIFE));
      b.addEventListener("click", function () { HALFLIFE = k; drawWindowControl(); drawChart(); });
      host.appendChild(b);
    });
    var note = document.createElement("span");
    note.className = "winnote";
    note.textContent = "±" + (SE_AT[HALFLIFE] || 0).toFixed(2) + " per 100 · " +
                       Math.round(2.885 * HALFLIFE) + " effective rounds";
    host.appendChild(note);
  }

  function drawLegend() {
    var ul = document.getElementById("quad-legend");
    if (!ul) return;
    ul.textContent = "";
    D.players.forEach(function (p) {
      var li = document.createElement("li");
      li.innerHTML = '<span class="swatch" style="background:var(' + COLOR[p.id] + ')"></span>' +
        '<span class="who">' + SHORT[p.id] + "</span>" +
        '<span class="exposure">' + p.matches + " matches · " + p.rounds + " rounds</span>";
      ul.appendChild(li);
    });
  }

  /* ---------- credit-type waterfall, one per player ---------- */
  /* Kill credit and death debit are each an order of magnitude larger than plant, defuse and
     clock, and they very nearly cancel. Drawn as separate bars they set the domain so wide that
     everything else becomes an invisible sliver, so they are collapsed into one duel bar with
     both sides printed on it. The remaining steps and the net are untouched and still sum. */
  function drawWaterfall(p) {
    var raw = p.comp || [];
    var duel = raw.filter(function (c) { return c.ct === "kill_credit" || c.ct === "death_debit"; });
    var steps = [];
    if (duel.length) {
      steps.push({ ct: "duels", v100: duel.reduce(function (a, c) { return a + c.v100; }, 0),
                   parts: duel });
    }
    raw.forEach(function (c) {
      if (c.ct !== "kill_credit" && c.ct !== "death_debit") steps.push(c);
    });
    if (!steps.length) return null;

    var dom = 0, run = 0;
    steps.forEach(function (c) { run += c.v100; dom = Math.max(dom, Math.abs(run), Math.abs(c.v100)); });
    dom = Math.max(1, Math.ceil(dom));

    var W = 720, rowH = 52, padL = 190, padR = 96;
    var H = steps.length * rowH + 62;
    var x = function (v) { return padL + ((v + dom) / (2 * dom)) * (W - padL - padR); };

    var svg = sv("svg", { viewBox: "0 0 " + W + " " + H, class: "wf", role: "img",
      "aria-label": "Credit-type decomposition for " + SHORT[p.id] + ", summing to " +
                    fmt(p.r100) + " per 100 rounds." });
    svg.appendChild(sv("line", { class: "zero", x1: x(0), x2: x(0), y1: 4, y2: steps.length * rowH + 4 }));

    run = 0;
    steps.forEach(function (c, i) {
      var yy = 8 + i * rowH, from = run, to = run + c.v100;
      run = to;
      svg.appendChild(sv("rect", { class: "step " + (c.v100 >= 0 ? "pos" : "neg"),
        x: x(Math.min(from, to)), y: yy, width: Math.max(1, Math.abs(x(to) - x(from))), height: rowH - 20 }));
      var lab = sv("text", { class: "wf-lab", x: padL - 12, y: yy + 18, "text-anchor": "end" });
      lab.textContent = CT_LABEL[c.ct] || c.ct;
      svg.appendChild(lab);
      if (c.parts) {
        var sub = sv("text", { class: "wf-sub", x: padL - 12, y: yy + 33, "text-anchor": "end" });
        sub.textContent = c.parts.map(function (q) { return fmt(q.v100); }).join("   ");
        svg.appendChild(sub);
      }
      var val = sv("text", { class: "wf-val", x: W - padR + 10, y: yy + 18 });
      val.textContent = fmt(c.v100);
      svg.appendChild(val);
    });

    var ny = 14 + steps.length * rowH;
    svg.appendChild(sv("line", { class: "axis", x1: padL - 4, x2: W - padR, y1: ny, y2: ny }));
    var nl = sv("text", { class: "wf-lab strong", x: padL - 12, y: ny + 26, "text-anchor": "end" });
    nl.textContent = "Net";
    svg.appendChild(nl);
    var nv = sv("text", { class: "wf-val strong", x: W - padR + 10, y: ny + 26 });
    nv.textContent = fmt(p.r100);
    svg.appendChild(nv);
    return svg;
  }

  function drawCards() {
    var host = document.getElementById("quad-cards");
    if (!host) return;
    host.textContent = "";
    D.players.forEach(function (p) {
      var d = document.createElement("div");
      d.className = "quad-card";
      d.innerHTML =
        '<div class="who"><span class="swatch" style="background:var(' + COLOR[p.id] + ')"></span>' +
        SHORT[p.id] + "</div>" +
        '<div class="big ' + (p.r100 >= 0 ? "pos" : "neg") + '">' + fmt(p.r100) + "</div>" +
        '<div class="sub">per 100 rounds · ' + p.matches + " matches · " + p.rounds + " rounds</div>";
      var wf = drawWaterfall(p);
      if (wf) d.appendChild(wf);
      host.appendChild(d);
    });
  }

  function drawMatchList() {
    var tb = document.querySelector("#quad-matches tbody");
    if (!tb) return;
    tb.textContent = "";
    D.matches.forEach(function (m) {
      var tr = document.createElement("tr");
      var cells = ['<td class="num">' + (m.i + 1) + "</td>", "<td>" + (m.map || "—") + "</td>",
                   '<td class="num">' + m.rounds.length + "</td>"];
      ids.forEach(function (pid) {
        var tot = 0, cnt = 0;
        m.rounds.forEach(function (r) { if (r.p[pid]) { tot += r.p[pid].t; cnt++; } });
        cells.push(cnt ? '<td class="num ' + (tot >= 0 ? "pos" : "neg") + '">' + fmt(tot) + "</td>"
                       : '<td class="num absent">—</td>');
      });
      tr.innerHTML = cells.join("");
      tr.addEventListener("click", function () { location.hash = "#/m/" + m.i; });
      tb.appendChild(tr);
    });
  }

  /* ---------- round sheet: how one round broke down ---------- */
  function roundSheet(m, ri) {
    var r = m.rounds[ri], present = m.who.filter(function (p) { return r.p[p]; });
    var host = document.getElementById("round-sheet");
    if (!host) return;
    if (!present.length) { host.innerHTML = ""; return; }

    var head = present.map(function (p) {
      return '<th class="num"><span class="swatch" style="background:var(' + COLOR[p] + ')"></span>' +
             SHORT[p] + "</th>";
    }).join("");

    function row(label, get, cls, dec) {
      var cells = present.map(function (p) {
        var v = get(r.p[p]);
        if (v === null || v === undefined) return '<td class="num absent">—</td>';
        if (typeof v === "number")
          return '<td class="num ' + (v > 0 ? "pos" : v < 0 ? "neg" : "") + '">' +
                 fmt(v, dec === undefined ? 3 : dec) + "</td>";
        return '<td class="num">' + v + "</td>";
      }).join("");
      return "<tr class='" + (cls || "") + "'><td>" + label + "</td>" + cells + "</tr>";
    }
    var any = function (k) { return present.some(function (p) { return r.p[p][k] !== undefined; }); };

    var body = "";
    body += row("Kill credit", function (e) { return e.kc; });
    body += row("Death debit", function (e) { return e.dd; });
    if (any("pl")) body += row("Plant credit", function (e) { return e.pl; });
    if (any("df")) body += row("Defuse credit", function (e) { return e.df; });
    body += row("Clock share", function (e) { return e.ck; });
    body += row("Round RWPA", function (e) { return e.t; }, "rule-total");
    body += "<tr class='spacer'><td colspan='" + (present.length + 1) + "'></td></tr>";
    body += row("Kills", function (e) { return e.c ? e.c.k : null; }, null, 0);
    body += row("Damage", function (e) { return e.c ? e.c.dmg : null; }, null, 0);
    body += row("Loadout", function (e) { return e.c ? e.c.ld : null; }, null, 0);
    body += row("Credits left", function (e) { return e.c ? e.c.cr : null; }, null, 0);
    body += row("Weapon", function (e) { return e.c ? (e.c.wp || "—") : null; });

    host.innerHTML =
      "<h3>Round " + (r.r + 1) + (r.pi ? " · pistol" : "") + (r.ot ? " · overtime" : "") + "</h3>" +
      '<p class="meta">' + (r.res || "—") + " · won by " + (r.win || "—") +
      " · " + (r.atk || "—") + " attacking</p>" +
      '<div class="table-wrap"><table class="round-table"><thead><tr><th></th>' + head +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  function showMatch(mi) {
    var m = D.matches[mi];
    if (!m) return showCohort();
    document.getElementById("view-cohort").hidden = true;
    var v = document.getElementById("view-match");
    v.hidden = false;
    var present = m.who;

    var head = present.map(function (p) {
      return '<th class="num"><span class="swatch" style="background:var(' + COLOR[p] + ')"></span>' +
             SHORT[p] + "</th>";
    }).join("");
    var totals = {}; present.forEach(function (p) { totals[p] = 0; });
    var body = m.rounds.map(function (r, ri) {
      var cells = present.map(function (p) {
        var e = r.p[p];
        if (!e) return '<td class="num absent">—</td>';
        totals[p] += e.t;
        return '<td class="num ' + (e.t >= 0 ? "pos" : "neg") + '">' + fmt(e.t, 3) + "</td>";
      }).join("");
      var tag = (r.pi ? ' <span class="rtag">pistol</span>' : "") + (r.ot ? ' <span class="rtag">OT</span>' : "");
      return "<tr data-r='" + ri + "'><td class='num'>" + (r.r + 1) + "</td><td>" +
             (r.res || "—") + tag + "</td><td>" + (r.win || "—") + "</td>" + cells + "</tr>";
    }).join("");
    var foot = present.map(function (p) {
      return '<td class="num ' + (totals[p] >= 0 ? "pos" : "neg") + '"><strong>' + fmt(totals[p]) + "</strong></td>";
    }).join("");
    var roster = present.map(function (p) {
      return "<li><span class='swatch' style='background:var(" + COLOR[p] + ")'></span>" +
             SHORT[p] + " · " + (m.agent[p] || "—") + " · " + (m.won[p] ? "won" : "lost") + "</li>";
    }).join("");

    var prev = mi > 0 ? '<a href="#/m/' + (mi - 1) + '">← previous match</a>' : "";
    var next = mi < D.matches.length - 1 ? '<a href="#/m/' + (mi + 1) + '">next match →</a>' : "";

    v.innerHTML =
      '<p class="crumb"><a href="#/">← all matches</a></p>' +
      "<h1>Match " + (m.i + 1) + " · " + (m.map || "—") + "</h1>" +
      '<p class="meta">' + m.rounds.length + " rounds · " +
      (m.score && m.score.red !== null ? m.score.red + "–" + m.score.blue + " · " : "") +
      present.length + " of the four played</p>" +
      '<ul class="roster">' + roster + "</ul>" +
      (present.length === 1
        ? '<p class="quad-note">Only one of the four played, so this is a record rather than a comparison.</p>'
        : '<p class="quad-note">These ' + present.length + " shared every round below: same opponents, " +
          "same rounds. Within a match the comparison holds.</p>") +
      '<p class="quad-note">Select a round to see how it broke down.</p>' +
      '<div class="table-wrap"><table class="round-table" id="match-rounds"><thead><tr>' +
      "<th class='num'>Rd</th><th>Ending</th><th>Won by</th>" + head + "</tr></thead>" +
      "<tbody>" + body + "</tbody>" +
      "<tfoot><tr><td colspan='3'>Match total</td>" + foot + "</tr></tfoot></table></div>" +
      '<div class="sheet-host" id="round-sheet" aria-live="polite"></div>' +
      '<p class="match-nav">' + prev + " " + next + "</p>";

    v.querySelectorAll("#match-rounds tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function () {
        v.querySelectorAll("#match-rounds tbody tr").forEach(function (o) { o.removeAttribute("aria-selected"); });
        tr.setAttribute("aria-selected", "true");
        roundSheet(m, Number(tr.getAttribute("data-r")));
      });
    });
    var first = v.querySelector("#match-rounds tbody tr");
    if (first) first.click();
    window.scrollTo(0, 0);
  }

  function showCohort() {
    document.getElementById("view-match").hidden = true;
    document.getElementById("view-cohort").hidden = false;
  }

  function route() {
    var m = /^#\/m\/(\d+)$/.exec(location.hash || "");
    if (m) showMatch(Number(m[1])); else showCohort();
  }

  function boot() {
    drawLegend(); drawCards(); drawScopeControl(); drawWindowControl(); drawChart(); drawMatchList();
    addEventListener("hashchange", route);
    route();
    var t = document.querySelector(".theme-toggle");
    if (t) t.addEventListener("click", function () { setTimeout(function () { drawCards(); drawChart(); }, 0); });
    addEventListener("resize", function () { clearTimeout(boot._r); boot._r = setTimeout(drawChart, 150); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
