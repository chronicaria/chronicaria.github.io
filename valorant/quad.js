/* Four-player E11A4 view.
 *
 * The one rule this file exists to enforce: a player's cumulative line is drawn as DISJOINT
 * segments. When a player misses matches, the cumulative total still carries across the gap --
 * it is a running sum of what they did -- but no stroke is drawn over the matches they sat out.
 * A connecting slope there would read as performance during games they never played.
 *
 * Nothing here ranks players. Season totals cover different matches, different opponents and
 * exposure differing by an order of magnitude; per-match values share a match and are the only
 * figures on this page that support a comparison.
 */
(function () {
  "use strict";
  var D = window.QUAD_DATA;
  if (!D) return;

  var COLOR = { martin: "--martin", snorlax: "--snorlax", themarias: "--themarias", trzzcko: "--trzzcko" };
  var SHORT = { martin: "Martin", snorlax: "SN0RLAX", themarias: "TheMarias", trzzcko: "Trzzcko" };
  var ids = D.players.map(function (p) { return p.id; });

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function fmt(x, d) { return (x >= 0 ? "+" : "") + x.toFixed(d === undefined ? 2 : d); }
  function el(tag, attrs, kids) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    (kids || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }

  /* Cumulative series per player, carrying the total across absences but recording, for each
     match index, whether the player was actually present. Segments are built from runs of
     present indices so the gaps are never stroked. */
  function series(pid) {
    var run = 0, pts = [];
    D.matches.forEach(function (m, i) {
      var v = m.p[pid];
      if (v) { run += v.rwpa; pts.push({ i: i, y: run, played: true, m: m, v: v }); }
      else { pts.push({ i: i, y: run, played: false, m: m }); }
    });
    return pts;
  }

  var SER = {};
  ids.forEach(function (p) { SER[p] = series(p); });

  function render() {
    var host = document.getElementById("quad-chart");
    if (!host) return;
    host.textContent = "";

    var W = 940, H = 380, ML = 52, MR = 16, MT = 18, MB = 34;
    var n = D.matches.length;
    var lo = 0, hi = 0;
    ids.forEach(function (p) { SER[p].forEach(function (q) { if (q.y < lo) lo = q.y; if (q.y > hi) hi = q.y; }); });
    var pad = Math.max(1, (hi - lo) * 0.12);
    lo -= pad; hi += pad;

    var x = function (i) { return ML + (n <= 1 ? 0 : i * (W - ML - MR) / (n - 1)); };
    var y = function (v) { return MT + (hi - v) * (H - MT - MB) / (hi - lo || 1); };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "quad-chart",
                          role: "img", "aria-label":
      "Cumulative round win probability added for four players across " + n +
      " matches this act. Each line breaks over matches that player did not play." });

    // gridlines + y ticks
    var steps = 5;
    for (var g = 0; g <= steps; g++) {
      var vv = lo + (hi - lo) * g / steps;
      svg.appendChild(el("line", { class: vv === 0 ? "zero" : "gridline", x1: ML, x2: W - MR, y1: y(vv), y2: y(vv) }));
      var t = el("text", { class: "tick", x: ML - 8, y: y(vv) + 4, "text-anchor": "end" });
      t.textContent = vv.toFixed(1);
      svg.appendChild(t);
    }
    svg.appendChild(el("line", { class: "axis", x1: ML, x2: W - MR, y1: H - MB, y2: H - MB }));

    // x ticks: first, last and a few in between, labelled by match number
    [0, Math.floor((n - 1) / 3), Math.floor(2 * (n - 1) / 3), n - 1].forEach(function (i) {
      var t = el("text", { class: "tick", x: x(i), y: H - MB + 16, "text-anchor": "middle" });
      t.textContent = String(i + 1);
      svg.appendChild(t);
    });
    var xl = el("text", { class: "tick", x: (ML + W - MR) / 2, y: H - 4, "text-anchor": "middle" });
    xl.textContent = "match, in order played this act";
    svg.appendChild(xl);

    // selection band
    var band = el("rect", { class: "sel-band", x: -99, y: MT, width: 0, height: H - MT - MB });
    svg.appendChild(band);

    // one path per contiguous run of played matches -- this is the disjoint-line rule
    ids.forEach(function (pid) {
      var col = css(COLOR[pid]);
      var pts = SER[pid], seg = [];
      var flush = function () {
        if (seg.length === 1) {
          svg.appendChild(el("circle", { class: "dot", cx: x(seg[0].i), cy: y(seg[0].y), r: 3.2, fill: col }));
        } else if (seg.length > 1) {
          svg.appendChild(el("path", { class: "seg", stroke: col,
            d: seg.map(function (q, j) { return (j ? "L" : "M") + x(q.i) + " " + y(q.y); }).join(" ") }));
        }
        seg = [];
      };
      pts.forEach(function (q) { if (q.played) seg.push(q); else flush(); });
      flush();
      pts.forEach(function (q) {
        if (q.played) svg.appendChild(el("circle", { class: "dot", cx: x(q.i), cy: y(q.y), r: 2.6, fill: col }));
      });
    });

    // hit targets
    D.matches.forEach(function (m, i) {
      var w = (W - ML - MR) / Math.max(n - 1, 1);
      var r = el("rect", { class: "hit", x: x(i) - w / 2, y: MT, width: w, height: H - MT - MB,
                           tabindex: "0", role: "button",
                           "aria-label": "Match " + (i + 1) + ", " + m.map + ", " +
                                         m.who.map(function (k) { return SHORT[k]; }).join(" and ") });
      r.addEventListener("click", function () { select(i); });
      r.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(i); } });
      svg.appendChild(r);
    });

    host.appendChild(svg);
    host._band = band; host._x = x; host._W = W; host._ML = ML; host._MR = MR; host._n = n;
  }

  function renderLegend() {
    var ul = document.getElementById("quad-legend");
    if (!ul) return;
    ul.textContent = "";
    D.players.forEach(function (p) {
      var li = document.createElement("li");
      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = "var(" + COLOR[p.id] + ")";
      var who = document.createElement("span");
      who.className = "who"; who.textContent = SHORT[p.id];
      var ex = document.createElement("span");
      ex.className = "exposure";
      ex.textContent = p.matches + " of " + D.n_matches + " · " + p.rounds + " rounds";
      li.appendChild(sw); li.appendChild(who); li.appendChild(ex);
      ul.appendChild(li);
    });
  }

  function renderCards() {
    var host = document.getElementById("quad-cards");
    if (!host) return;
    host.textContent = "";
    D.players.forEach(function (p) {
      var d = document.createElement("div");
      d.className = "quad-card";
      d.innerHTML =
        '<div class="who"><span class="swatch" style="background:var(' + COLOR[p.id] + ')"></span>' +
        SHORT[p.id] + '</div>' +
        '<div class="big ' + (p.rwpa >= 0 ? "pos" : "neg") + '">' + fmt(p.rwpa) + '</div>' +
        '<div class="sub">' + fmt(p.r100 || 0) + " per 100 · " + p.matches + " matches · " +
        p.rounds + " rounds</div>";
      host.appendChild(d);
    });
  }

  function renderTable() {
    var tb = document.querySelector("#quad-matches tbody");
    if (!tb) return;
    tb.textContent = "";
    D.matches.forEach(function (m, i) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-i", i);
      var cells = ['<td class="num">' + (i + 1) + "</td>", "<td>" + (m.map || "—") + "</td>"];
      ids.forEach(function (pid) {
        var v = m.p[pid];
        cells.push(v
          ? '<td class="num ' + (v.rwpa >= 0 ? "pos" : "neg") + '">' + fmt(v.rwpa) + "</td>"
          : '<td class="num absent">—</td>');
      });
      tr.innerHTML = cells.join("");
      tr.addEventListener("click", function () { select(i); });
      tb.appendChild(tr);
    });
  }

  function select(i) {
    var m = D.matches[i];
    var host = document.getElementById("quad-chart");
    if (host && host._band) {
      var w = (host._W - host._ML - host._MR) / Math.max(host._n - 1, 1);
      host._band.setAttribute("x", host._x(i) - w / 2);
      host._band.setAttribute("width", w);
    }
    document.querySelectorAll("#quad-matches tbody tr").forEach(function (tr) {
      tr.setAttribute("aria-selected", String(Number(tr.getAttribute("data-i")) === i));
    });
    var sheet = document.getElementById("quad-sheet");
    if (!sheet) return;
    var present = m.who;
    var rows = present.map(function (pid) {
      var v = m.p[pid];
      return "<tr><td><span class='swatch' style='display:inline-block;width:.7rem;height:.7rem;" +
        "border-radius:2px;background:var(" + COLOR[pid] + ");margin-right:.45rem'></span>" +
        SHORT[pid] + "</td><td>" + (v.agent || "—") + "</td>" +
        '<td class="num">' + v.rounds + "</td>" +
        '<td class="num ' + (v.rwpa >= 0 ? "pos" : "neg") + '">' + fmt(v.rwpa) + "</td>" +
        '<td class="num">' + fmt(v.rounds ? 100 * v.rwpa / v.rounds : 0) + "</td>" +
        "<td>" + (v.won ? "won" : "lost") + "</td></tr>";
    }).join("");
    sheet.innerHTML =
      "<h3>Match " + (i + 1) + " · " + (m.map || "—") + "</h3>" +
      '<p class="meta">' + m.rounds + " rounds · " +
      present.length + " of the four played</p>" +
      "<table><thead><tr><th>Player</th><th>Agent</th><th class='num'>Rounds</th>" +
      "<th class='num'>RWPA</th><th class='num'>Per 100</th><th>Result</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table>" +
      (present.length === 1
        ? '<p class="solo">Only one of the four played this match, so there is nothing to compare here — this is a single record, not a contrast.</p>'
        : '<p class="solo">These ' + present.length + ' shared this match: same opponents, same rounds. ' +
          'Within a match the comparison holds; across the season it does not.</p>');
  }

  function boot() {
    renderLegend(); renderCards(); render(); renderTable();
    var last = D.matches.length - 1;
    if (last >= 0) select(last);
    var t = document.querySelector(".theme-toggle");
    if (t) t.addEventListener("click", function () { setTimeout(render, 0); });
    addEventListener("resize", function () { clearTimeout(boot._r); boot._r = setTimeout(render, 120); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
