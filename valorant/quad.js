/* Four-player E11A4 view: a rate walk over rounds, and a round-by-round view per match.
 *
 * Two rules this file exists to enforce.
 *
 * 1. DISJOINT LINES. A player's series is drawn only over rounds they actually played. The
 *    running totals carry across an absence -- they are a record of what that player did -- but
 *    no stroke spans it. A connecting slope there would draw performance in rounds nobody played.
 *
 * 2. RATE, NOT SUM, AND NOT BELOW THE FLOOR. The y value is cumulative RWPA per 100 rounds, so
 *    a player who simply played more does not drift upward for that reason alone. A rate over
 *    very few rounds is noise, so nothing is drawn until a player passes the release's own
 *    exposure floor (meta.gate.min_elig_rounds_for_rate). Trzzcko's 93 rounds are exactly why:
 *    at five matches a rate can look enormous and mean very little.
 *
 * Nothing here ranks players.
 */
(function () {
  "use strict";
  var D = window.QUAD_DATA;
  if (!D) return;

  var COLOR = { martin: "--martin", snorlax: "--snorlax", themarias: "--themarias", trzzcko: "--trzzcko" };
  var SHORT = { martin: "Martin", snorlax: "SN0RLAX", themarias: "TheMarias", trzzcko: "Trzzcko" };
  var FLOOR = D.min_rounds_for_rate || 20;
  var ids = D.players.map(function (p) { return p.id; });

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function fmt(x, d) { return (x >= 0 ? "+" : "") + Number(x).toFixed(d === undefined ? 2 : d); }
  function svgEl(tag, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    return n;
  }

  /* Flatten to a global round timeline: every round of every match, in play order. */
  var TL = [];
  D.matches.forEach(function (m) {
    m.rounds.forEach(function (r) { TL.push({ m: m, r: r }); });
  });

  /* Per player: cumulative rwpa and cumulative rounds, walked over the global timeline.
     `on` marks rounds the player was actually in; `y` is per-100 once past the floor. */
  var SER = {};
  ids.forEach(function (pid) {
    var sum = 0, cnt = 0;
    SER[pid] = TL.map(function (t) {
      var v = t.r.p[pid];
      var on = v !== undefined;
      if (on) { sum += v; cnt += 1; }
      return { on: on, sum: sum, cnt: cnt, y: cnt >= FLOOR ? 100 * sum / cnt : null };
    });
  });

  function drawChart() {
    var host = document.getElementById("quad-chart");
    if (!host) return;
    host.textContent = "";

    var W = 940, H = 400, ML = 54, MR = 14, MT = 16, MB = 40;
    var n = TL.length;
    var lo = 0, hi = 0;
    ids.forEach(function (p) {
      SER[p].forEach(function (q) {
        if (q.y === null) return;
        if (q.y < lo) lo = q.y; if (q.y > hi) hi = q.y;
      });
    });
    var pad = Math.max(0.5, (hi - lo) * 0.12);
    lo -= pad; hi += pad;

    var x = function (i) { return ML + (n <= 1 ? 0 : i * (W - ML - MR) / (n - 1)); };
    var y = function (v) { return MT + (hi - v) * (H - MT - MB) / (hi - lo || 1); };

    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "quad-chart", role: "img",
      "aria-label": "Cumulative round win probability added per 100 rounds for four players across " +
        n + " rounds this act. Each line is drawn only over rounds that player played, and starts " +
        "once they pass " + FLOOR + " rounds of exposure." });

    var steps = 5;
    for (var g = 0; g <= steps; g++) {
      var vv = lo + (hi - lo) * g / steps;
      svg.appendChild(svgEl("line", { class: Math.abs(vv) < 1e-9 ? "zero" : "gridline",
                                      x1: ML, x2: W - MR, y1: y(vv), y2: y(vv) }));
      var t = svgEl("text", { class: "tick", x: ML - 8, y: y(vv) + 4, "text-anchor": "end" });
      t.textContent = vv.toFixed(1);
      svg.appendChild(t);
    }
    // true zero line, if inside range
    if (lo < 0 && hi > 0) svg.appendChild(svgEl("line", { class: "zero", x1: ML, x2: W - MR, y1: y(0), y2: y(0) }));
    svg.appendChild(svgEl("line", { class: "axis", x1: ML, x2: W - MR, y1: H - MB, y2: H - MB }));

    // match boundaries, faint, so the round axis still reads as matches
    var acc = 0;
    D.matches.forEach(function (m, mi) {
      acc += m.rounds.length;
      if (mi < D.matches.length - 1 && acc < n) {
        svg.appendChild(svgEl("line", { class: "matchsep", x1: x(acc), x2: x(acc), y1: MT, y2: H - MB }));
      }
    });

    [0, Math.floor((n - 1) / 3), Math.floor(2 * (n - 1) / 3), n - 1].forEach(function (i) {
      var t = svgEl("text", { class: "tick", x: x(i), y: H - MB + 16, "text-anchor": "middle" });
      t.textContent = String(i + 1);
      svg.appendChild(t);
    });
    var xl = svgEl("text", { class: "tick", x: (ML + W - MR) / 2, y: H - 6, "text-anchor": "middle" });
    xl.textContent = "round, in play order across the act (faint rules mark match boundaries)";
    svg.appendChild(xl);

    var band = svgEl("rect", { class: "sel-band", x: -99, y: MT, width: 0, height: H - MT - MB });
    svg.appendChild(band);

    ids.forEach(function (pid) {
      var col = css(COLOR[pid]), pts = SER[pid], seg = [];
      var flush = function () {
        if (seg.length === 1) {
          svg.appendChild(svgEl("circle", { class: "dot", cx: x(seg[0].i), cy: y(seg[0].y), r: 2.6, fill: col }));
        } else if (seg.length > 1) {
          svg.appendChild(svgEl("path", { class: "seg", stroke: col,
            d: seg.map(function (q, j) { return (j ? "L" : "M") + x(q.i) + " " + y(q.y); }).join(" ") }));
        }
        seg = [];
      };
      pts.forEach(function (q, i) {
        if (q.on && q.y !== null) seg.push({ i: i, y: q.y }); else flush();
      });
      flush();
    });

    // one hit target per match, spanning its rounds
    var start = 0;
    D.matches.forEach(function (m) {
      var w = Math.max(x(start + m.rounds.length) - x(start), 2);
      var r = svgEl("rect", { class: "hit", x: x(start), y: MT, width: w, height: H - MT - MB,
        tabindex: "0", role: "button",
        "aria-label": "Match " + (m.i + 1) + ", " + m.map + ", " + m.rounds.length + " rounds" });
      r.addEventListener("click", function () { location.hash = "#/m/" + m.i; });
      r.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); location.hash = "#/m/" + m.i; }
      });
      svg.appendChild(r);
      start += m.rounds.length;
    });

    host.appendChild(svg);
    host._x = x; host._band = band;
  }

  function highlightMatch(mi) {
    var host = document.getElementById("quad-chart");
    if (!host || !host._band) return;
    var start = 0;
    for (var k = 0; k < mi; k++) start += D.matches[k].rounds.length;
    var w = host._x(start + D.matches[mi].rounds.length) - host._x(start);
    host._band.setAttribute("x", host._x(start));
    host._band.setAttribute("width", Math.max(w, 2));
  }

  function drawLegend() {
    var ul = document.getElementById("quad-legend");
    if (!ul) return;
    ul.textContent = "";
    D.players.forEach(function (p) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="swatch" style="background:var(' + COLOR[p.id] + ')"></span>' +
        '<span class="who">' + SHORT[p.id] + "</span>" +
        '<span class="exposure">' + p.matches + " matches · " + p.rounds + " rounds</span>";
      ul.appendChild(li);
    });
  }

  function drawCards() {
    var host = document.getElementById("quad-cards");
    if (!host) return;
    host.textContent = "";
    D.players.forEach(function (p) {
      var below = p.rounds < FLOOR;
      var d = document.createElement("div");
      d.className = "quad-card";
      d.innerHTML =
        '<div class="who"><span class="swatch" style="background:var(' + COLOR[p.id] + ')"></span>' +
        SHORT[p.id] + "</div>" +
        '<div class="big ' + (p.r100 >= 0 ? "pos" : "neg") + '">' +
        (below ? "—" : fmt(p.r100)) + "</div>" +
        '<div class="sub">per 100 rounds · ' + p.matches + " matches · " + p.rounds + " rounds</div>" +
        (below ? '<div class="sub">below the ' + FLOOR + "-round floor</div>" : "");
      host.appendChild(d);
    });
  }

  function drawMatchList() {
    var tb = document.querySelector("#quad-matches tbody");
    if (!tb) return;
    tb.textContent = "";
    D.matches.forEach(function (m) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-i", m.i);
      var cells = ['<td class="num">' + (m.i + 1) + "</td>",
                   "<td>" + (m.map || "—") + '</td><td class="num">' + m.rounds.length + "</td>"];
      ids.forEach(function (pid) {
        var tot = 0, cnt = 0;
        m.rounds.forEach(function (r) { if (r.p[pid] !== undefined) { tot += r.p[pid]; cnt++; } });
        cells.push(cnt
          ? '<td class="num ' + (tot >= 0 ? "pos" : "neg") + '">' + fmt(tot) + "</td>"
          : '<td class="num absent">—</td>');
      });
      tr.innerHTML = cells.join("");
      tr.addEventListener("click", function () { location.hash = "#/m/" + m.i; });
      tb.appendChild(tr);
    });
  }

  /* ---- match subpage: round-by-round ---- */
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

    var totals = {}, counts = {};
    present.forEach(function (p) { totals[p] = 0; counts[p] = 0; });
    var body = m.rounds.map(function (r) {
      var cells = present.map(function (p) {
        var val = r.p[p];
        if (val === undefined) return '<td class="num absent">—</td>';
        totals[p] += val; counts[p] += 1;
        return '<td class="num ' + (val >= 0 ? "pos" : "neg") + '">' + fmt(val, 3) + "</td>";
      }).join("");
      var tag = (r.pi ? ' <span class="rtag">pistol</span>' : "") + (r.ot ? ' <span class="rtag">OT</span>' : "");
      return "<tr><td class='num'>" + (r.r + 1) + "</td><td>" + (r.res || "—") + tag +
             "</td><td>" + (r.win || "—") + "</td>" + cells + "</tr>";
    }).join("");

    var foot = present.map(function (p) {
      return '<td class="num ' + (totals[p] >= 0 ? "pos" : "neg") + '"><strong>' + fmt(totals[p]) + "</strong></td>";
    }).join("");

    var roster = present.map(function (p) {
      return "<li><span class='swatch' style='background:var(" + COLOR[p] + ")'></span>" +
             SHORT[p] + " · " + (m.agent[p] || "—") + " · " + (m.won[p] ? "won" : "lost") + "</li>";
    }).join("");

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
      '<div class="table-wrap"><table class="round-table"><thead><tr>' +
      "<th class='num'>Rd</th><th>Ending</th><th>Won by</th>" + head + "</tr></thead>" +
      "<tbody>" + body + "</tbody>" +
      "<tfoot><tr><td colspan='3'>Match total</td>" + foot + "</tr></tfoot>" +
      "</table></div>";
    window.scrollTo(0, 0);
  }

  function showCohort() {
    document.getElementById("view-match").hidden = true;
    document.getElementById("view-cohort").hidden = false;
  }

  function route() {
    var m = /^#\/m\/(\d+)$/.exec(location.hash || "");
    if (m) { showMatch(Number(m[1])); highlightMatch(Number(m[1])); }
    else showCohort();
  }

  function boot() {
    drawLegend(); drawCards(); drawChart(); drawMatchList();
    addEventListener("hashchange", route);
    route();
    var t = document.querySelector(".theme-toggle");
    if (t) t.addEventListener("click", function () { setTimeout(drawChart, 0); });
    addEventListener("resize", function () { clearTimeout(boot._r); boot._r = setTimeout(drawChart, 150); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
