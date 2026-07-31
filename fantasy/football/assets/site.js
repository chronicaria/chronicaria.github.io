/* site.js — theme, search, nav dropdowns, and the draft-room board.
   Vanilla, one IIFE, no dependencies. Anti-drift rules:
   - nothing here writes prose; the generator owns every string the reader sees
   - the board's sort is stable and type-aware, and blanks always sort last
   - no LaTeX: this vault forbids it, so there is no math renderer to load */
(function () {
  "use strict";
  var css = document.querySelector('link[href$="assets/style.css"]');
  var rel = css ? css.getAttribute("href").replace("assets/style.css", "") : "";

  /* ---- theme -------------------------------------------------------------- */
  var btn = document.getElementById("theme");
  function paint() {
    if (btn) btn.textContent = document.documentElement.dataset.theme === "lamp" ? "☀" : "☾";
  }
  if (btn) {
    btn.addEventListener("click", function () {
      var next = document.documentElement.dataset.theme === "lamp" ? "paper" : "lamp";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("ff-theme", next); } catch (e) {}
      paint();
    });
  }
  paint();

  /* ---- nav dropdowns ------------------------------------------------------ */
  var drops = [].slice.call(document.querySelectorAll(".navdrop"));
  drops.forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (d.open) drops.forEach(function (o) { if (o !== d) o.open = false; });
    });
  });
  document.addEventListener("click", function (e) {
    drops.forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; });
  });

  /* ---- search ------------------------------------------------------------- */
  var q = document.getElementById("q"), qr = document.getElementById("qr");
  var index = null, active = -1, shown = [];
  function norm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function load(cb) {
    if (index) return cb();
    fetch(rel + "assets/search-index.json")
      .then(function (r) { return r.json(); })
      .then(function (j) { index = j; cb(); })
      .catch(function () { index = []; cb(); });
  }
  function render(list) {
    shown = list; active = -1;
    if (!list.length) { qr.hidden = true; return; }
    qr.innerHTML = list.map(function (r, i) {
      return '<div class="opt" data-i="' + i + '"><span class="nm">' + r.t +
        '</span><span class="meta">' + r.s + "</span></div>";
    }).join("");
    qr.hidden = false;
    [].forEach.call(qr.children, function (el) {
      el.addEventListener("mousedown", function (e) {
        e.preventDefault();
        location.href = rel + shown[+el.getAttribute("data-i")].u;
      });
    });
  }
  function search(term) {
    var t = norm(term.trim());
    if (t.length < 2) { render([]); return; }
    var words = t.split(/\s+/), scored = [];
    for (var i = 0; i < index.length; i++) {
      var hay = norm(index[i].t + " " + index[i].s + " " + (index[i].d || ""));
      var name = norm(index[i].t);
      var ok = true;
      for (var w = 0; w < words.length; w++) {
        if (hay.indexOf(words[w]) === -1) { ok = false; break; }
      }
      if (!ok) continue;
      var score = name.indexOf(words[0]) === 0 ? 0 : (name.indexOf(words[0]) !== -1 ? 1 : 2);
      scored.push([score, index[i]]);
    }
    scored.sort(function (a, b) { return a[0] - b[0] || a[1].t.localeCompare(b[1].t); });
    render(scored.slice(0, 12).map(function (s) { return s[1]; }));
  }
  if (q) {
    q.addEventListener("focus", function () { load(function () {}); });
    q.addEventListener("input", function () { load(function () { search(q.value); }); });
    q.addEventListener("keydown", function (e) {
      if (qr.hidden) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
        [].forEach.call(qr.children, function (el, i) {
          el.classList.toggle("active", i === active);
          if (i === active && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
        });
      } else if (e.key === "Enter" && active >= 0) {
        location.href = rel + shown[active].u;
      } else if (e.key === "Escape") { render([]); q.blur(); }
    });
    q.addEventListener("blur", function () { setTimeout(function () { render([]); }, 150); });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== q &&
        !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      e.preventDefault(); if (q) q.focus();
    }
  });

  /* ---- the board: text filter, position pills, sort by any column --------- */
  var board = document.getElementById("board");
  if (board) {
    var tbody = board.tBodies[0];
    var rows = [].slice.call(tbody.rows);
    var text = "", pos = "ALL";
    var count = document.getElementById("boardcount");

    function apply() {
      var n = 0;
      rows.forEach(function (r) {
        var okPos = pos === "ALL" || r.getAttribute("data-pos") === pos;
        var okText = !text || norm(r.textContent).indexOf(text) !== -1;
        var show = okPos && okText;
        r.style.display = show ? "" : "none";
        if (show) n++;
      });
      if (count) count.textContent = n + (n === 1 ? " player" : " players");
    }

    var bf = document.getElementById("bf");
    if (bf) bf.addEventListener("input", function () { text = norm(bf.value); apply(); });

    var pills = [].slice.call(document.querySelectorAll(".posfilter"));
    pills.forEach(function (b) {
      b.addEventListener("click", function () {
        pills.forEach(function (o) { o.classList.remove("on"); });
        b.classList.add("on");
        pos = b.getAttribute("data-pos");
        apply();
      });
    });
    var first = document.querySelector('.posfilter[data-pos="ALL"]');
    if (first) first.classList.add("on");

    // Blank and em-dash sort last in both directions, so a missing value never
    // masquerades as a zero — the same fail-loud rule the data pipeline uses.
    function keyOf(cell) {
      var t = cell.textContent.replace(/[#,%+]/g, "").trim();
      if (t === "" || t === "—") return null;
      var n = parseFloat(t);
      return isNaN(n) ? t.toLowerCase() : n;
    }
    [].forEach.call(board.tHead.rows[0].cells, function (th, col) {
      th.setAttribute("tabindex", "0");
      function sort() {
        var asc = !th.classList.contains("asc");
        [].forEach.call(board.tHead.rows[0].cells, function (h) {
          h.classList.remove("asc", "desc");
          h.removeAttribute("aria-sort");
        });
        th.classList.add(asc ? "asc" : "desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var idx = rows.map(function (r, i) { return [r, i]; });
        idx.sort(function (a, b) {
          var x = keyOf(a[0].cells[col]), y = keyOf(b[0].cells[col]);
          if (x === null && y === null) return a[1] - b[1];
          if (x === null) return 1;
          if (y === null) return -1;
          if (typeof x === "number" && typeof y === "number") {
            return (asc ? x - y : y - x) || a[1] - b[1];
          }
          return (asc ? String(x).localeCompare(y) : String(y).localeCompare(x))
            || a[1] - b[1];
        });
        var frag = document.createDocumentFragment();
        idx.forEach(function (p) { frag.appendChild(p[0]); });
        tbody.appendChild(frag);
      }
      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); }
      });
    });
    apply();
  }
})();
