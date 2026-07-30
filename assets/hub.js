/* ─────────────────────────────────────────────────────────────
   hub.js — the band that ties the sub-projects back to the site.

   Each project under chronicaria.github.io keeps its own design;
   this adds one prussian band across the top so you can always get
   home. It renders inside a shadow root, so none of the eight
   stylesheets underneath it can reach in and none of its rules leak
   out. Static flow, not fixed — it pushes the page down instead of
   covering whatever the host renders first.
   ───────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  var SECTIONS = [
    { href: "/rome-wiki/", label: "Rome Wiki" },
    { href: "/fantasy-basketball/", label: "Fantasy Basketball" },
    { href: "/fantasy-football/", label: "Fantasy Football" },
    { href: "/valorant/", label: "Valorant RWPA" },
    { href: "/concerto/", label: "Concerto Ranker" },
    { href: "/nyc-weather/", label: "Weather Dashboard" },
    { href: "/winter-trip/", label: "Italy, winter 2026–27" },
    { href: "/paper/", label: "Gothic Times v2" },
  ];

  var ELSEWHERE = [
    { href: "/", label: "Home" },
    { href: "/daily/", label: "Newspaper" },
    { href: "/sports.html", label: "Sports" },
    { href: "/music.html", label: "Music" },
    { href: "/literature.html", label: "Literature" },
    { href: "/weather.html", label: "Temperature" },
  ];

  // Longest matching prefix wins, so /fantasy-football/ doesn't answer to /fantasy-.
  function currentSection() {
    var path = location.pathname;
    var best = null;
    SECTIONS.forEach(function (s) {
      if (path.indexOf(s.href) === 0 && (!best || s.href.length > best.href.length)) best = s;
    });
    return best;
  }

  var CSS = [
    ":host{all:initial;display:block}",
    ".band{",
    "  display:flex;align-items:center;gap:.9rem;flex-wrap:wrap;",
    "  padding:.5rem clamp(.75rem,3vw,2rem);",
    "  background:#003153;color:#faf9f4;",
    '  font-family:"Newsreader",Georgia,"Times New Roman",serif;',
    "  font-size:15px;line-height:1.3;",
    "  border-bottom:2px solid #001a2c;",
    "  -webkit-font-smoothing:antialiased;",
    "}",
    ".home{display:flex;align-items:center;gap:.5rem;color:#faf9f4;text-decoration:none;font-weight:600}",
    ".home:hover .name{text-decoration:underline;text-underline-offset:3px}",
    ".mono{",
    "  display:grid;place-items:center;width:22px;height:22px;flex:none;",
    "  border:1.5px solid currentColor;font-size:10px;font-weight:700;letter-spacing:.03em;",
    '  font-family:"Bodoni Moda",Didot,Georgia,serif;',
    "}",
    ".here{opacity:.72;font-style:italic}",
    ".here::before{content:'/';margin-right:.55rem;font-style:normal;opacity:.55}",
    ".spacer{flex:1 1 auto}",
    "details{position:relative}",
    "summary{",
    "  list-style:none;cursor:pointer;user-select:none;",
    "  padding:.2rem .6rem;border:1px solid rgba(250,249,244,.42);",
    "  font-variant:small-caps;letter-spacing:.06em;font-size:14px;",
    "}",
    "summary::-webkit-details-marker{display:none}",
    "summary:hover,details[open] summary{background:rgba(250,249,244,.13)}",
    "summary:focus-visible,.home:focus-visible{outline:2px solid #faf9f4;outline-offset:2px}",
    ".menu{",
    "  position:absolute;right:0;top:calc(100% + .4rem);z-index:2147483647;",
    "  min-width:15rem;padding:.35rem;",
    "  background:#faf9f4;color:#10171e;",
    "  border:1px solid #003153;box-shadow:0 10px 30px rgba(0,0,0,.28);",
    "}",
    ".menu a{display:block;padding:.34rem .6rem;color:#10171e;text-decoration:none;font-size:14.5px}",
    ".menu a:hover{background:#003153;color:#faf9f4}",
    ".menu a[aria-current]{font-weight:700;background:rgba(0,49,83,.1)}",
    ".rule{margin:.35rem .6rem;border-top:1px solid rgba(16,23,30,.2)}",
    ".rule span{",
    "  display:block;margin-top:.4rem;font-variant:small-caps;letter-spacing:.07em;",
    "  font-size:12px;opacity:.62;",
    "}",
    "@media print{.band{display:none}}",
  ].join("");

  function group(items, here) {
    return items
      .map(function (i) {
        var cur = here && i.href === here.href ? ' aria-current="page"' : "";
        return '<a href="' + i.href + '"' + cur + ">" + i.label + "</a>";
      })
      .join("");
  }

  function mount() {
    if (document.getElementById("ap-hub")) return;

    var here = currentSection();
    var host = document.createElement("div");
    host.id = "ap-hub";
    var root = host.attachShadow({ mode: "open" });

    root.innerHTML =
      "<style>" + CSS + "</style>" +
      '<div class="band">' +
      '  <a class="home" href="/"><span class="mono">AP</span><span class="name">Andrew Park</span></a>' +
      (here ? '  <span class="here">' + here.label + "</span>" : "") +
      '  <span class="spacer"></span>' +
      "  <details>" +
      "    <summary>All projects</summary>" +
      '    <div class="menu">' +
      group(SECTIONS, here) +
      '      <div class="rule"><span>Elsewhere</span></div>' +
      group(ELSEWHERE, null) +
      "    </div>" +
      "  </details>" +
      "</div>";

    document.body.insertBefore(host, document.body.firstChild);

    // Click-away and Esc close the menu, matching the main site's nav-drop.
    var details = root.querySelector("details");
    document.addEventListener("click", function (e) {
      if (details.open && e.target !== host) details.open = false;
    });
    root.addEventListener("click", function (e) {
      e.stopPropagation();
      if (e.target.closest && e.target.closest(".menu a")) details.open = false;
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") details.open = false;
    });
  }

  // The Rome wiki is a hydrated Next.js export; React owns <body>'s children and
  // will discard a node inserted before hydration finishes. Waiting for load
  // covers that, and the re-check covers a client-side route change dropping it.
  if (document.readyState === "complete") mount();
  else window.addEventListener("load", mount);

  setInterval(function () {
    if (!document.getElementById("ap-hub")) mount();
  }, 1500);
})();
