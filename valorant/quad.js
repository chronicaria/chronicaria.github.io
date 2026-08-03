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
  var WINDOW = 50;

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function fmt(x, d) { return (x >= 0 ? "+" : "") + Number(x).toFixed(d === undefined ? 2 : d); }
  function sv(tag, a) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in a) if (a[k] !== null && a[k] !== undefined) n.setAttribute(k, a[k]);
    return n;
  }

  /* global round timeline */
  var TL = [];
  D.matches.forEach(function (m) { m.rounds.forEach(function (r) { TL.push({ m: m, r: r }); }); });

  /* per player: the rounds they played, as {i, v} against the global index */
  var PTS = {};
  ids.forEach(function (pid) {
    PTS[pid] = [];
    TL.forEach(function (t, i) {
      var e = t.r.p[pid];
      if (e) PTS[pid].push({ i: i, v: e.t });
    });
  });

  /* trailing mean over the player's OWN last k rounds, positioned at the global index of the
     round that closes the window. Only emitted once the window is full. */
  function rolling(pid, k) {
    var p = PTS[pid], out = [], sum = 0;
    for (var j = 0; j < p.length; j++) {
      sum += p[j].v;
      if (j >= k) sum -= p[j - k].v;
      if (j >= k - 1) out.push({ i: p[j].i, y: 100 * sum / k });
    }
    return out;
  }

  function drawChart() {
    var host = document.getElementById("quad-chart");
    if (!host) return;
    host.textContent = "";

    var W = 940, H = 400, ML = 54, MR = 14, MT = 16, MB = 42;
    var n = TL.length;

    var lines = {};
    ids.forEach(function (p) { lines[p] = rolling(p, WINDOW); });

    /* Scale to the LINES, not the scatter. Single-round RWPA ranges past +/-70 per 100 while
       every trailing mean sits inside a few points of zero, so scaling to the dots squeezes the
       lines into an unreadable band -- the figure would spend its whole height on outliers.
       The frame is the line range with generous headroom; dots outside it are clipped, and the
       count of clipped rounds is printed so nothing is silently dropped. */
    var lmin = Infinity, lmax = -Infinity;
    ids.forEach(function (p) {
      lines[p].forEach(function (q) { if (q.y < lmin) lmin = q.y; if (q.y > lmax) lmax = q.y; });
    });
    if (!isFinite(lmin)) { lmin = -1; lmax = 1; }
    /* Frame the trailing means and nothing else. Single rounds reach past +/-70 per 100; letting
       them set the scale flattens every line into one band and hides the differences the chart
       exists to show. Dots outside are clipped and counted on the axis. */
    var span = Math.max(lmax - lmin, 0.5), padY = span * 0.14;
    var lo = lmin - padY, hi = lmax + padY;
    var clipped = 0;
    ids.forEach(function (p) {
      PTS[p].forEach(function (q) { var v = 100 * q.v; if (v < lo || v > hi) clipped++; });
    });

    var x = function (i) { return ML + (n <= 1 ? 0 : i * (W - ML - MR) / (n - 1)); };
    var y = function (v) { return MT + (hi - v) * (H - MT - MB) / (hi - lo || 1); };

    var svg = sv("svg", { viewBox: "0 0 " + W + " " + H, class: "quad-chart", role: "img",
      "aria-label": "Each round's win probability added for four players across " + n +
        " rounds, with a " + WINDOW + "-round trailing mean per player." });
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
    D.matches.forEach(function (m, mi) {
      acc += m.rounds.length;
      if (mi < D.matches.length - 1 && acc < n)
        svg.appendChild(sv("line", { class: "matchsep", x1: x(acc), x2: x(acc), y1: MT, y2: H - MB }));
    });

    [0, Math.floor((n - 1) / 3), Math.floor(2 * (n - 1) / 3), n - 1].forEach(function (i) {
      var t = sv("text", { class: "tick", x: x(i), y: H - MB + 16, "text-anchor": "middle" });
      t.textContent = String(i + 1);
      svg.appendChild(t);
    });
    var xl = sv("text", { class: "tick", x: (ML + W - MR) / 2, y: H - 6, "text-anchor": "middle" });
    xl.textContent = "round, in play order across the act · dots are single rounds, lines are a " +
      WINDOW + "-round trailing mean" +
      (clipped ? " · " + clipped + " rounds fall outside this frame" : "");
    svg.appendChild(xl);

    var band = sv("rect", { class: "sel-band", x: -99, y: MT, width: 0, height: H - MT - MB });
    svg.appendChild(band);

    // scatter first, so the means read on top
    ids.forEach(function (pid) {
      var col = css(COLOR[pid]);
      var g = sv("g", { class: "scatter", "clip-path": "url(#plotclip)" });
      PTS[pid].forEach(function (q) {
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
        if (prevI !== null && q.i !== prevI + 1) flush();
        seg.push(q); prevI = q.i;
      });
      flush();
    });

    var start = 0;
    D.matches.forEach(function (m) {
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
      i = Math.max(0, Math.min(n - 1, i));
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
        '<div class="tip-cols"><span></span><span></span><span>mean</span><span>round</span></div>' + rows;
      panel.hidden = false;
      /* Clamp inside the chart rather than flipping at a fixed fraction: a fixed flip still
         overflows whenever the panel is wider than the remaining space. */
      panel.style.left = "0px";
      panel.style.transform = "none";
      var hb = host.getBoundingClientRect(), pb = panel.getBoundingClientRect();
      var want = (i / Math.max(n - 1, 1)) * hb.width + 14;
      panel.style.left = Math.max(0, Math.min(want, hb.width - pb.width)) + "px";
    }
    var surface = sv("rect", { class: "hover-surface", x: ML, y: MT,
                               width: W - ML - MR, height: H - MT - MB });
    surface.addEventListener("mousemove", function (e) {
      var r = svg.getBoundingClientRect();
      var vx = ((e.clientX - r.left) / r.width) * W;
      hoverAt(Math.round((vx - ML) / ((W - ML - MR) / Math.max(n - 1, 1))));
    });
    surface.addEventListener("mouseleave", hoverOff);
    svg.appendChild(surface);

    host.appendChild(svg);
    host._x = x; host._band = band;
  }

  function drawWindowControl() {
    var host = document.getElementById("quad-window");
    if (!host) return;
    host.textContent = "";
    [25, 50, 100].forEach(function (k) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "winbtn" + (k === WINDOW ? " on" : "");
      b.textContent = k + " rounds";
      b.setAttribute("aria-pressed", String(k === WINDOW));
      b.addEventListener("click", function () { WINDOW = k; drawWindowControl(); drawChart(); });
      host.appendChild(b);
    });
    var se = { 25: 4.21, 50: 2.98, 100: 2.11 }[WINDOW];
    var note = document.createElement("span");
    note.className = "winnote";
    note.textContent = "±" + se.toFixed(1) + " per 100 at this window";
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
    drawLegend(); drawCards(); drawWindowControl(); drawChart(); drawMatchList();
    addEventListener("hashchange", route);
    route();
    var t = document.querySelector(".theme-toggle");
    if (t) t.addEventListener("click", function () { setTimeout(function () { drawCards(); drawChart(); }, 0); });
    addEventListener("resize", function () { clearTimeout(boot._r); boot._r = setTimeout(drawChart, 150); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
