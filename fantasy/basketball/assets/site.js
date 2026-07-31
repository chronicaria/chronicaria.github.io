/* site.js — theme toggle, global search, dropdown behavior, sortable tables, KaTeX. */
(function () {
  "use strict";
  var rel = document.body.getAttribute("data-rel") || "";

  /* ---- theme -------------------------------------------------------------- */
  var btn = document.getElementById("themebtn");
  function paint() {
    var t = document.documentElement.dataset.theme;
    if (btn) btn.textContent = t === "lamp" ? "☀" : "☾";
  }
  if (btn) btn.addEventListener("click", function () {
    var next = document.documentElement.dataset.theme === "lamp" ? "paper" : "lamp";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("fbe-theme", next); } catch (e) {}
    paint();
  });
  paint();

  /* ---- nav dropdowns: only one open, close on outside click --------------- */
  var drops = [].slice.call(document.querySelectorAll(".navdrop"));
  drops.forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (d.open) drops.forEach(function (o) { if (o !== d) o.open = false; });
    });
  });
  document.addEventListener("click", function (e) {
    drops.forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; });
  });

  /* ---- global search ------------------------------------------------------ */
  var q = document.getElementById("q"), qr = document.getElementById("qr");
  var index = null, active = -1, shown = [];
  function load(cb) {
    if (index) return cb();
    fetch(rel + "assets/search-index.json").then(function (r) { return r.json(); })
      .then(function (j) { index = j; cb(); }).catch(function () {});
  }
  function norm(s) {
    return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  function render(list) {
    shown = list; active = -1;
    if (!list.length) { qr.hidden = true; q.setAttribute("aria-expanded", "false"); return; }
    qr.innerHTML = list.map(function (r, i) {
      return '<div class="opt" role="option" data-i="' + i + '"><span class="nm">' + r.t +
        '</span><span class="meta">' + (r.x ? r.x + " · " : "") + r.k + "</span></div>";
    }).join("");
    qr.hidden = false; q.setAttribute("aria-expanded", "true");
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
    var words = t.split(/\s+/);
    var scored = [];
    for (var i = 0; i < index.length; i++) {
      var name = norm(index[i].t);
      var ok = words.every(function (w) { return name.indexOf(w) !== -1; });
      if (!ok) continue;
      var score = name.indexOf(words[0]) === 0 ? 0 : 1;
      if (index[i].k === "player") score -= 0.5;
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
        [].forEach.call(qr.children, function (el, i) { el.classList.toggle("active", i === active); });
      } else if (e.key === "Enter" && active >= 0) {
        location.href = rel + shown[active].u;
      } else if (e.key === "Escape") { render([]); q.blur(); }
    });
    q.addEventListener("blur", function () { setTimeout(function () { render([]); }, 150); });
  }

  /* ---- players index: filter + sort --------------------------------------- */
  var filter = document.getElementById("pfilter"), table = document.getElementById("ptable");
  if (filter && table) {
    var rows = [].slice.call(table.tBodies[0].rows);
    filter.addEventListener("input", function () {
      var t = norm(filter.value);
      rows.forEach(function (r) {
        r.style.display = norm(r.textContent).indexOf(t) !== -1 ? "" : "none";
      });
    });
  }
  if (table) {
    [].forEach.call(table.tHead.rows[0].cells, function (th, col) {
      th.addEventListener("click", function () {
        var numeric = th.hasAttribute("data-n");
        var asc = !th.classList.contains("asc");
        [].forEach.call(table.tHead.rows[0].cells, function (h) { h.classList.remove("asc", "desc"); });
        th.classList.add(asc ? "asc" : "desc");
        var rows = [].slice.call(table.tBodies[0].rows);
        rows.sort(function (a, b) {
          var x = a.cells[col].textContent.replace(/[#—]/g, "").trim();
          var y = b.cells[col].textContent.replace(/[#—]/g, "").trim();
          if (numeric) {
            var nx = parseFloat(x), ny = parseFloat(y);
            if (isNaN(nx)) nx = Infinity; if (isNaN(ny)) ny = Infinity;
            return asc ? nx - ny : ny - nx;
          }
          return asc ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
  }

  /* ---- KaTeX -------------------------------------------------------------- */
  window.addEventListener("load", function () {
    if (window.renderMathInElement) {
      renderMathInElement(document.body, {
        delimiters: [
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false }
        ], throwOnError: false
      });
    }
  });
})();
