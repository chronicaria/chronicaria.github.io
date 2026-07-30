/* app.js — Italy, winter 2026–27.
   Vanilla, no dependencies, no build step. Five jobs: theme toggle,
   mobile nav, ⌘K jump-to-anywhere, scroll reveal, rail scrollspy.
   The theme is set pre-paint by an inline script in each <head>;
   this file only owns the button. */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  /* ---------- theme ---------- */
  var themeBtn = document.querySelector(".theme-toggle");
  function paintTheme() {
    if (!themeBtn) return;
    var dark = root.dataset.theme === "dark";
    themeBtn.textContent = dark ? "◑ light" : "◐ dark";
    themeBtn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  paintTheme();
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem("italy-theme", root.dataset.theme); } catch (e) {}
      paintTheme();
    });
  }

  /* ---------- mobile nav ---------- */
  var burger = document.querySelector(".nav-burger");
  var nav = document.querySelector(".primary-nav");
  if (burger && nav) {
    burger.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* ---------- current year ---------- */
  var y = document.querySelector("[data-year]");
  if (y) y.textContent = new Date().getFullYear();

  /* ---------- scroll reveal ---------- */
  var reveals = document.querySelectorAll(".reveal");
  if (reveals.length && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- rail scrollspy ---------- */
  var railLinks = [].slice.call(document.querySelectorAll(".rail a"));
  if (railLinks.length && "IntersectionObserver" in window) {
    var targets = railLinks
      .map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); })
      .filter(Boolean);
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        railLinks.forEach(function (a) {
          a.classList.toggle("active", a.getAttribute("href") === "#" + e.target.id);
        });
      });
    }, { rootMargin: "-10% 0px -75% 0px" });
    targets.forEach(function (t) { spy.observe(t); });
  }

  /* ---------- ⌘K: jump to any page, day, or section ----------
     Fourteen days across eight pages is more than a nav bar can hold.
     The index is built once: the site's pages, plus every heading on
     the current page that carries an id. */
  var PAGES = [
    ["The trip", "index.html", "page"],
    ["Day by day", "itinerary.html", "page"],
    ["Lake Como", "como.html", "page"],
    ["Flights & trains", "travel.html", "page"],
    ["Stays & budget", "stays.html", "page"],
    ["Bookings & calendar", "bookings.html", "page"],
    ["Food & practical", "food.html", "page"],
    ["What we cut", "alternatives.html", "page"]
  ];

  var index = PAGES.map(function (p) {
    return { name: p[0], url: p[1], kind: p[2] };
  });

  document.querySelectorAll("[id][data-jump]").forEach(function (el) {
    index.push({
      name: el.getAttribute("data-jump"),
      url: "#" + el.id,
      kind: el.getAttribute("data-jump-kind") || "on this page"
    });
  });

  var bg = document.createElement("div");
  bg.className = "pal-bg";
  bg.innerHTML =
    '<div class="pal" role="dialog" aria-modal="true" aria-label="Jump to">' +
    '<input type="text" placeholder="Jump to a day, page, or section…" ' +
    'aria-label="Jump to" role="combobox" aria-expanded="true" aria-controls="pal-list" autocomplete="off">' +
    '<ul id="pal-list" role="listbox"></ul>' +
    '<div class="pal-hint"><span>↑↓ move</span><span>↵ go</span><span>esc close</span></div>' +
    "</div>";
  document.body.appendChild(bg);

  var input = bg.querySelector("input");
  var list = bg.querySelector("ul");
  var results = [];
  var cursor = 0;

  function score(q, name) {
    var n = name.toLowerCase();
    var i = n.indexOf(q);
    if (i === 0) return 100;
    if (i > 0) return 60 - i;
    // subsequence fallback: "dec28" matches "Mon Dec 28 — Pisa and Lucca"
    var j = 0;
    for (var k = 0; k < n.length && j < q.length; k++) if (n[k] === q[j]) j++;
    return j === q.length ? 10 : -1;
  }

  function render() {
    list.innerHTML = "";
    if (!results.length) {
      list.innerHTML = '<li class="pal-empty" role="presentation">Nothing matches that.</li>';
      return;
    }
    results.forEach(function (r, i) {
      var li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === cursor ? "true" : "false");
      if (i === cursor) li.className = "on";
      li.innerHTML = '<span class="pal-name"></span><span class="pal-kind"></span>';
      li.querySelector(".pal-name").textContent = r.name;
      li.querySelector(".pal-kind").textContent = r.kind;
      li.addEventListener("click", function () { go(r); });
      list.appendChild(li);
    });
  }

  function search() {
    var q = input.value.trim().toLowerCase();
    results = q
      ? index
          .map(function (r) { return { r: r, s: score(q, r.name) }; })
          .filter(function (x) { return x.s >= 0; })
          .sort(function (a, b) { return b.s - a.s; })
          .slice(0, 10)
          .map(function (x) { return x.r; })
      : index.slice(0, 10);
    cursor = 0;
    render();
  }

  function go(r) {
    close();
    window.location.href = r.url;
  }

  function open() {
    bg.classList.add("open");
    input.value = "";
    search();
    input.focus();
  }
  function close() {
    bg.classList.remove("open");
  }

  input.addEventListener("input", search);
  bg.addEventListener("click", function (e) { if (e.target === bg) close(); });

  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;

    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      bg.classList.contains("open") ? close() : open();
      return;
    }
    if (e.key === "/" && !typing && !bg.classList.contains("open")) {
      e.preventDefault();
      open();
      return;
    }
    if (!bg.classList.contains("open")) return;

    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); cursor = (cursor + 1) % results.length; render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cursor = (cursor - 1 + results.length) % results.length; render(); }
    else if (e.key === "Enter" && results[cursor]) { e.preventDefault(); go(results[cursor]); }
  });
})();
