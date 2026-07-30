/* app.js — Martin & SN0RLAX RWPA dashboard.
   Vanilla, no dependencies, no build step. Reads window.VAL_DATA, which is
   emitted by `python3 -m valorant_impact.dashboard_data`.

   Six jobs: theme button, hash routing, the cumulative walk, the cohort
   tables, the match view with its round ledger, and the caveat plumbing.

   The payload carries its own dictionary (VAL_DATA.dict) and caveat set
   (VAL_DATA.meta.cav). Nothing here hardcodes what a metric means or how it
   should be formatted — if a definition is wrong, fix the extractor, not this
   file. That is the whole point of shipping the dictionary alongside the
   numbers.

   Honesty rules this file enforces, because the release does:
     - VAL_DATA.meta.gate.rank_players is false, so the two players are never
       decorated with a winner: no arrows, no highlight, no "leader" column.
     - An excluded round has no RWPA keys at all. It renders as an em dash and
       a reason, never as 0.00, because 0.00 would be a fabrication.
     - A per-100 rate is suppressed where the match has fewer than
       gate.min_elig_rounds_for_rate eligible rounds (r100_ok === false).
     - Every metric whose dict tier is not "h" is drawn demoted and flagged. */
(function () {
  "use strict";

  var D = window.VAL_DATA;
  var root = document.documentElement;
  root.classList.add("js");

  if (!D) {
    document.querySelector(".shell").innerHTML =
      '<p class="note">data.js did not load. Rebuild it with ' +
      '<code>python3 -m valorant_impact.dashboard_data --output dashboard/data.js</code>.</p>';
    return;
  }

  var PLAYERS = ["m", "s"];
  var NAME = { m: D.players.m.riot, s: D.players.s.riot };
  var SHORT = { m: "MartinLutherKing", s: "SN0RLAX" };

  /* ---------- theme ---------- */
  var themeBtn = document.querySelector(".theme-toggle");
  function paintTheme() {
    var dark = root.dataset.theme === "dark";
    themeBtn.textContent = dark ? "◑ light" : "◐ dark";
    themeBtn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  paintTheme();
  themeBtn.addEventListener("click", function () {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("rwpa-theme", root.dataset.theme); } catch (e) {}
    paintTheme();
    if (currentMatch) renderStrip(currentMatch);
    renderWalk();
  });

  /* ---------- formatting ---------- */
  /* Every number on the page goes through here so a format lives in exactly one
     place: VAL_DATA.meta.fmt, keyed off the metric's dict entry. */
  function fmtSpec(spec, v) {
    if (v === null || v === undefined) return "—";
    if (spec && spec.kind === "string") return String(v);
    if (spec && spec.kind === "boolean") return v ? "yes" : "no";
    if (spec && spec.kind === "duration_ms") {
      var s = Math.round(v / 1000);
      return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    }
    var n = Number(v);
    if (!isFinite(n)) return "—";
    if (spec && spec.mult) n *= spec.mult;
    var dec = spec && spec.dec !== undefined ? spec.dec : 2;
    var out = Math.abs(n).toFixed(dec);
    var sign = n < 0 ? "−" : (spec && spec.sign ? "+" : "");
    /* An exact zero takes no sign at all — it is the absence of an event, not a
       positive one, and the sign glyph is a load-bearing channel (CSS rule 2).
       A tiny negative that ROUNDS to zero still prints "+" rather than "−0.000". */
    if (spec && spec.sign && Number(out) === 0) sign = n === 0 ? "" : "+";
    if (spec && spec.group) out = Number(out).toLocaleString();
    return sign + out + ((spec && spec.suf) || "");
  }
  function fmtKey(key, v) {
    var meta = D.dict[key];
    return fmtSpec(D.meta.fmt[meta ? meta.fmt : "n2"], v);
  }
  function signed(v, dec) {
    return fmtSpec({ dec: dec === undefined ? 3 : dec, sign: true }, v);
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  /* Legend entries are swatch + label everywhere on the page, so they are built
     in one place. `mark` tags the ones a re-render owns and must clear first. */
  function swatchSpan(kind, label, mark) {
    var s = el("span");
    if (mark) s.setAttribute("data-walk-mark", "");
    s.appendChild(el("i", "swatch " + kind));
    s.appendChild(document.createTextNode(label));
    return s;
  }
  function svgEl(tag, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    return n;
  }
  /* Rule 2 in the CSS: green is "this moved the team's chance up", red is
     "down", and a zero is neither — it is the absence of an event, and ~38% of
     kill-credit cells and ~35% of death-debit cells are exactly zero. This
     never runs on a name, a neutral count, or a win/loss chip. */
  function signCls(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "zero"; }

  /* ---------- caveats and the one disclosure component ---------- */
  /* Everything explanatory on this page lands behind a `?` button, never a
     title= attribute: native tooltips do not exist on touch and never appear on
     keyboard focus, so a title= disclosure is a disclosure only for a mouse.

     A source is a dict key, a caveat id, or a literal {lbl, body}. A dict key
     also drags in every BLOCKING caveat it names — a boundary that blocks a
     reading has to travel with the number it blocks. Warn-tier caveats come
     only when named, which is what keeps a panel to three or four paragraphs.
     De-duplication is by label, so c_exposure reached through four dict keys
     renders once. */
  function infoEntries(src) {
    var list = [].concat(src), out = [], seen = {};
    function push(lbl, body) {
      if (!lbl || !body || seen[lbl]) return;
      seen[lbl] = true;
      out.push({ lbl: lbl, body: body });
    }
    list.forEach(function (s) {
      if (!s) return;
      if (typeof s === "object") { push(s.lbl, s.body); return; }
      var m = D.dict[s];
      if (m) {
        push(m.lbl, m.def);
        (m.cav || []).forEach(function (id) {
          var c = D.meta.cav[id];
          if (c && c.sev === "block") push(c.t, c.b);
        });
        return;
      }
      var c = D.meta.cav[s];
      if (c) push(c.t, c.b);
    });
    return out;
  }

  /* A `?` is an HTML <button>, so it can never go inside an <svg>. Each figure
     collects its disclosures onto one button on its HTML .fig-title. */
  function infoButton(src, label) {
    var entries = infoEntries(src);
    if (!entries.length) return null;
    var b = el("button", "info", "?");
    b.type = "button";
    b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-label", "What is " + (label || entries[0].lbl) + "?");
    b.addEventListener("click", function (ev) {
      /* the button sits inside clickable table rows and clickable figure cards */
      ev.stopPropagation();
      var open = b.getAttribute("aria-expanded") === "true";
      var cell = b.parentNode;
      var existing = cell.querySelector(".def");
      if (existing) existing.remove();
      b.setAttribute("aria-expanded", open ? "false" : "true");
      if (open) return;
      var box = el("div", "def");
      entries.forEach(function (e) {
        var p = el("p");
        p.appendChild(el("b", null, e.lbl));
        p.appendChild(document.createTextNode(" — " + e.body));
        box.appendChild(p);
      });
      cell.appendChild(box);
    });
    return b;
  }

  function caveatMark(ids) {
    if (!ids || !ids.length) return null;
    var block = ids.filter(function (id) {
      return D.meta.cav[id] && D.meta.cav[id].sev === "block";
    });
    return infoButton(block.length ? block : ids);
  }
  function tierFlag(key) {
    var meta = D.dict[key];
    if (!meta || meta.tier === "h") return null;
    var t = D.meta.tier[meta.tier];
    var span = el("span", "tier-flag", t.lbl.slice(0, 4));
    span.title = t.lbl + " — " + t.blurb;
    return span;
  }

  /* Reference scale for the unsigned bars in the round sheet. Computed once
     over all 752 player-rounds and cached. It must NEVER be recomputed from the
     round being drawn: normalising head-to-head would pin the larger of the two
     values to a full bar on every row of every round and manufacture 17 matches
     of blowouts out of a corpus whose headline difference does not clear zero. */
  var P95 = (function () {
    var acc = { dmg: [], lv: [], cr: [] };
    D.matches.forEach(function (m) {
      m.rs.forEach(function (r) {
        PLAYERS.forEach(function (pid) {
          var pr = r.p[pid];
          if (!pr) return;
          Object.keys(acc).forEach(function (k) {
            if (typeof pr[k] === "number") acc[k].push(pr[k]);
          });
        });
      });
    });
    var out = {};
    Object.keys(acc).forEach(function (k) {
      var v = acc[k].sort(function (a, b) { return a - b; });
      out[k] = v[Math.floor(v.length * 0.95)] || 1;
    });
    return out;
  })();

  /* ---------- round provenance ---------- */
  /* Three states, not two. A round where somebody was inactive is scored as a
     genuine four-versus-five — the alive counts describe it and the win
     probability model conditions on them — so it is a headline round with a
     provenance mark, not a discount. Only a round with no well-defined endpoint
     (a surrender, no active players) is unscorable, because pricing one would
     be fabrication.

     The extractor may or may not ship meta.cohort.disp yet. Every figure reads
     this accessor, so the page renders against either payload and lights the
     third state up the moment it arrives. */
  function disposition() {
    var c = D.meta.cohort;
    if (c.disp && c.disp.length) return c.disp;
    return [
      { k: "clean", lbl: "Scored", n: c.elig_rounds, cav: ["c_exposure"] },
      { k: "unscorable", lbl: "No scorable endpoint", n: c.excl_rounds, cav: ["c_not_measured"] },
    ].filter(function (d) { return d.n > 0; });
  }
  function isDegraded(r) { return r.dg === true; }
  function dispTotal() {
    return disposition().reduce(function (a, d) { return a + d.n; }, 0);
  }

  /* A figure whose viewBox is a fixed number of CSS pixels must not be allowed
     to scale below the size its labels were written at. The walk and F1 measure
     their container instead; the small figures cannot, because they are laid
     out inside cards and panels whose width they do not know at build time. So
     below their natural width they scroll rather than shrink — on a 375px phone
     the forest plot would otherwise render its 10.5px row labels at 3.7px,
     which is the same "chart becomes decoration" failure the walk's viewBox
     comment warns about. The scroller wraps only the svg, so the `?` panel on
     the figure title is never clipped by it. */
  function figScroll(svg, minW) {
    var box = el("div", "fig-scroll");
    svg.style.minWidth = minW + "px";
    box.appendChild(svg);
    return box;
  }

  /* One 45° hatch, two figures (F1 and the strip), so the pattern id cannot
     collide when both are in the document at once. */
  function hatchDefs(id) {
    var defs = svgEl("defs", {});
    var pat = svgEl("pattern", { id: id, width: 5, height: 5,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    pat.appendChild(svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 5, stroke: "var(--line)", "stroke-width": 2.4 }));
    defs.appendChild(pat);
    return defs;
  }

  /* ============================ COHORT VIEW ============================ */

  var vCohort = document.getElementById("view-cohort");
  var vMatch = document.getElementById("view-match");

  /* Every round of the cohort, flattened in play order. This is the x-axis of
     the walk and the spine of most cohort-level arithmetic. */
  var SEQ = [];
  D.matches.forEach(function (m) {
    m.rs.forEach(function (r) { SEQ.push({ m: m, r: r }); });
  });

  function renderHeader() {
    var c = D.meta.cohort;
    /* One denominator in the masthead. The eligible/raw split is the entire
       subject of F1 a screen below, and c_raw_den warns against carrying two
       denominators side by side where neither is labelled. */
    document.querySelector("[data-header-meta]").textContent =
      c.matches + " matches · " + c.rec.w + "W " + c.rec.l + "L" + (c.rec.d ? " " + c.rec.d + "D" : "") +
      " · " + c.raw_rounds + " rounds · " + D.meta.season;

    var h1 = document.querySelector(".masthead h1");
    var ib = infoButton(["rwpa"], "round win probability added");
    if (h1 && ib) h1.appendChild(ib);
  }

  /* ---------- the walk ---------- */
  /* Cumulative headline RWPA over every round in order. Rounds that were never
     scored carry no value, so the line is flat across them and the flat span is
     hatched — the gap is drawn, not hidden.

     The y-domain is the union envelope of the two cumulative series and nothing
     else. It used to also swallow both total-RWPA intervals, which are several
     times wider, so the walk was squashed into the middle 40% of the figure and
     two thirds of the plot was whitespace held open by a bracket. The intervals
     are still on the page twice — on each verdict card and across the forest
     plot — both times in per-100 units, which is the unit every other interval
     on the page is quoted in. */
  /* The viewBox is sized to the container in CSS pixels, 1 user unit = 1 px, so
     the tick and label text renders at the size it is written at whatever the
     screen width. A fixed 1000-unit viewBox scaled to a 335px phone shrinks
     10.5px ticks to 3.5px, which is how a chart becomes decoration. */
  var H = 300, PAD_L = 40, PAD_T = 18, PAD_B = 26;
  var W = 1000, PAD_R = 56;
  var walkNode = document.querySelector("[data-walk]");
  var walkFig = document.querySelector("[data-walk-figure]");
  var walkReadout = document.querySelector("[data-walk-readout]");
  var walkGeom = null;

  function cumulative(pid) {
    var run = 0, out = [];
    SEQ.forEach(function (s) {
      var pr = s.r.p[pid];
      if (s.r.el && pr && typeof pr.rw === "number") run += pr.rw;
      out.push(run);
    });
    return out;
  }

  function renderWalk() {
    /* Clear by identity, not by count. `childNodes.length > 2` counts the
       indentation text nodes between the markup's <title> and <desc>, so it ate
       the <desc> on the first render — which then threw on the line that writes
       the description, silently killing everything route() does after the walk,
       and left aria-labelledby pointing at a node that no longer existed. */
    Array.prototype.slice.call(walkFig.childNodes).forEach(function (n) {
      if (n.nodeType === 1 && n.nodeName !== "title" && n.nodeName !== "desc") walkFig.removeChild(n);
    });
    W = Math.max(320, Math.round(walkFig.clientWidth || walkNode.clientWidth || 1000));
    PAD_R = W < 640 ? 40 : 56;
    var narrow = W < 640;
    walkFig.setAttribute("viewBox", "0 0 " + W + " " + H);

    var series = { m: cumulative("m"), s: cumulative("s") };
    /* Both series start at 0, so 0 is inside [lo, hi] by construction and the
       zero rule is always drawn. The domain is deliberately NOT forced
       symmetric about zero — that would put back the dead space this removes. */
    var lo = 0, hi = 0;
    PLAYERS.forEach(function (pid) {
      series[pid].forEach(function (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    });
    var pad = Math.max(0.25, (hi - lo) * 0.06);
    lo -= pad; hi += pad;

    var plotW = W - PAD_L - PAD_R;
    var x = function (i) { return PAD_L + (SEQ.length < 2 ? 0 : (i / (SEQ.length - 1)) * plotW); };
    var y = function (v) { return PAD_T + (1 - (v - lo) / (hi - lo)) * (H - PAD_T - PAD_B); };
    walkGeom = { x: x, y: y, series: series };

    var g = svgEl("g", {});

    /* y grid + ticks at whole RWPA units */
    /* 2.5 is deliberately absent: RWPA reads in whole probability units and a
       +2.5 gridline looks like a rounding artefact. */
    var LADDER = [0.5, 1, 2, 5, 10, 20, 50];
    var rawStep = (hi - lo) / 5;
    var step = LADDER.filter(function (v) { return v >= rawStep; })[0] || 50;
    var dp = step < 1 ? 1 : 0;
    for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      g.appendChild(svgEl("line", { class: t === 0 ? "walk-axis" : "walk-grid",
        x1: PAD_L, x2: W - PAD_R, y1: y(t), y2: y(t) }));
      var lab = svgEl("text", { class: "walk-tick", x: PAD_L - 7, y: y(t) + 3.5, "text-anchor": "end" });
      lab.textContent = (t > 0 ? "+" : "") + t.toFixed(dp);
      g.appendChild(lab);
    }

    /* shade the spans where nothing was measured */
    var runStart = null;
    SEQ.forEach(function (s, i) {
      if (!s.r.el && runStart === null) runStart = i;
      if ((s.r.el || i === SEQ.length - 1) && runStart !== null) {
        g.appendChild(svgEl("rect", { class: "walk-band", fill: "var(--line)", opacity: .5,
          x: x(runStart), y: PAD_T, width: Math.max(1.2, x(i) - x(runStart)), height: H - PAD_T - PAD_B }));
        runStart = null;
      }
    });

    /* match boundaries */
    var acc = 0;
    D.matches.forEach(function (m, mi) {
      if (mi > 0) g.appendChild(svgEl("line", { class: "walk-sep", x1: x(acc), x2: x(acc), y1: PAD_T, y2: H - PAD_B }));
      acc += m.rs.length;
    });

    /* the two lines */
    PLAYERS.forEach(function (pid) {
      var dd = series[pid].map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(2) + " " + y(v).toFixed(2); }).join(" ");
      g.appendChild(svgEl("path", { class: "walk-line " + pid, d: dd }));
    });

    /* interval gutter — same scale as the walk */
    /* The gutter is gone; the end value moves onto the line it belongs to. */
    PLAYERS.forEach(function (pid) {
      var lastV = series[pid][series[pid].length - 1];
      var yEnd = y(lastV);
      var other = y(series[pid === "m" ? "s" : "m"][SEQ.length - 1]);
      /* legibility nudge only when the two ends collide — moves the LABEL, never
         the line and never the value */
      if (Math.abs(yEnd - other) < 11) yEnd += (yEnd <= other ? -6 : 6);
      var lab = svgEl("text", { class: "walk-end " + pid, x: x(SEQ.length - 1) + 7, y: yEnd + 4 });
      lab.textContent = signed(lastV, 2);
      g.appendChild(lab);
    });

    /* x ticks: the x-axis is a timeline, so label the first match of each play
       date rather than every nth match — 17 matches sit on only 10 dates. */
    var acc2 = 0, seenDate = null, lastLabelX = -1e9;
    D.matches.forEach(function (m) {
      if (m.det !== seenDate) {
        seenDate = m.det;
        /* skip a label rather than overprint one when the axis gets tight */
        if (x(acc2) - lastLabelX > (narrow ? 46 : 34)) {
          lastLabelX = x(acc2);
          var tx = svgEl("text", { class: "walk-tick", x: x(acc2) + 3, y: H - PAD_B + 15 });
          tx.textContent = m.det.slice(5).replace("-", "/");
          g.appendChild(tx);
        }
      }
      acc2 += m.rs.length;
    });

    g.appendChild(svgEl("line", { class: "walk-cursor", x1: 0, x2: 0, y1: PAD_T, y2: H - PAD_B }));
    walkFig.appendChild(g);

    var hit = svgEl("rect", { class: "walk-hit", x: PAD_L, y: PAD_T, width: plotW, height: H - PAD_T - PAD_B });
    walkFig.appendChild(hit);

    /* The legend names the marks and nothing else — a sentence here was the
       page telling the reader what it had just drawn. It only ever names marks
       that are actually on screen: once every round in the cohort is scored
       there are no shaded spans, and a legend pointing at nothing is worse than
       no legend. */
    var legend = document.querySelector("[data-walk-legend]");
    var unscored = SEQ.filter(function (q) { return !q.r.el; }).length;
    Array.prototype.slice.call(legend.querySelectorAll("[data-walk-mark]")).forEach(function (n) { n.remove(); });
    legend.appendChild(swatchSpan("rule", "match boundary", true));
    if (unscored) legend.appendChild(swatchSpan("hatch", "no scorable endpoint", true));

    walkFig.querySelector("[data-walk-desc]").textContent =
      "Cumulative round win probability added over " + SEQ.length + " rounds, in play order. " +
      SHORT.m + " ends at " + signed(series.m[SEQ.length - 1], 2) + " and " +
      SHORT.s + " at " + signed(series.s[SEQ.length - 1], 2) + ".";
  }

  function walkAt(i) {
    var s = SEQ[i];
    if (!s) return;
    var cursor = walkFig.querySelector(".walk-cursor");
    cursor.setAttribute("x1", walkGeom.x(i));
    cursor.setAttribute("x2", walkGeom.x(i));
    walkNode.classList.add("is-live");
    var lines = [
      "<b>" + s.m.map + " · " + s.m.det + " · " + s.m.res + "</b>",
      "Round " + s.r.n + (s.r.el ? "" : " · not measured"),
    ];
    PLAYERS.forEach(function (pid) {
      var pr = s.r.p[pid];
      var cum = walkGeom.series[pid][i];
      var delta = s.r.el && pr && typeof pr.rw === "number" ? signed(pr.rw, 3) : "—";
      lines.push(SHORT[pid] + " " + signed(cum, 2) + " (" + delta + ")");
    });
    walkReadout.innerHTML = lines.join("<br>");
  }

  function walkIndexFromEvent(ev) {
    var box = walkFig.getBoundingClientRect();
    var px = ((ev.clientX - box.left) / box.width) * W;
    var frac = (px - PAD_L) / (W - PAD_L - PAD_R);
    return Math.max(0, Math.min(SEQ.length - 1, Math.round(frac * (SEQ.length - 1))));
  }
  walkFig.addEventListener("pointermove", function (ev) { walkAt(walkIndexFromEvent(ev)); });
  walkFig.addEventListener("pointerleave", function () { walkNode.classList.remove("is-live"); });
  walkFig.addEventListener("click", function (ev) {
    var s = SEQ[walkIndexFromEvent(ev)];
    if (s) location.hash = "#/m/" + s.m.id;
  });


  /* ---------- F1 · where the rounds went ---------- */
  /* Every round the two of them played, once, to scale. This is the figure that
     replaces four paragraphs about held-out rounds and a fraction in the
     masthead: the reader can see how much of the corpus is priced without being
     told a number to trust.

     Monochrome on purpose. A disposition is neither a direction nor a person,
     so it may borrow neither the sign palette nor the player palette. The order
     is fixed by state, never sorted by count — clean → degraded → unscorable is
     a monotone ramp of how much of a round can be priced, and sorting would
     make the visual order a function of whichever reason happened to be
     commonest this refresh. */
  var DISP_FILL = {
    clean: { fill: "var(--muted)", opacity: 1, swatch: "" },
    degraded: { fill: "var(--muted)", opacity: .45, swatch: "dim" },
    unscorable: { fill: "var(--line-2)", opacity: 1, hatch: true, swatch: "hatch" },
  };

  function renderDisposition() {
    var host = document.querySelector("[data-disposition]");
    if (!host) return;
    host.innerHTML = "";
    var raw = D.meta.cohort.raw_rounds;
    var disp = disposition();
    var total = dispTotal();

    var ttl = el("p", "fig-title");
    /* Fail loud. A disposition that does not sum to the rounds played is a
       broken payload, and silently rescaling the bar would hide it. */
    var ok = total === raw;
    ttl.appendChild(el("span", null, ok
      ? "Where the " + raw + " rounds went"
      : "Round provenance — payload inconsistent: " + total + " of " + raw));
    /* The unscorable slice is the one segment a reader will want itemised, and
       the payload already knows why each of its rounds is there. Grouping
       overall.excl by its gate token puts that breakdown on the `?` instead of
       in a method card. */
    var src = ["elig_rounds", "raw_rounds", "c_exposure", "c_raw_den"];
    var by = {}, any = false;
    (D.overall.excl || []).forEach(function (e) { by[e.xr] = (by[e.xr] || 0) + 1; any = true; });
    if (any) {
      src.push({ lbl: "Why those rounds have no endpoint", body: Object.keys(by).map(function (k) {
        return by[k] + " · " + (D.meta.xr[k] || k);
      }).join("; ") + "." });
    }
    var ib = infoButton(src, "the round denominators");
    if (ib) ttl.appendChild(ib);
    host.appendChild(ttl);
    if (!ok || !total) return;

    var w = Math.max(320, Math.round(host.clientWidth || 1000));
    var h = 78, barY = 8, barH = 26, axisY = 42;
    var svg = svgEl("svg", { viewBox: "0 0 " + w + " " + h, role: "img" });
    var t = svgEl("title", {});
    t.textContent = raw + " rounds played: " + disp.map(function (d) {
      return d.n + " " + d.lbl.toLowerCase();
    }).join(", ") + ".";
    svg.appendChild(t);
    svg.appendChild(hatchDefs("disp-hatch"));

    var x = 0;
    disp.forEach(function (d, i) {
      var style = DISP_FILL[d.k] || DISP_FILL.clean;
      var wd = (d.n / total) * w;
      svg.appendChild(svgEl("rect", { x: x, y: barY, width: Math.max(1, wd), height: barH,
        fill: style.fill, opacity: style.opacity }));
      if (style.hatch) {
        svg.appendChild(svgEl("rect", { x: x, y: barY, width: Math.max(1, wd), height: barH,
          fill: "url(#disp-hatch)", opacity: .85 }));
      }
      if (i) svg.appendChild(svgEl("line", { class: "seg", x1: x, x2: x, y1: barY, y2: barY + barH }));
      x += wd;
    });

    svg.appendChild(svgEl("line", { class: "axis-line", x1: 0, x2: w, y1: axisY, y2: axisY }));
    var step = raw > 600 ? 100 : 50;
    for (var v = 0; v < raw; v += step) {
      var tx = (v / total) * w;
      svg.appendChild(svgEl("line", { class: "ref-tick", x1: tx, x2: tx, y1: axisY, y2: axisY + 4 }));
      var lb = svgEl("text", { x: tx + (v ? 0 : 1), y: axisY + 15, "text-anchor": v ? "middle" : "start" });
      lb.textContent = v;
      svg.appendChild(lb);
    }
    var end = svgEl("text", { class: "val", x: w - 1, y: axisY + 15, "text-anchor": "end" });
    end.textContent = raw;
    svg.appendChild(end);
    host.appendChild(svg);

    /* Labels live in the legend, never inside the segments: a four-percent-wide
       segment cannot hold "no scorable endpoint". */
    var legend = el("p", "walk-legend");
    disp.forEach(function (d) {
      var style = DISP_FILL[d.k] || DISP_FILL.clean;
      legend.appendChild(swatchSpan("block " + style.swatch, d.n + " · " + d.lbl));
    });
    host.appendChild(legend);
  }

  /* ---------- credit-type waterfall ---------- */
  /* The only headline-tier object in the payload that nothing rendered, and it
     answers the question the page provokes and never settles: why are two
     totals this close when the two players are not alike? Because each is the
     residue of about forty units of churn either way. Martin's +4.746 is
     +38.148 of kill credit against −35.810 of death debit.
     dict.comp.def forbids reading the five as five separate skills, so this is
     drawn as a flow into one net — never five ranked bars, never sorted. */
  var COMP_LABEL = {
    kill_credit: "Kill credit", death_debit: "Death debit",
    plant: "Plant", defuse: "Defuse", alive_clock: "Clock",
  };

  function renderWaterfall(pid) {
    var comp = D.overall.p[pid].comp;
    var net = D.overall.p[pid].rw.v;
    var lo = 0, hi = 0, run = 0;
    comp.forEach(function (c) { run += c.v; lo = Math.min(lo, run); hi = Math.max(hi, run); });
    /* one shared domain across both players so the two figures are comparable
       without either being scaled to the other */
    var dom = 0;
    PLAYERS.forEach(function (q) {
      var r2 = 0;
      D.overall.p[q].comp.forEach(function (c) {
        r2 += c.v;
        dom = Math.max(dom, Math.abs(r2), Math.abs(c.v));
      });
    });
    dom = Math.ceil(dom / 10) * 10;

    var W = 460, rowH = 22, padL = 92, padR = 54;
    var H = comp.length * rowH + 30;
    var x = function (v) { return padL + ((v + dom) / (2 * dom)) * (W - padL - padR); };

    var fig = el("div", "fig");
    var ttl = el("p", "fig-title", "How " + SHORT[pid] + " got to " + signed(net, 3));
    /* The two method cards that used to narrate this figure from 40px away are
       gone; every sentence they carried is in this panel, from the payload. */
    var ib = infoButton(["comp", "kc_r", "dd_r", "pl_r", "df_r", "rc_r"], "the credit types");
    if (ib) ttl.appendChild(ib);
    fig.appendChild(ttl);
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    var t = svgEl("title", {});
    t.textContent = "Credit-type decomposition for " + SHORT[pid] +
      ", five steps summing to " + signed(net, 3) + ".";
    svg.appendChild(t);

    svg.appendChild(svgEl("line", { class: "zero-line", x1: x(0), x2: x(0), y1: 4, y2: comp.length * rowH + 2 }));

    run = 0;
    comp.forEach(function (c, i) {
      var y = 6 + i * rowH;
      var from = run, to = run + c.v;
      run = to;
      svg.appendChild(svgEl("rect", {
        class: "step " + (c.v >= 0 ? "pos" : "neg"),
        x: x(Math.min(from, to)), y: y,
        width: Math.max(1, Math.abs(x(to) - x(from))), height: rowH - 8,
      }));
      var lab = svgEl("text", { x: padL - 8, y: y + 9, "text-anchor": "end" });
      lab.textContent = COMP_LABEL[c.ct] || c.ct;
      svg.appendChild(lab);
      var val = svgEl("text", { class: "val", x: W - padR + 6, y: y + 9 });
      val.textContent = signed(c.v, 2);
      svg.appendChild(val);
    });

    var ny = 6 + comp.length * rowH;
    svg.appendChild(svgEl("line", { class: "axis-line", x1: padL, x2: W - padR, y1: ny - 3, y2: ny - 3 }));
    var nl = svgEl("text", { x: padL - 8, y: ny + 11, "text-anchor": "end" });
    nl.textContent = "Net";
    svg.appendChild(nl);
    svg.appendChild(svgEl("circle", { class: "net", cx: x(net), cy: ny + 7, r: 3.5 }));
    var nv = svgEl("text", { class: "val", x: W - padR + 6, y: ny + 11 });
    nv.textContent = signed(net, 2);
    svg.appendChild(nv);

    fig.appendChild(figScroll(svg, W));
    return fig;
  }

  /* ---------- scenario sensitivity ---------- */
  /* c_no_rank is a blocking caveat and it claims the point ordering reverses
     when the four inactivity-affected matches are dropped. The page asserted
     that in prose and never showed it. The contrast runs +0.239 -> +0.530 ->
     -0.352 across the three scenarios while neither player's own interval ever
     clears zero and the duo's always does. The zero rule is the hero here, not
     the ordering. */
  function renderScenarios() {
    var scen = D.overall.scen;
    var groups = [
      ["m", SHORT.m], ["s", SHORT.s],
      ["contrast", "Difference"], ["duo", "Together"],
    ];
    /* The basic-bootstrap reading of the duo estimand is a fourth bar in the
       Together group, not a fourth scenario: same point estimate, same axis, a
       dashed stroke because it is a method variant. Two paragraphs used to say
       "read it as fragile" — here the bar crosses the rule the three above it
       clear, which is the same statement without the instruction. */
    var basic = D.overall.duo && D.overall.duo.r100_basic;
    var lo = 0, hi = 0;
    scen.forEach(function (sc) {
      groups.forEach(function (g) {
        var e = sc.e[g[0]];
        if (!e) return;
        lo = Math.min(lo, e.lo); hi = Math.max(hi, e.hi);
      });
    });
    if (basic) { lo = Math.min(lo, basic.lo); hi = Math.max(hi, basic.hi); }
    var pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;

    /* The group name gets its own line. Sharing a baseline with the first
       scenario row put the player's name on top of the scenario's label. */
    var W = 1000, padL = 212, padR = 70, rowH = 17, headH = 17, groupGap = 12;
    var extra = basic ? rowH : 0;
    var H = groups.length * (scen.length * rowH + headH + groupGap) + extra + 24;
    var x = function (v) { return padL + ((v - lo) / (hi - lo)) * (W - padL - padR); };

    var fig = el("div", "fig");
    var ttl = el("p", "fig-title", "Every estimand, under all three eligibility scenarios");
    var ib = infoButton(["contrast100", "duo100", "c_teammates", "c_no_rank"], "the difference and the duo estimand");
    if (ib) ttl.appendChild(ib);
    fig.appendChild(ttl);
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    var t = svgEl("title", {});
    t.textContent = "Forest plot: four estimands across three scenarios, plus the duo estimand " +
      "under a basic bootstrap, all on one scale, with the zero rule running unbroken " +
      "down the figure.";
    svg.appendChild(t);
    svg.appendChild(svgEl("line", { class: "zero-line", x1: x(0), x2: x(0), y1: 2, y2: H - 18 }));

    var y = 6;
    groups.forEach(function (g) {
      var gl = svgEl("text", { x: 0, y: y + 9 });
      gl.textContent = g[1];
      gl.setAttribute("font-weight", "600");
      if (g[0] === "m" || g[0] === "s") gl.setAttribute("fill", "var(--" + (g[0] === "m" ? "martin" : "snorlax") + ")");
      else gl.setAttribute("fill", "var(--muted)");
      svg.appendChild(gl);
      y += headH;

      /* The connector runs through the three Difference dots, behind the
         strokes, so the sign reversal across scenarios is a visible crossing of
         the zero rule rather than a sentence quoting three numbers. Faint by
         design: a reading aid, not a trend claim. */
      if (g[0] === "contrast") {
        var pts = [];
        scen.forEach(function (sc, i) {
          var e = sc.e.contrast;
          if (e) pts.push(x(e.v).toFixed(2) + "," + (y + i * rowH + 7).toFixed(2));
        });
        if (pts.length > 1) svg.appendChild(svgEl("polyline", { class: "link", points: pts.join(" ") }));
      }

      var rows = scen.map(function (sc) { return { lbl: sc.lbl, e: sc.e[g[0]] }; });
      if (g[0] === "duo" && basic) rows.push({ lbl: "Basic bootstrap · all matches", e: basic, variant: true });

      rows.forEach(function (row) {
        var e = row.e;
        if (!e) { y += rowH; return; }
        var cy = y + 7;
        svg.appendChild(svgEl("line", {
          class: row.variant ? "rng-basic" : null,
          x1: x(e.lo), x2: x(e.hi), y1: cy, y2: cy,
          stroke: "var(--muted)",
          "stroke-width": row.variant ? 1.5 : (e.z ? 2.5 : 1.5),
          opacity: row.variant ? .7 : (e.z ? 1 : .7),
        }));
        svg.appendChild(svgEl("circle", { cx: x(e.v), cy: cy, r: 2.6, fill: "var(--text)" }));
        var sl = svgEl("text", { x: padL - 8, y: cy + 3.5, "text-anchor": "end" });
        sl.textContent = row.lbl;
        svg.appendChild(sl);
        var vv = svgEl("text", { class: e.z ? "val" : "", x: W - padR + 5, y: cy + 3.5 });
        vv.textContent = signed(e.v, 2) + (e.z ? "  ✓" : "");
        svg.appendChild(vv);
        y += rowH;
      });
      y += groupGap;
    });
    var zl = svgEl("text", { x: x(0), y: H - 4, "text-anchor": "middle" });
    zl.textContent = "0";
    svg.appendChild(zl);
    /* four words where a forty-word caption was */
    var key = svgEl("text", { x: 0, y: H - 4 });
    key.textContent = "✓ interval excludes zero";
    svg.appendChild(key);
    fig.appendChild(figScroll(svg, W));
    return fig;
  }

  /* ---------- verdict ---------- */
  function ciBar(ci, lo, hi) {
    var wrap = el("div", "ci");
    var bar = el("div", "ci-bar");
    var pct = function (v) { return ((v - lo) / (hi - lo)) * 100; };
    var zero = el("div", "ci-zero");
    zero.style.left = pct(0) + "%";
    var range = el("div", "ci-range");
    range.style.left = pct(ci.lo) + "%";
    range.style.width = Math.max(0.6, pct(ci.hi) - pct(ci.lo)) + "%";
    var point = el("div", "ci-point");
    point.style.left = "calc(" + pct(ci.v) + "% - 1px)";
    bar.appendChild(zero); bar.appendChild(range); bar.appendChild(point);
    var scale = el("div", "ci-scale");
    scale.appendChild(el("span", null, signed(ci.lo, 2)));
    scale.appendChild(el("span", null, ci.z ? "excludes zero" : "includes zero"));
    scale.appendChild(el("span", null, signed(ci.hi, 2)));
    wrap.appendChild(bar); wrap.appendChild(scale);
    return wrap;
  }

  function renderVerdict() {
    var host = document.querySelector("[data-verdict]");
    host.innerHTML = "";

    /* one shared scale for both cards, so the two intervals are comparable by eye */
    var lo = 0, hi = 0;
    PLAYERS.forEach(function (pid) {
      var ci = D.overall.p[pid].rw100;
      lo = Math.min(lo, ci.lo); hi = Math.max(hi, ci.hi);
    });
    lo -= 0.4; hi += 0.4;

    PLAYERS.forEach(function (pid) {
      var p = D.overall.p[pid];
      var card = el("div", "card " + pid);
      card.appendChild(el("h3", null, NAME[pid]));

      var big = el("span", "big " + signCls(p.rw.v), signed(p.rw.v, 3));
      card.appendChild(big);
      card.appendChild(el("span", "big-sub",
        signed(p.rw100.v, 3) + " per 100 · " + p.rounds_elig + " eligible rounds"));

      card.appendChild(ciBar(p.rw100, lo, hi));

      var line = el("div", "statline");
      [
        ["Action", signed(p.ra, 3)],
        ["Clock", signed(p.rc, 3)],
        ["K / D / A", p.k + " / " + p.d + " / " + p.a],
        /* label from the dictionary: this is (K+A)/D, and calling it K/D was
           the defect two verifiers independently caught in the extractor */
        [D.dict.kda.sh, fmtKey("kda", p.kda)],
      ].forEach(function (pair) {
        var st = el("div", "stat");
        st.appendChild(el("span", "stat-k", pair[0]));
        st.appendChild(el("span", "stat-v", pair[1]));
        line.appendChild(st);
      });
      card.appendChild(line);
      card.appendChild(renderWaterfall(pid));
      host.appendChild(card);
    });

    var note = el("div", "verdict-note");

    /* One caption for both cards instead of the same 24-word sentence rendered
       twice, and the method name comes from the payload rather than being
       retyped here. */
    var cap = el("p", "lab");
    cap.appendChild(document.createTextNode(
      "95% interval on " + D.dict.rwpa100.sh + ", " + D.overall.p.m.rw100.mth + " over match clusters"));
    var capIb = infoButton(["rwpa100", "c_fixed_oof"], D.dict.rwpa100.lbl);
    if (capIb) cap.appendChild(capIb);
    note.appendChild(cap);

    /* The standing caption is shipped by the release precisely so the
       no-ranking statement is visible without interaction. It may not become a
       `?`, and the two paragraphs that used to follow it are now the forest
       plot below: the paired difference is its Difference group, the duo's
       method-sensitivity is its dashed basic-bootstrap row. */
    var lead = el("p");
    lead.appendChild(el("strong", null, D.meta.gate.standing_caption));
    note.appendChild(lead);

    note.appendChild(renderScenarios());
    host.appendChild(note);
  }

  /* ---------- match table ---------- */
  var matchSort = { key: "seq", dir: -1 };
  /* one shared magnitude domain for the RWPA columns — rule 7 */
  var MATCH_MAG = (function () {
    var mx = 0;
    D.matches.forEach(function (m) {
      PLAYERS.forEach(function (pid) { mx = Math.max(mx, Math.abs(m.p[pid].rw)); });
    });
    return mx || 1;
  })();

  /* Metric-major, not player-major. The previous layout pushed four columns per
     player in sequence, which put the two numbers a reader most wants to compare
     three columns and ~390px apart. Grouping by metric makes that comparison a
     single short saccade, and the two player hues then mark the two columns
     INSIDE each pair rather than separating them.

     Action and /100 are gone from this table. Action correlates r = 0.995 with
     RWPA at match level and they are identical to 2dp on most matches — two
     columns saying one thing. /100 was an em dash on 14 of 34 cells because of
     the (correct) r100_ok suppression, and where it did render it correlated
     0.99 with the RWPA beside it, because within one match the denominator is
     nearly constant. Per-100 earns its place at cohort level, where the
     denominators genuinely differ, and it is already on the verdict card. */
  var MATCH_COLS = [
    { k: "det", lbl: "Date", cls: "l", get: function (m) { return m.det; } },
    { k: "map", lbl: "Map", cls: "l", get: function (m) { return m.map; } },
    { k: "sf", lbl: "Score", get: function (m) { return m.sf - m.sa; }, cell: scoreCell },
    { k: "rn", lbl: "Rounds", get: function (m) { return m.rn; },
      cell: function (m) {
        var e = el("span", m.el < m.rn ? "dim" : null, m.el + "/" + m.rn);
        if (m.el < m.rn) e.title = (m.rn - m.el) + " rounds not measured";
        return e;
      } },
  ];
  var MATCH_GROUPS = [{ lbl: "", span: 4 }];

  [
    { key: "kda", lbl: "K / D / A",
      get: function (m, pid) { return m.p[pid].kda; },
      cell: function (m, pid) {
        var q = m.p[pid];
        var e = el("span", null, q.k + "/" + q.d + "/" + q.a);
        e.title = D.dict.kda.lbl + " " + fmtKey("kda", q.kda) + " — " + D.dict.kda.def;
        return e;
      } },
    { key: "rw", lbl: "RWPA", mag: true,
      get: function (m, pid) { return m.p[pid].rw; },
      cell: function (m, pid) { return el("span", signCls(m.p[pid].rw), signed(m.p[pid].rw, 3)); } },
  ].forEach(function (g) {
    MATCH_GROUPS.push({ lbl: g.lbl, span: 2 });
    PLAYERS.forEach(function (pid) {
      MATCH_COLS.push({
        k: pid + "_" + g.key, grp: pid, mag: g.mag,
        lbl: SHORT[pid] === "MartinLutherKing" ? "Martin" : "SN0RLAX",
        get: function (m) { return g.get(m, pid); },
        cell: function (m) { return g.cell(m, pid); },
      });
    });
  });

  function scoreCell(m) {
    var w = el("span");
    w.appendChild(el("span", null, m.sf + "–" + m.sa + " "));
    w.appendChild(el("span", "chip " + (m.o === "W" ? "w" : m.o === "L" ? "l" : ""), m.o));
    return w;
  }

  /* a magnitude bar sharing one scale across the column, drawn from a zero rule.
     Direction carries the sign; a negative bar is hollowed rather than recoloured. */
  function rwpaCell(v, pid, scale) {
    var wrap = el("span");
    wrap.appendChild(el("span", signCls(v), signed(v, 3)));
    var bar = el("span", "bar");
    var i = el("i", v < 0 ? "down" : null);
    var frac = Math.min(1, Math.abs(v) / scale) * 50;
    if (v >= 0) { i.style.left = "50%"; i.style.width = frac + "%"; }
    else { i.style.right = "50%"; i.style.width = frac + "%"; }
    bar.appendChild(i);
    wrap.appendChild(bar);
    return wrap;
  }

  function renderMatchTable() {
    var table = document.querySelector("[data-match-table]");
    Array.prototype.slice.call(table.querySelectorAll("thead,tbody")).forEach(function (n) { n.remove(); });

    var thead = el("thead");
    var grpRow = el("tr", "grouprow");
    MATCH_GROUPS.forEach(function (g, i) {
      var th = el("th", i === 0 ? "l" : null, g.lbl);
      th.colSpan = g.span;
      grpRow.appendChild(th);
    });
    thead.appendChild(grpRow);

    var colRow = el("tr", "colrow");
    MATCH_COLS.forEach(function (c) {
      var th = el("th", (c.cls || "") + (c.grp ? " g-" + c.grp : ""));
      var btn = el("span", null, c.lbl + (matchSort.key === c.k ? (matchSort.dir > 0 ? " ▲" : " ▼") : ""));
      th.appendChild(btn);
      th.setAttribute("role", "button");
      th.setAttribute("tabindex", "0");
      th.style.cursor = "pointer";
      var doSort = function () {
        matchSort.dir = matchSort.key === c.k ? -matchSort.dir : -1;
        matchSort.key = c.k;
        renderMatchTable();
      };
      th.addEventListener("click", doSort);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doSort(); } });
      colRow.appendChild(th);
    });
    thead.appendChild(colRow);
    table.appendChild(thead);

    var col = MATCH_COLS.filter(function (c) { return c.k === matchSort.key; })[0];
    var rows = D.matches.slice();
    if (col) {
      rows.sort(function (a, b) {
        var av = col.get(a), bv = col.get(b);
        if (av === null) return 1;
        if (bv === null) return -1;
        if (typeof av === "string") return av.localeCompare(bv) * matchSort.dir;
        return (av - bv) * matchSort.dir;
      });
    } else {
      rows.sort(function (a, b) { return (b.seq - a.seq); });
    }

    var tbody = el("tbody");
    rows.forEach(function (m) {
      var tr = el("tr", "clickable");
      tr.setAttribute("tabindex", "0");
      tr.setAttribute("role", "link");
      tr.setAttribute("aria-label", m.map + " " + m.det + " " + m.res + " — open round ledger");
      MATCH_COLS.forEach(function (c) {
        var td = el("td", (c.cls || "") + (c.grp ? " " + c.grp + "-cell" : "") + (c.mag ? " mag" : ""));
        if (c.cell) td.appendChild(c.cell(m));
        else td.textContent = c.get(m);
        if (c.mag) {
          var v = c.get(m), frac = Math.min(1, Math.abs(v) / MATCH_MAG) * 50;
          td.style.setProperty("--mag-w", frac + "%");
          td.style.setProperty("--mag-l", v >= 0 ? "50%" : (50 - frac) + "%");
          td.style.setProperty("--mag-c", "var(--" + (v >= 0 ? "pos" : "neg") + ")");
        }
        tr.appendChild(td);
      });
      var go = function () { location.hash = "#/m/" + m.id; };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }
  function spanTh(text, span, cls) {
    var th = el("th", cls, text);
    th.colSpan = span;
    return th;
  }

  /* ---------- beyond the headline ---------- */
  /* Everything the release built that is not the headline ledger. It is here
     because it is the interesting part for two people reading about their own
     games — and it is visually demoted, tier-flagged and caveat-marked because
     the release is explicit that none of it ranks anybody and none of it adds
     to RWPA. Blocks are ordered by how directly they describe the pair. */
  /* The note under each panel heading is gone; what it said is either drawn or
     sits on the heading's own `?`. */
  function panel(title, infoSrc, infoLabel) {
    var p = el("div", "layer");
    var h = el("h3", null, title);
    var ib = infoSrc ? infoButton(infoSrc, infoLabel) : null;
    if (ib) h.appendChild(ib);
    p.appendChild(h);
    return p;
  }

  /* ---------- F4 · a win rate against the cohort baseline ---------- */
  /* The dashed cohort rule is not decoration — it is the mitigation for
     c_mechanical. A bare 93% bar invites "so being action-positive together
     CAUSES wins"; the rule reframes it as 93% against a base rate, which is
     what a descriptive split actually looks like.

     Monochrome, per the two-palette rule: a win rate is not a signed
     probability change and may not borrow green/red, and a slice of rounds is
     not a person and may not borrow amber/cyan. */
  /* No fig-title: the panel's own <h3> already names the split, the axis is
     labelled 0-100%, and every row carries its slice name. A second heading
     saying the same thing in different words is the prose this rewrite is
     removing. `label` is the accessible name only. */
  function winRateFig(label, rows) {
    var c = D.meta.cohort;
    var baseline = c.round_rec_elig && c.elig_rounds
      ? c.round_rec_elig.w / c.elig_rounds : null;
    var floor = D.meta.gate.min_elig_rounds_for_rate;

    /* Natural width is chosen so this figure scales by roughly the same factor
       as the waterfall and the forest plot in a full-width panel. A viewBox
       narrow enough to look right on its own renders its 10.5px labels at 18px
       once stretched to 1144, which reads as a different type system from every
       other figure on the page. */
    var W = 950, rowH = 30, padL = 210, padR = 185, top = 34;
    var H = rows.length * rowH + top + 24;
    var x = function (v) { return padL + v * (W - padL - padR); };

    var fig = el("div", "fig");
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    var t = svgEl("title", {});
    t.textContent = label + ". Round win rate per slice against a cohort baseline of " +
      (baseline === null ? "unknown" : fmtKey("wr", baseline)) + ".";
    svg.appendChild(t);

    if (baseline !== null) {
      svg.appendChild(svgEl("line", { class: "ref-rule",
        x1: x(baseline), x2: x(baseline), y1: top - 12, y2: top + rows.length * rowH }));
      var bl = svgEl("text", { x: x(baseline), y: top - 17, "text-anchor": "middle" });
      bl.textContent = "cohort " + fmtKey("wr", baseline);
      svg.appendChild(bl);
    }

    rows.forEach(function (r, i) {
      var cy = top + i * rowH + rowH / 2;
      var lab = svgEl("text", { x: padL - 10, y: cy + 3.5, "text-anchor": "end" });
      lab.textContent = r.lbl;
      svg.appendChild(lab);

      /* C4: below the exposure floor the rate is suppressed, not shrunk. The
         words stand where the bar and the number would have been. */
      if (r.rounds < floor) {
        var sup = svgEl("text", { x: padL + 2, y: cy + 3.5 });
        sup.textContent = "rate suppressed — under " + floor + " eligible rounds";
        svg.appendChild(sup);
      } else {
        svg.appendChild(svgEl("rect", { x: x(0), y: cy - 6, width: Math.max(1, x(r.wr) - x(0)),
          height: 12, fill: "var(--muted)", opacity: .55 }));
        var vv = svgEl("text", { class: "val", x: W - padR + 8, y: cy + 3.5 });
        vv.textContent = fmtKey("wr", r.wr);
        svg.appendChild(vv);
      }
      var nn = svgEl("text", { x: W - 2, y: cy + 3.5, "text-anchor": "end" });
      nn.textContent = r.rounds + " rounds";
      svg.appendChild(nn);
    });

    var ay = top + rows.length * rowH + 2;
    svg.appendChild(svgEl("line", { class: "axis-line", x1: x(0), x2: x(1), y1: ay, y2: ay }));
    [0, .25, .5, .75, 1].forEach(function (v) {
      svg.appendChild(svgEl("line", { class: "ref-tick", x1: x(v), x2: x(v), y1: ay, y2: ay + 4 }));
      var lb = svgEl("text", { x: x(v), y: ay + 15, "text-anchor": "middle" });
      lb.textContent = Math.round(v * 100) + "%";
      svg.appendChild(lb);
    });
    fig.appendChild(figScroll(svg, W));
    return fig;
  }

  /* ---------- F5 · floor and ceiling ---------- */
  /* Drawn ONLY from overall.consist[pid].match, never from matches[].p[].r100.
     A per-match strip of per-100 values is the obvious build and it is
     forbidden: c_suppressed_rate is blocking, a large share of matches fall
     under the exposure floor, and plotting them would publish exactly the
     single-match extremes the release suppresses. This summary object is the
     licensed source and it ships its own intervals. */
  function rangeFig() {
    var W = 950, rowH = 42, padL = 170, padR = 230;
    var H = PLAYERS.length * rowH + 38;

    var lo = 0, hi = 0;
    PLAYERS.forEach(function (pid) {
      var mm = D.overall.consist[pid].match;
      ["floor", "ceil"].forEach(function (k) {
        lo = Math.min(lo, mm[k].lo, mm[k].v);
        hi = Math.max(hi, mm[k].hi, mm[k].v);
      });
      lo = Math.min(lo, mm.mean.v); hi = Math.max(hi, mm.mean.v);
    });
    var pad = Math.max(0.25, (hi - lo) * 0.06);
    lo -= pad; hi += pad;
    var x = function (v) { return padL + ((v - lo) / (hi - lo)) * (W - padL - padR); };

    var fig = el("div", "fig");
    var ttl = el("p", "fig-title", D.dict.rwpa100.sh + " · one match at a time");
    var tf = tierFlag("cons_floor");
    if (tf) ttl.appendChild(tf);
    var ib = infoButton(["cons_floor", "cons_ceil", "cons_dsd", "cons_carry"], "floor and ceiling");
    if (ib) ttl.appendChild(ib);
    fig.appendChild(ttl);

    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    var t = svgEl("title", {});
    t.textContent = "Match-level range of RWPA per 100 rounds for each player: a bar from floor " +
      "to ceiling, a dot at the mean, and percentile whiskers on each endpoint.";
    svg.appendChild(t);
    svg.appendChild(svgEl("line", { class: "zero-line", x1: x(0), x2: x(0), y1: 4, y2: PLAYERS.length * rowH + 4 }));

    PLAYERS.forEach(function (pid, i) {
      var mm = D.overall.consist[pid].match;
      var cy = 8 + i * rowH + rowH / 2 - 6;
      var hue = pid === "m" ? "rng-m" : "rng-s";

      ["floor", "ceil"].forEach(function (k) {
        svg.appendChild(svgEl("line", { class: hue, x1: x(mm[k].lo), x2: x(mm[k].hi),
          y1: cy, y2: cy, "stroke-width": 1, opacity: .5 }));
      });
      svg.appendChild(svgEl("line", { class: hue, x1: x(mm.floor.v), x2: x(mm.ceil.v),
        y1: cy, y2: cy, "stroke-width": 5 }));
      /* the mean sits ON its own bar, so it needs a panel-coloured ring to read
         at all — same hue, same palette, just not invisible against itself */
      svg.appendChild(svgEl("circle", { class: pid === "m" ? "dot-m" : "dot-s",
        cx: x(mm.mean.v), cy: cy, r: 3.5,
        stroke: "var(--panel-2)", "stroke-width": 1.5 }));

      var lab = svgEl("text", { x: padL - 10, y: cy + 3.5, "text-anchor": "end" });
      lab.textContent = SHORT[pid] === "MartinLutherKing" ? "Martin" : SHORT[pid];
      lab.setAttribute("fill", "var(--" + (pid === "m" ? "martin" : "snorlax") + ")");
      svg.appendChild(lab);

      var r1 = svgEl("text", { x: W - padR + 10, y: cy });
      r1.textContent = "downside " + mm.dsd.v.toFixed(2);
      svg.appendChild(r1);
      var r2 = svgEl("text", { x: W - padR + 10, y: cy + 12 });
      r2.textContent = "carry " + fmtKey("cons_carry", mm.carry.v);
      svg.appendChild(r2);
    });

    var ay = 8 + PLAYERS.length * rowH - 2;
    svg.appendChild(svgEl("line", { class: "axis-line", x1: x(lo), x2: x(hi), y1: ay, y2: ay }));
    var LAD = [1, 2, 5, 10, 20];
    var st = LAD.filter(function (v) { return v >= (hi - lo) / 5; })[0] || 20;
    for (var v = Math.ceil(lo / st) * st; v <= hi; v += st) {
      svg.appendChild(svgEl("line", { class: "ref-tick", x1: x(v), x2: x(v), y1: ay, y2: ay + 4 }));
      var lb = svgEl("text", { x: x(v), y: ay + 15, "text-anchor": "middle" });
      lb.textContent = (v > 0 ? "+" : "") + v;
      svg.appendChild(lb);
    }
    fig.appendChild(figScroll(svg, W));
    return fig;
  }

  function miniTable(headers, rows) {
    var wrap = el("div", "table-wrap");
    var t = el("table");
    var thead = el("thead");
    var hr = el("tr", "colrow");
    headers.forEach(function (h, i) {
      var th = el("th", i === 0 ? "l" : null);
      if (h && h.nodeType) th.appendChild(h);
      else th.textContent = h;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    t.appendChild(thead);
    var tb = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      r.forEach(function (c, i) {
        var td = el("td", i === 0 ? "l" : null);
        if (c && c.nodeType) td.appendChild(c);
        else td.textContent = c;
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  function withFlags(text, dictKey, cavIds) {
    var meta = D.dict[dictKey];
    var span = el("span");
    /* the payload ships a short label per metric; use it so a column heading
       cannot drift away from the definition the marker explains */
    var label = el("span", null, text || (meta && meta.sh) || dictKey);
    if (meta) label.title = meta.lbl + " — " + meta.def + "\n\nSource: " + meta.src;
    span.appendChild(label);
    var tf = tierFlag(dictKey);
    if (tf) span.appendChild(tf);
    var cm = caveatMark(cavIds || (meta && meta.cav));
    if (cm) span.appendChild(cm);
    return span;
  }

  var CTRL = { neither: "Neither of us", exactly_one: "One of us", both: "Both of us" };
  var OPEN_SRC = { m: "MartinLutherKing", s: "SN0RLAX", T: "A teammate", O: "An opponent" };

  function renderLayers() {
    var host = document.querySelector("[data-layers]");
    if (!host) return;
    host.innerHTML = "";
    var o = D.overall;

    /* c_no_layer_sum is blocking, ten words long, and the only thing standing
       between this section and the worst available misread. It stays as literal
       visible text; the full body is on its `?`. */
    var sum = document.querySelector("[data-layer-sum]");
    if (sum && !sum.querySelector(".info")) {
      var sib = infoButton(["c_no_layer_sum"], D.meta.cav.c_no_layer_sum.t);
      if (sib) sum.appendChild(sib);
    }

    /* --- the pair --- */
    /* The wins column is dropped from both of these: it is round(wr × rounds)
       and printing it a third time adds nothing. */
    var a = panel("Rounds where we were both doing something", ["ctrl", "wr"], D.dict.ctrl.lbl);
    a.appendChild(winRateFig("Round win rate by how many of us were action-positive",
      o.control.map(function (c) {
        return { lbl: CTRL[c.cat] || c.cat, rounds: c.rounds, wr: c.wr };
      })));
    host.appendChild(a);

    var b = panel("Who took the opening duel", ["wr", "c_role_volume"], D.dict.wr.lbl);
    b.appendChild(winRateFig("Round win rate by who drew first blood",
      o.opening.map(function (c) {
        return { lbl: OPEN_SRC[c.src] || c.src, rounds: c.rounds, wr: c.wr };
      })));
    host.appendChild(b);

    /* The trade table stays a table: five heterogeneous columns, no shared
       scale, nothing to chart. Its definition — with the real window and the
       denominator the prose omitted — is on the heading's `?`. */
    var c = panel("Trading each other", ["trade_link"], D.dict.trade_link.lbl);
    c.appendChild(miniTable(
      ["Direction", withFlags("Direct", "trade_link"), "Broad response", "Median gap", "Share of their traded deaths"],
      o.trade.map(function (t) {
        return [
          SHORT[t.from] + " trades " + SHORT[t.to],
          t.direct, t.broad,
          (t.med_ms / 1000).toFixed(2) + "s",
          fmtSpec(D.meta.fmt.pct1, t.share_of_targets_direct_traded_deaths),
        ];
      })));
    host.appendChild(c);

    /* --- per player, still not a ranking --- */
    var d = panel("Floor and ceiling");
    d.appendChild(rangeFig());
    host.appendChild(d);

    /* The "Other model layers" row is gone. It carried match WPA, lobby-adjusted
       RWPA, future economy, clutch conversion and traded-death rate side by side
       — five metrics in five different units (expected match points, RWPA per
       100, next-round win probability per transition, share of clean
       opportunities, share of eligible deaths), with abbreviated headers, no
       units printed and no shared denominator. Nothing in that row could be
       compared with anything else in it, including by the two people it was
       about. Each of those metrics either earns its own block with its unit
       stated, or it does not belong on the page. */

    /* --- the negative result, shown rather than dropped --- */
    /* F7: the two status tokens and the four gate failures are one visual list
       of six facts instead of a sentence with <code> embedded twice. The
       message itself is one payload sentence and stays visible — a negative
       result that only appears on hover is a negative result that was hidden. */
    var r = el("div", "layer rejected");
    var rh = el("h3", null, "Adjusted round impact — rejected");
    var rib = infoButton(["ari"], D.dict.ari.lbl);
    if (rib) rh.appendChild(rib);
    r.appendChild(rh);
    var rp = el("p", "note");
    rp.appendChild(el("strong", null, D.meta.tier.r.lbl + "."));
    rp.appendChild(document.createTextNode(" " + o.ari.msg));
    r.appendChild(rp);

    var chips = el("p", "chips");
    [o.ari.status, o.ari.pair_status].concat(o.ari.gate_failures || []).forEach(function (tok) {
      if (!tok) return;
      chips.appendChild(el("code", "gate-chip", "✗ " + String(tok).replace(/_/g, " ")));
    });
    r.appendChild(chips);
    host.appendChild(r);
  }

  /* ---------- F6 · evidence registry ---------- */
  /* Provenance, not an estimand, so it carries no caveat and no sign colour:
     the four classes step down through one neutral in fixed order of epistemic
     standing, never sorted by count. */
  var REG_CLASS = [
    ["validated_predictive", 1], ["descriptive", .62],
    ["exploratory", .38], ["rejected", 0],
  ];

  function renderProvenance() {
    var f = document.querySelector("[data-provenance]");
    f.innerHTML = "";
    var line = el("p", "foot-line");
    line.innerHTML =
      "Release <code>" + D.meta.release + "</code> · SHA-256 <code>" +
      D.meta.manifest_sha256.slice(0, 16) + "…</code> · " + D.meta.built_at.slice(0, 10) +
      " · <code>python3 -m valorant_impact.dashboard_data</code>";
    f.appendChild(line);

    var reg = D.overall.registry;
    if (!reg || !reg.rows) return;
    var w = Math.max(320, Math.round(f.clientWidth || 900));
    var h = 58, barY = 6, barH = 14;

    var fig = el("div", "fig");
    var svg = svgEl("svg", { viewBox: "0 0 " + w + " " + h, role: "img" });
    var t = svgEl("title", {});
    t.textContent = reg.rows + " rows in the evidence registry, " + reg.interval_supported +
      " carrying an interval and " + reg.player_facing_supported + " player-facing and supported.";
    svg.appendChild(t);
    svg.appendChild(hatchDefs("reg-hatch"));

    var x = 0;
    REG_CLASS.forEach(function (c, i) {
      var n = (reg.by_class && reg.by_class[c[0]]) || 0;
      if (!n) return;
      var wd = (n / reg.rows) * w;
      svg.appendChild(svgEl("rect", { x: x, y: barY, width: Math.max(1, wd), height: barH,
        fill: c[1] ? "var(--muted)" : "var(--line-2)", opacity: c[1] || 1 }));
      if (!c[1]) {
        svg.appendChild(svgEl("rect", { x: x, y: barY, width: Math.max(1, wd), height: barH,
          fill: "url(#reg-hatch)", opacity: .85 }));
      }
      if (i) svg.appendChild(svgEl("line", { class: "seg", x1: x, x2: x, y1: barY, y2: barY + barH }));
      x += wd;
    });

    /* Both marks land inside the first segment, a few percent apart, so their
       labels get a line each rather than colliding at the left edge. The tick
       drop grows with the row so each label is unambiguously joined to its own
       mark. */
    [[reg.interval_supported, "carry an interval"],
      [reg.player_facing_supported, "player-facing and supported"]].forEach(function (mark, i) {
      var tx = (mark[0] / reg.rows) * w;
      var ly = barY + barH + 14 + i * 13;
      svg.appendChild(svgEl("line", { class: "ref-tick", x1: tx, x2: tx, y1: barY - 4, y2: ly - 8 }));
      var lb = svgEl("text", { class: "val", x: tx + 4, y: ly });
      lb.textContent = mark[0] + " " + mark[1];
      svg.appendChild(lb);
    });
    fig.appendChild(svg);

    var legend = el("p", "walk-legend");
    REG_CLASS.forEach(function (c) {
      var n = (reg.by_class && reg.by_class[c[0]]) || 0;
      if (!n) return;
      legend.appendChild(swatchSpan("block reg-" + c[0], n + " " + c[0].replace(/_/g, " ")));
    });
    fig.appendChild(legend);
    f.appendChild(fig);
  }

  /* ============================ MATCH VIEW ============================ */

  var currentMatch = null;
  var openRound = null;

  function matchById(id) {
    return D.matches.filter(function (m) { return m.id === id; })[0];
  }

  function renderMatch(m) {
    currentMatch = m;
    openRound = null;
    var host = document.querySelector("[data-match-body]");
    host.innerHTML = "";

    var head = el("div", "match-head");
    var left = el("div");
    left.appendChild(el("p", "eyebrow", "Match " + m.seq + " of " + D.matches.length + " · " + m.det));
    left.appendChild(el("h1", null, m.map));
    head.appendChild(left);

    var score = el("div");
    var sc = el("div", "match-score", m.sf + " – " + m.sa);
    score.appendChild(sc);
    var facts = el("div", "match-facts");
    facts.appendChild(el("span", null, m.o === "W" ? "Win" : m.o === "L" ? "Loss" : "Draw"));
    facts.appendChild(el("span", null, m.rn + " rounds"));
    facts.appendChild(el("span", null, m.el + " measured"));
    /* A round scored as a four-versus-five is a fact about the lobby, so it
       goes in the fact row beside the two round counts — the paragraph that
       used to call these rounds "not measured" would now be actively false. */
    if (m.dg > 0) facts.appendChild(el("span", null, m.dg + " as 4v5"));
    if (m.dur) facts.appendChild(el("span", null, fmtSpec({ kind: "duration_ms" }, m.dur)));
    score.appendChild(facts);
    head.appendChild(score);
    host.appendChild(head);

    /* per-player summary */
    var cards = el("div", "verdict");
    PLAYERS.forEach(function (pid) {
      var p = m.p[pid];
      var card = el("div", "card " + pid);
      card.appendChild(el("h3", null, SHORT[pid] + " · " + p.ag));
      card.appendChild(el("span", "big " + signCls(p.rw), signed(p.rw, 3)));
      card.appendChild(el("span", "big-sub", p.r100_ok
        ? signed(p.r100, 2) + " per 100 rounds"
        : "rate suppressed — under " + D.meta.gate.min_elig_rounds_for_rate + " eligible rounds"));
      var line = el("div", "statline");
      [
        ["K / D / A", p.k + " / " + p.d + " / " + p.a],
        ["ADR", p.adr.toFixed(1)],
        ["ACS", p.acs.toFixed(1)],
        ["Action", signed(p.ra, 3)],
        ["Clock", signed(p.rc, 3)],
        ["Act tier", p.tier],
      ].forEach(function (pair) {
        var st = el("div", "stat");
        st.appendChild(el("span", "stat-k", pair[0]));
        st.appendChild(el("span", "stat-v", pair[1]));
        line.appendChild(st);
      });
      card.appendChild(line);
      cards.appendChild(card);
    });
    host.appendChild(cards);

    /* the strip */
    var strip = el("div", "strip");
    var fig = svgEl("svg", { class: "strip-figure", "data-strip": "", role: "img" });
    var ttl = svgEl("title", {});
    ttl.textContent = "Round-by-round RWPA. " + SHORT.m + " above the axis, " + SHORT.s + " below.";
    fig.appendChild(ttl);
    strip.appendChild(fig);
    /* Marks only. Each player's zero line is drawn and labelled, and "click to
       open" is a cursor:pointer affordance the sentence was duplicating. */
    var legend = el("p", "walk-legend");
    legend.appendChild(swatchSpan("m", SHORT.m));
    legend.appendChild(swatchSpan("s", SHORT.s));
    if (m.rs.some(function (r) { return !r.el; })) {
      legend.appendChild(swatchSpan("hatch", "no scorable endpoint"));
    }
    if (m.rs.some(isDegraded)) legend.appendChild(swatchSpan("tick", "scored 4v5"));
    strip.appendChild(legend);
    host.appendChild(strip);

    /* round ledger */
    var sh = el("div", "section-head");
    sh.appendChild(el("h2", null, "Rounds"));
    host.appendChild(sh);

    var wrap = el("div", "table-wrap");
    var table = el("table");
    table.setAttribute("data-round-table", "");
    wrap.appendChild(table);
    host.appendChild(wrap);

    var sheetHost = el("div", "sheet-host");
    sheetHost.id = "round-sheet";
    sheetHost.setAttribute("data-round-sheet", "");
    sheetHost.setAttribute("aria-live", "polite");
    host.appendChild(sheetHost);

    /* prev / next */
    var nav = el("div", "match-nav");
    var prev = el("button", null, "← Previous match");
    var next = el("button", null, "Next match →");
    var idx = D.matches.indexOf(m);
    prev.disabled = idx <= 0;
    next.disabled = idx >= D.matches.length - 1;
    prev.addEventListener("click", function () { location.hash = "#/m/" + D.matches[idx - 1].id; });
    next.addEventListener("click", function () { location.hash = "#/m/" + D.matches[idx + 1].id; });
    nav.appendChild(prev); nav.appendChild(next);
    host.appendChild(nav);

    renderRounds(m, table);
    renderStrip(m);
  }

  /* Enum legends come from the payload. Two of these codes collide across
     fields — "d" is defense in `sd` but disadvantage in `ec`, "a" is attack in
     `sd` but advantage in `ec` — which is exactly the kind of thing a hardcoded
     lookup in this file gets wrong once and never gets caught. */
  function code(field, v, short) {
    var map = D.meta.code[field] || {};
    var full = map[v] || v;
    if (!short) return full;
    /* Table columns are narrow, so the long form goes in the title. A word-like
       token ("timer_expired") prettifies better than the sentence it maps to
       truncates ("All opponents eliminated" -> "All opponents"); a one-letter
       token ("w", "a", "d") carries nothing, so trim the sentence instead. */
    if (String(v).length > 2) {
      var t = String(v).replace(/_/g, " ");
      return t.charAt(0).toUpperCase() + t.slice(1);
    }
    return full.split(" (")[0].split(" ").slice(0, 2).join(" ");
  }
  var SIDE = D.meta.code.sd;
  var TERM = D.meta.code.tr;

  /* r.sf/r.sa are the running score BEFORE the round. Printing that made round 1
     read "0-0" and round 2 carry round 1's result, so the ledger looked like it
     started at round 2 — which is exactly how it was reported. A scoreboard
     shows the score once the round is over, so that is what this returns. */
  function scoreAfter(r) {
    return [r.sf + (r.w ? 1 : 0), r.sa + (r.w ? 0 : 1)];
  }

  function renderRounds(m, table) {
    table.innerHTML = "";
    var maxAbs = 0;
    m.rs.forEach(function (r) {
      PLAYERS.forEach(function (pid) {
        var pr = r.p[pid];
        if (pr && typeof pr.rw === "number") maxAbs = Math.max(maxAbs, Math.abs(pr.rw));
      });
    });
    maxAbs = maxAbs || 1;

    var thead = el("thead");
    var grp = el("tr", "grouprow");
    grp.appendChild(spanTh("", 6, "l"));
    /* Both players' RWPA side by side on a single round is the one place this
       page could quietly become a scoreboard. dict.rw_r ends by saying this
       licenses no comparison between the two on any single round, so it sits on
       each of the two column groups where the temptation is. */
    PLAYERS.forEach(function (pid) {
      var th = el("th", "g-" + pid, SHORT[pid]);
      th.colSpan = 3;
      var ib = infoButton(["rw_r", "c_no_rank"], D.dict.rw_r.lbl);
      if (ib) th.appendChild(ib);
      grp.appendChild(th);
    });
    thead.appendChild(grp);

    /* Clock is deliberately not a column here: it is ±0.01 on most rounds and
       RWPA − Action recovers it exactly. The full split is in the row detail. */
    var cols = ["#", "Side", "Result", "Ended", "Econ", "Opening"];
    PLAYERS.forEach(function () { cols.push("K/D/A", "Action", "RWPA"); });
    var colRow = el("tr", "colrow");
    cols.forEach(function (c, i) { colRow.appendChild(el("th", i < 6 && i !== 0 ? "l" : null, c)); });
    thead.appendChild(colRow);
    table.appendChild(thead);

    var tbody = el("tbody");
    m.rs.forEach(function (r) {
      var tr = el("tr", "clickable" + (r.el ? "" : " excluded"));
      tr.setAttribute("tabindex", "0");

      var nCell = el("td", null);
      nCell.appendChild(el("span", "chev", "›"));
      nCell.appendChild(document.createTextNode(
        r.n + (r.pi ? " ·P" : "") + (r.ot ? " ·OT" : "")));
      /* A degraded round is scored. It gets a provenance mark alongside the
         pistol and overtime markers, never the not-measured treatment. */
      if (isDegraded(r)) nCell.appendChild(el("span", "dim", " ·4v5"));
      tr.appendChild(nCell);

      var side = el("td", "l");
      side.appendChild(el("span", "chip " + (r.sd === "a" ? "atk" : "def"), SIDE[r.sd]));
      tr.appendChild(side);


      var res = el("td", "l");
      res.appendChild(el("span", "chip " + (r.w ? "w" : "l"), r.w ? "Won" : "Lost"));
      res.appendChild(el("span", "dim num", " " + scoreAfter(r).join("–")));
      tr.appendChild(res);

      var term = el("td", "l dim", code("tr", r.tr, true));
      term.title = code("tr", r.tr);
      tr.appendChild(term);

      var econ = el("td", "l dim", code("ec", r.ec, true));
      econ.title = code("ec", r.ec);
      tr.appendChild(econ);

      var open = el("td", "l dim", r.os ? code("os", r.os) : "—");
      tr.appendChild(open);

      PLAYERS.forEach(function (pid) {
        var pr = r.p[pid] || {};
        var kda = el("td", pid + "-cell");
        kda.textContent = (pr.k || 0) + "/" + (pr.d || 0) + "/" + (pr.a || 0);
        tr.appendChild(kda);

        if (!r.el || typeof pr.rw !== "number") {
          ["ra", "rw"].forEach(function () {
            var td = el("td", pid + "-cell dim", "—");
            td.title = D.meta.cav.c_not_measured.t + " — " + D.meta.cav.c_not_measured.b;
            tr.appendChild(td);
          });
        } else {
          var a = el("td", pid + "-cell " + signCls(pr.ra), signed(pr.ra, 3));
          var w = el("td", pid + "-cell");
          w.appendChild(rwpaCell(pr.rw, pid, maxAbs));
          tr.appendChild(a); tr.appendChild(w);
        }
      });

      tr.setAttribute("aria-expanded", "false");
      tr.setAttribute("aria-controls", "round-sheet");
      var toggle = function () { toggleRound(m, r, tr, tbody); };
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
      tr.setAttribute("data-round", r.i);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  /* ---------- the round sheet ---------- */
  /* THE ROW SET IS THE UNION OVER BOTH PLAYERS, NEVER PER-PLAYER.
     If either player has a value, the row renders for both.

     Its predecessor built `rows` inside PLAYERS.forEach with `if (pr.pl)`,
     `if (pr.df)`, `if (pr.oos)` gating pushes per player. The two lists then
     diverged in length on 223 of 376 rounds, so line N on the left was not
     line N on the right. The panel was not hard to compare — it was not
     comparable. Everything else here is secondary to that rule. */

  function sheetRow(cls, label, src, cells) {
    var tr = el("tr", cls || null);
    var td = el("td", "metric");
    td.appendChild(el("span", null, label));
    var ib = src ? infoButton(src) : null;
    if (ib) td.appendChild(ib);
    tr.appendChild(td);
    cells.forEach(function (c) { tr.appendChild(c); });
    return tr;
  }

  function valueCell(v, opts) {
    var td = el("td", "val");
    if (v === null || v === undefined) {
      td.appendChild(el("span", "v dim", "—"));
      return td;
    }
    var txt = opts.fmtKey ? fmtKey(opts.fmtKey, v) : fmtSpec(opts.spec, v);
    td.appendChild(el("span", "v " + (opts.signed ? signCls(v) : ""), txt));
    if (opts.scale) {
      var track = el("span", "track" + (opts.signed ? " signed" : ""));
      var i = el("i", opts.signed ? signCls(v) : "plain");
      var frac = Math.min(1, Math.abs(v) / opts.scale);
      if (opts.signed) {
        var half = frac * 50;
        if (v >= 0) { i.style.left = "50%"; i.style.width = half + "%"; }
        else { i.style.right = "50%"; i.style.width = half + "%"; }
      } else {
        i.style.left = "0";
        i.style.width = (frac * 100) + "%";
        if (Math.abs(v) > opts.scale) i.className += " over";
      }
      if (v !== 0) track.appendChild(i);
      td.appendChild(track);
    }
    return td;
  }

  function anyNonZero(r, key) {
    return PLAYERS.some(function (pid) {
      var pr = r.p[pid] || {};
      return typeof pr[key] === "number" && pr[key] !== 0;
    });
  }

  function buildSheet(m, r) {
    /* The round is measured if the LEDGER produced anything for it. Requiring
       both players to have credit was wrong once 4v5 rounds started counting:
       in a round one of them sat out, the other still played it and still has
       real numbers, and hiding the whole band threw those away. */
    var measured = PLAYERS.some(function (pid) {
      return r.p[pid] && typeof r.p[pid].rw === "number";
    });
    var table = el("table", "sheet");

    var cap = el("caption");
    cap.innerHTML = "<b>Round " + r.n + "</b> · " + code("tr", r.tr).toLowerCase() +
      " at " + (r.tt / 1000).toFixed(1) + "s · loadout " + r.lk.toLocaleString() +
      " against " + r.lko.toLocaleString() +
      ' · <span class="lab">' + D.meta.tier.d.lbl + " · round grain</span>";
    table.appendChild(cap);

    var thead = el("thead");
    var hr = el("tr");
    hr.appendChild(el("th", null, ""));
    PLAYERS.forEach(function (pid) {
      var th = el("th", "p-" + pid, SHORT[pid]);
      th.scope = "col";
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    /* ---- band 1: probability ---- */
    var tb = el("tbody");
    if (measured) {
      var axisMax = 0;
      PLAYERS.forEach(function (pid) {
        if (typeof r.p[pid].rw !== "number") return;
        ["kc", "dd", "pl", "df", "ra", "rc", "rw"].forEach(function (k) {
          var v = r.p[pid][k];
          if (typeof v === "number") axisMax = Math.max(axisMax, Math.abs(v));
        });
      });
      axisMax = Math.max(axisMax, 0.05);
      tb.appendChild(band("Probability", "signed · shared axis ±" + axisMax.toFixed(2) +
        " · green + / red −"));

      var sgn = function (k) {
        return function (pid) {
          var pr = r.p[pid];
          if (typeof pr.rw !== "number") {
            /* present in the lobby's scoreboard, absent from the round */
            var td = el("td", "val");
            var dash = el("span", "v dim", "—");
            dash.title = SHORT[pid] + " was not playing this round, so the ledger " +
              "credits them nothing. A 0.0000 here would say they were present " +
              "and did nothing.";
            td.appendChild(dash);
            return td;
          }
          return valueCell(pr[k], { spec: { dec: 4, sign: true }, signed: true, scale: axisMax });
        };
      };
      tb.appendChild(sheetRow(null, "Kill credit", "kc_r", PLAYERS.map(sgn("kc"))));
      tb.appendChild(sheetRow(null, deathLabel(r), "dd_r", PLAYERS.map(sgn("dd"))));
      if (anyNonZero(r, "pl")) tb.appendChild(sheetRow(null, "Plant credit", "pl_r", PLAYERS.map(sgn("pl"))));
      if (anyNonZero(r, "df")) tb.appendChild(sheetRow(null, "Defuse credit", "df_r", PLAYERS.map(sgn("df"))));
      tb.appendChild(sheetRow("rule-sum", "Action", "ra_r", PLAYERS.map(sgn("ra"))));
      tb.appendChild(sheetRow(null, "Clock share", "rc_r", PLAYERS.map(sgn("rc"))));
      /* The precision footnote lives here, where the 0.0001 discrepancy between
         a component and its own subtotal is actually noticed, rather than as a
         four-line footer under every open round. */
      var rwSrc = ["rw_r", { lbl: "Precision", body: D.meta.precision.note }];
      if (r.dr && D.meta.xr[r.dr]) {
        rwSrc.push({ lbl: "Scored four-versus-five", body: D.meta.xr[r.dr] });
      }
      tb.appendChild(sheetRow("rule-total total", "Round RWPA", rwSrc, PLAYERS.map(sgn("rw"))));
      if (PLAYERS.some(function (pid) { return r.p[pid].oos; })) {
        tb.appendChild(sheetRow("aside", "Out of support — not in the total", "oos_r",
          PLAYERS.map(function (pid) {
            var o = r.p[pid].oos;
            return valueCell(o ? o[1] : 0, { spec: { dec: 4, sign: true }, signed: true });
          })));
      }
    } else {
      tb.appendChild(band("Probability", "not measured"));
      var tr = el("tr");
      var td = el("td", "notmeasured");
      td.colSpan = 3;
      /* The em dash and the payload's own sentence naming the actual cause stay
         visible; the boundary and the gate-token decode go behind the `?`. */
      td.appendChild(document.createTextNode("— "));
      td.appendChild(el("b", null, r.xt || "Round not measured."));
      var nib = infoButton(["r_xt", "c_not_measured",
        { lbl: "Gate " + r.xr, body: D.meta.xr[r.xr] || r.xr }], "this unscored round");
      if (nib) td.appendChild(nib);
      tr.appendChild(td);
      tb.appendChild(tr);
    }
    table.appendChild(tb);

    /* ---- band 2: combat and economy ---- */
    var tb2 = el("tbody");
    tb2.appendChild(band("Combat & economy", "unsigned · bars scaled to the corpus 95th percentile"));
    tb2.appendChild(sheetRow(null, "Kills / deaths / assists", "pr_k", PLAYERS.map(function (pid) {
      var pr = r.p[pid];
      var td = el("td", "val");
      td.appendChild(el("span", "v", pr.k + " / " + pr.d + " / " + pr.a));
      return td;
    })));
    if (PLAYERS.some(function (pid) { var q = r.p[pid]; return q.ak !== q.k || q.ad !== q.d; })) {
      tb2.appendChild(sheetRow(null, "Analysis kills / deaths", "pr_ak", PLAYERS.map(function (pid) {
        var pr = r.p[pid];
        var td = el("td", "val");
        td.appendChild(el("span", "v", pr.ak + " / " + pr.ad));
        return td;
      })));
    }
    tb2.appendChild(sheetRow(null, "Damage", "pr_dmg", PLAYERS.map(function (pid) {
      return valueCell(r.p[pid].dmg, { spec: { dec: 0, group: true }, scale: P95.dmg });
    })));
    tb2.appendChild(sheetRow(null, "Loadout value", "pr_lv", PLAYERS.map(function (pid) {
      return valueCell(r.p[pid].lv, { spec: { dec: 0, group: true }, scale: P95.lv });
    })));
    tb2.appendChild(sheetRow(null, "Credits left", "pr_cr", PLAYERS.map(function (pid) {
      return valueCell(r.p[pid].cr, { spec: { dec: 0, group: true }, scale: P95.cr });
    })));
    tb2.appendChild(sheetRow(null, "Weapon", "pr_wp", PLAYERS.map(function (pid) {
      var pr = r.p[pid];
      var td = el("td", "val");
      td.appendChild(el("span", "v", pr.wp ? (pr.wp + (pr.ar ? " · " + pr.ar.replace(" Armor", "") : "")) : "—"));
      return td;
    })));
    table.appendChild(tb2);

    /* ---- band 3: events ---- */
    var EVENTS = [
      ["ok", "Opening kill", "pr_ok"], ["od", "Opening death", "pr_od"],
      ["oa", "Opening assist", "pr_oa"], ["tk", "Trade kill", "pr_tk"],
      ["pt", "Plant", "pr_pt"], ["dz", "Defuse", "pr_dz"],
      ["mk", "Multikill", "pr_mk"], ["afk", "Flagged inactive", "pr_afk"],
    ].filter(function (e) {
      return PLAYERS.some(function (pid) { return r.p[pid][e[0]]; });
    });
    var hasClutch = PLAYERS.some(function (pid) { return r.p[pid].cl; });
    var tb3 = el("tbody");
    tb3.appendChild(band("Events", EVENTS.length || hasClutch ? "" : "none this round"));
    EVENTS.forEach(function (e) {
      tb3.appendChild(sheetRow(null, e[1], e[2], PLAYERS.map(function (pid) {
        var v = r.p[pid][e[0]];
        var td = el("td", "val");
        var bool = r.p[pid][e[0]] === true || D.meta.absent_means_false.indexOf(e[0]) >= 0;
        var txt = v === true ? "yes" : v ? String(v) : (bool ? "no" : "0");
        td.appendChild(el("span", "v " + (v ? "" : "dim"), txt));
        return td;
      })));
    });
    if (hasClutch) {
      tb3.appendChild(sheetRow(null, "Clutch", "cda10", PLAYERS.map(function (pid) {
        var c = r.p[pid].cl;
        var td = el("td", "val");
        td.appendChild(el("span", "v " + (c ? "" : "dim"),
          c ? c.lb + " · " + (c.cv ? "converted" : "lost") : "—"));
        return td;
      })));
    }
    table.appendChild(tb3);
    return { table: table, measured: measured };
  }

  function band(title, axis) {
    var tr = el("tr", "band");
    var th = el("th");
    th.colSpan = 3;
    th.scope = "rowgroup";
    th.appendChild(el("span", null, title));
    if (axis) th.appendChild(el("span", "axis", axis));
    return tr.appendChild(th), tr;
  }

  /* dx[].t covers every player-round containing a death, so the timestamp costs
     nothing and supplies the one piece of narrative the sheet otherwise lacks.
     Both players' times go on the shared row label — a per-player death clock
     column would be a sixth thing to read for a fact the round already implies. */
  function deathLabel(r) {
    var at = PLAYERS.map(function (pid) {
      var dx = r.p[pid].dx;
      return dx && dx.length ? SHORT[pid].slice(0, 1) + " " + (dx[0].t / 1000).toFixed(1) + "s" : null;
    }).filter(Boolean);
    return at.length ? "Death debit · died " + at.join(", ") : "Death debit";
  }

  /* The sheet renders BELOW the ledger, not as a nested <tr>. A table inside a
     colspan cell contributes its own min-content width to the parent's column
     sizing, which dragged the 1142px ledger out to 2250px and pushed both value
     columns off-screen. Taking it out of the table deletes that interaction
     rather than fighting it, and it stops a 15-row panel shoving the rest of
     the ledger down every time a round is opened. */
  function toggleRound(m, r, tr, tbody) {
    var host = document.querySelector("[data-round-sheet]");
    var same = host.getAttribute("data-open") === String(r.i);
    tbody.querySelectorAll("tr.is-open").forEach(function (x) {
      x.classList.remove("is-open");
      x.setAttribute("aria-expanded", "false");
    });
    host.innerHTML = "";
    if (same) { host.removeAttribute("data-open"); openRound = null; return; }

    host.setAttribute("data-open", String(r.i));
    openRound = r.i;
    tr.classList.add("is-open");
    tr.setAttribute("aria-expanded", "true");

    var td = host;
    var meta = el("p", "sheet-meta");
    meta.textContent = SIDE[r.sd] + " · " + (r.w ? "won" : "lost") + " " +
      scoreAfter(r).join("–") + " · " + code("ec", r.ec).toLowerCase() +
      (r.pi ? " · pistol round" : "") + (r.ot ? " · overtime" : "") +
      (isDegraded(r) ? " · scored four-versus-five" : "");
    td.appendChild(meta);

    td.appendChild(buildSheet(m, r).table);
    host.scrollIntoView({ block: "nearest", behavior: prefersReduced() ? "auto" : "smooth" });
  }

  function prefersReduced() {
    return matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /* ---------- the strip ---------- */
  /* Two stacked panels, one per player, each with its OWN zero line. The first
     draft mirrored them around a single shared axis, which meant a negative bar
     pointed into the other player's half and the two colours overlapped — the
     picture said "SN0RLAX did something here" when SN0RLAX had done nothing.
     Panel position carries the player; direction from that panel's own zero
     carries the sign. Neither channel has to do two jobs. */
  function renderStrip(m) {
    var fig = document.querySelector("[data-strip]");
    if (!fig) return;
    while (fig.childNodes.length > 1) fig.removeChild(fig.lastChild);

    var n = m.rs.length;
    var w = Math.max(320, Math.round(fig.clientWidth || fig.parentNode.clientWidth || 1000));
    var h = 210, padT = 10, padB = 20, gutter = w < 640 ? 42 : 54;
    var panelH = (h - padT - padB - 10) / 2;
    fig.setAttribute("viewBox", "0 0 " + w + " " + h);
    var plotW = w - gutter;
    var colW = plotW / n;

    var maxAbs = 0;
    m.rs.forEach(function (r) {
      PLAYERS.forEach(function (pid) {
        var pr = r.p[pid];
        if (pr && typeof pr.rw === "number") maxAbs = Math.max(maxAbs, Math.abs(pr.rw));
      });
    });
    maxAbs = maxAbs || 1;

    var axisY = { m: padT + panelH / 2, s: padT + panelH + 10 + panelH / 2 };
    var scale = function (v) { return (Math.abs(v) / maxAbs) * (panelH / 2 - 3); };

    fig.appendChild(hatchDefs("notmeasured"));

    var g = svgEl("g", {});

    PLAYERS.forEach(function (pid) {
      var lab = svgEl("text", { class: "strip-tick", x: gutter - 8, y: axisY[pid] + 3.5, "text-anchor": "end" });
      lab.textContent = SHORT[pid] === "MartinLutherKing" ? "Martin" : "SN0RLAX";
      lab.setAttribute("fill", "var(--" + (pid === "m" ? "martin" : "snorlax") + ")");
      g.appendChild(lab);
    });

    m.rs.forEach(function (r, i) {
      var cx = gutter + i * colW;
      var col = svgEl("g", { class: "strip-col" });
      col.appendChild(svgEl("rect", { class: "strip-hit", x: cx, y: padT, width: colW, height: h - padT - padB }));

      if (!r.el) {
        col.appendChild(svgEl("rect", { x: cx + colW * 0.14, y: padT,
          width: colW * 0.72, height: h - padT - padB, fill: "url(#notmeasured)", opacity: .8 }));
      }
      /* A degraded round is drawn normally — full opacity, correct sign colour,
         nothing greyed — and marked by a 2px tick under the column baseline.
         The bar is the value; the tick is provenance. */
      if (isDegraded(r)) {
        PLAYERS.forEach(function (pid) {
          col.appendChild(svgEl("rect", { class: "strip-degraded",
            x: cx + colW * 0.2, y: axisY[pid] + 2, width: Math.max(1.5, colW * 0.6), height: 2 }));
        });
      }
      PLAYERS.forEach(function (pid) {
        var pr = r.p[pid];
        if (!r.el || !pr || typeof pr.rw !== "number") return;
        var len = scale(pr.rw);
        var y0 = axisY[pid];
        var y1 = y0 - (pr.rw >= 0 ? len : -len);
        col.appendChild(svgEl("rect", {
          class: "strip-bar " + pid + (pr.rw >= 0 ? "" : " out"),
          x: cx + colW * 0.2,
          y: Math.min(y0, y1),
          width: Math.max(1.5, colW * 0.6),
          height: Math.max(1, Math.abs(y1 - y0)),
        }));
      });

      col.addEventListener("click", function () {
        var tr = document.querySelector('tr[data-round="' + r.i + '"]');
        if (tr) { toggleRound(m, r, tr, tr.parentNode); tr.focus(); }
      });
      var t = svgEl("title", {});
      t.textContent = "Round " + r.n + " · " + (r.w ? "won" : "lost") +
        (r.el
          ? " · Martin " + signed(r.p.m.rw, 3) + " · SN0RLAX " + signed(r.p.s.rw, 3)
          : " · not measured (" + r.xr + ")");
      col.appendChild(t);
      g.appendChild(col);
    });

    PLAYERS.forEach(function (pid) {
      g.appendChild(svgEl("line", { class: "strip-axis", x1: gutter, x2: w, y1: axisY[pid], y2: axisY[pid] }));
    });

    m.rs.forEach(function (r, i) {
      if (r.n % 5 !== 0 && r.n !== 1) return;
      var t = svgEl("text", { class: "strip-tick", x: gutter + i * colW + colW / 2, y: h - 5, "text-anchor": "middle" });
      t.textContent = r.n;
      g.appendChild(t);
    });
    fig.appendChild(g);
  }

  /* ============================ ROUTING ============================ */

  function route() {
    var hash = location.hash || "#/";
    var mm = hash.match(/^#\/m\/(.+)$/);
    if (mm) {
      var m = matchById(mm[1]);
      if (m) {
        vCohort.hidden = true;
        vMatch.hidden = false;
        renderMatch(m);
        document.title = m.map + " " + m.det + " · RWPA";
        window.scrollTo(0, 0);
        return;
      }
    }
    vMatch.hidden = true;
    vCohort.hidden = false;
    currentMatch = null;
    document.title = "RWPA · MartinLutherKing & SN0RLAX";
    renderWalk();
    renderDisposition();
  }

  document.querySelector("[data-back]").addEventListener("click", function () { location.hash = "#/"; });
  window.addEventListener("hashchange", route);

  /* both figures size their viewBox to the container, so a width change means a
     re-render rather than a rescale */
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (currentMatch) renderStrip(currentMatch);
      else { renderWalk(); renderDisposition(); renderProvenance(); }
    }, 120);
  });

  /* keyboard: j/k step through matches from anywhere */
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    if (e.key === "Escape" && currentMatch) { location.hash = "#/"; return; }
    if (!currentMatch) return;
    var i = D.matches.indexOf(currentMatch);
    if (e.key === "j" && i < D.matches.length - 1) location.hash = "#/m/" + D.matches[i + 1].id;
    if (e.key === "k" && i > 0) location.hash = "#/m/" + D.matches[i - 1].id;
  });

  /* ---------- boot ---------- */
  renderHeader();
  renderVerdict();
  renderMatchTable();
  renderLayers();
  renderProvenance();
  route();
})();
