/* ui.js — command palette, help overlay, service worker registration.
   Self-contained IIFE; injects its own CSS. Safe on file:// (no-op extras). */
(function () {
  "use strict";

  var isFile = location.protocol === "file:";

  /* ---- root prefix: how many path segments deep are we below the site root? ---- */
  function rootPrefix() {
    if (isFile) return "";
    // strip leading slash and trailing filename, count remaining directory segments
    var path = location.pathname.replace(/^\//, "");
    var parts = path.split("/");
    parts.pop(); // filename (or "" for directory URLs)
    var depth = parts.filter(function (p) { return p.length > 0; }).length;
    var prefix = "";
    for (var i = 0; i < depth; i++) prefix += "../";
    return prefix;
  }
  var PREFIX = rootPrefix();

  /* ---------------- styles ---------------- */
  var style = document.createElement("style");
  style.textContent = [
    ".ui-overlay{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.5);display:flex;align-items:flex-start;justify-content:center;padding:10vh 1rem 1rem;}",
    ".ui-overlay[hidden]{display:none;}",
    ".ui-panel{width:34rem;max-width:100%;background:var(--panel,#171b21);border:1px solid var(--line,#2a313b);border-radius:.15rem;box-shadow:0 18px 50px rgba(0,0,0,.45);overflow:hidden;}",
    ".ui-pal-input{width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom:1px solid var(--line,#2a313b);color:var(--text,#e6e9ee);font:inherit;font-size:1rem;padding:.75rem .9rem;outline:none;}",
    ".ui-pal-input::placeholder{color:var(--muted,#939ca7);}",
    ".ui-pal-list{list-style:none;margin:0;padding:.3rem;max-height:21rem;overflow-y:auto;}",
    ".ui-pal-list li{padding:.45rem .6rem;border-radius:.15rem;cursor:pointer;display:flex;justify-content:space-between;gap:.75rem;color:var(--text,#e6e9ee);font-size:.92rem;}",
    ".ui-pal-list li .ui-pal-kind{color:var(--muted,#939ca7);font-size:.78rem;white-space:nowrap;}",
    ".ui-pal-list li.active{background:var(--panel-2,#1d232b);outline:1px solid var(--accent,#5b9dff);outline-offset:-1px;}",
    ".ui-pal-empty{padding:.6rem .7rem;color:var(--muted,#939ca7);font-size:.88rem;}",
    ".ui-help-body{padding:.9rem 1rem;color:var(--text,#e6e9ee);font-size:.92rem;line-height:1.7;}",
    ".ui-help-body h3{margin:0 0 .4rem;font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#939ca7);}",
    ".ui-help-body kbd{background:var(--panel-2,#1d232b);border:1px solid var(--line,#2a313b);border-radius:.15rem;padding:.05rem .35rem;font-size:.82rem;}",
    ".ui-shelf-head{padding:.6rem .9rem;border-bottom:1px solid var(--line,#2a313b);color:var(--muted,#939ca7);font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;}",
    ".ui-shelf-list{list-style:none;margin:0;padding:.3rem;max-height:21rem;overflow-y:auto;}",
    ".ui-shelf-list li{display:flex;align-items:center;gap:.6rem;padding:.45rem .6rem;border-radius:.15rem;font-size:.92rem;}",
    ".ui-shelf-list li a{flex:1;min-width:0;color:var(--text,#e6e9ee);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
    ".ui-shelf-list li a:hover{color:var(--accent,#5b9dff);}",
    ".ui-shelf-src{color:var(--muted,#939ca7);font-size:.78rem;white-space:nowrap;}",
    ".ui-shelf-x{background:none;border:0;color:var(--muted,#939ca7);cursor:pointer;font:inherit;font-size:.88rem;line-height:1;padding:.1rem .25rem;}",
    ".ui-shelf-x:hover{color:var(--text,#e6e9ee);}",
    ".ui-shelf-empty{padding:.6rem .7rem;color:var(--muted,#939ca7);font-size:.88rem;}",
    ".ui-shelf-foot{display:flex;justify-content:flex-end;padding:.5rem .6rem;border-top:1px solid var(--line,#2a313b);}",
    ".ui-shelf-clear{background:var(--panel-2,#1d232b);border:1px solid var(--line,#2a313b);border-radius:.15rem;color:var(--text,#e6e9ee);font:inherit;font-size:.82rem;padding:.25rem .6rem;cursor:pointer;}",
    ".ui-shelf-clear:hover{border-color:var(--accent,#5b9dff);}"
  ].join("\n");
  document.head.appendChild(style);

  /* ---------------- data sources ---------------- */
  var STATIC_ENTRIES = [
    { n: "Home", u: "index.html", k: "page" },
    { n: "Newspaper front page", u: "daily/index.html", k: "daily" },
    { n: "Newspaper: Sports desk", u: "daily/sports.html", k: "daily" },
    { n: "Newspaper: AI & Models", u: "daily/ai.html", k: "daily" },
    { n: "Newspaper: Markets", u: "daily/markets.html", k: "daily" },
    { n: "Newspaper: Elections", u: "daily/elections.html", k: "daily" },
    { n: "Newspaper: Math", u: "daily/math.html", k: "daily" },
    { n: "Newspaper: Archive", u: "daily/archive.html", k: "daily" },
    { n: "Sports trackers", u: "sports.html", k: "page" },
    { n: "Music", u: "music.html", k: "page" },
    { n: "Literature", u: "literature.html", k: "page" },
    { n: "SMP Basketball League", u: "league/index.html", k: "league" }
  ];

  var leagueEntries = null;   // null = not loaded, [] = loaded (possibly empty/failed)
  var leagueLoading = false;
  var leaguePlayers = [];     // players only, for the random-player action
  var pendingRandomPlayer = false;

  function loadLeagueIndex() {
    if (leagueEntries !== null || leagueLoading || isFile) return;
    leagueLoading = true;
    fetch(PREFIX + "league/assets/search-index.json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var out = [];
        if (data) {
          (data.teams || []).forEach(function (t) {
            out.push({ n: "SMP: " + t.n, u: "league/" + t.u, k: "team" });
          });
          (data.players || []).forEach(function (p) {
            var e = { n: "SMP: " + p.n, u: "league/" + p.u, k: p.t || "player" };
            out.push(e);
            leaguePlayers.push(e);
          });
        }
        leagueEntries = out;
        if (pendingRandomPlayer) {
          pendingRandomPlayer = false;
          if (leaguePlayers.length) { goRandomPlayer(); return; }
        }
        if (!overlay.hidden) renderResults(input.value);
      })
      .catch(function () { leagueEntries = []; pendingRandomPlayer = false; });
  }

  function goRandomPlayer() {
    var p = leaguePlayers[Math.floor(Math.random() * leaguePlayers.length)];
    closePalette();
    location.href = PREFIX + p.u;
  }

  /* ---------------- saved-for-later shelf (localStorage contract: gtShelf) ---------------- */
  function readShelf() {
    try {
      var v = JSON.parse(localStorage.getItem("gtShelf") || "[]");
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }
  function writeShelf(items) {
    try { localStorage.setItem("gtShelf", JSON.stringify(items)); } catch (e) { /* ignore */ }
  }

  var shelf = null;
  function buildShelf() {
    shelf = document.createElement("div");
    shelf.className = "ui-overlay";
    shelf.hidden = true;
    shelf.innerHTML =
      '<div class="ui-panel" role="dialog" aria-label="Saved for later">' +
      '<div class="ui-shelf-head">Saved for later</div>' +
      '<ul class="ui-shelf-list"></ul>' +
      '<div class="ui-shelf-foot"><button type="button" class="ui-shelf-clear">Clear all</button></div>' +
      "</div>";
    shelf.addEventListener("mousedown", function (ev) {
      if (ev.target === shelf) shelf.hidden = true;
    });
    shelf.querySelector(".ui-shelf-clear").addEventListener("click", function () {
      writeShelf([]);
      renderShelf();
    });
    document.body.appendChild(shelf);
  }

  function renderShelf() {
    var ul = shelf.querySelector(".ui-shelf-list");
    ul.innerHTML = "";
    var items = readShelf();
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "ui-shelf-empty";
      empty.textContent = "Nothing saved.";
      ul.appendChild(empty);
      return;
    }
    items.forEach(function (item, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = item.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = item.title || item.url;
      var src = document.createElement("span");
      src.className = "ui-shelf-src";
      src.textContent = item.source || "";
      var x = document.createElement("button");
      x.type = "button";
      x.className = "ui-shelf-x";
      x.textContent = "✕";
      x.setAttribute("aria-label", "Remove");
      x.addEventListener("click", function () {
        var cur = readShelf();
        cur.splice(i, 1);
        writeShelf(cur);
        renderShelf();
      });
      li.appendChild(a);
      li.appendChild(src);
      li.appendChild(x);
      ul.appendChild(li);
    });
  }

  function openShelf() {
    closePalette();
    if (!shelf) buildShelf();
    renderShelf();
    shelf.hidden = false;
  }

  /* ---------------- palette actions ---------------- */
  var ACTIONS = [
    {
      n: "Toggle light/dark theme", k: "action",
      run: function () {
        var next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
        document.documentElement.dataset.theme = next;
        try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
        var btn = document.querySelector("[data-theme-toggle]");
        if (btn) btn.textContent = next === "light" ? "◑ dark mode" : "◐ light mode";
      }
    },
    {
      n: "Random edition from the Morgue", k: "action",
      run: function () {
        if (isFile) return;
        fetch(PREFIX + "data/daily/index.json?v=" + new Date().toISOString().slice(0, 10))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (dates) {
            if (!dates || !dates.length) return;
            var d = dates[Math.floor(Math.random() * dates.length)];
            if (typeof d !== "string") d = d && d.date;
            if (!d) return;
            closePalette();
            location.href = PREFIX + "daily/index.html?date=" + encodeURIComponent(d);
          })
          .catch(function () { /* ignore */ });
      }
    },
    {
      n: "Random SMP player", k: "action",
      run: function () {
        if (leaguePlayers.length) { goRandomPlayer(); return; }
        if (leagueEntries !== null) return; // index loaded; no players to pick from
        pendingRandomPlayer = true;
        loadLeagueIndex();
      }
    },
    {
      n: "Open today's puzzle", k: "action",
      run: function () {
        closePalette();
        location.href = PREFIX + "daily/index.html#puzzle";
      }
    },
    {
      n: "Copy RSS feed URL", k: "action",
      run: function (idx) {
        var done = function () { flashRow(idx, "Copied ✓"); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText("https://chronicaria.github.io/daily.xml").then(done, done);
        }
      }
    }
  ];

  function actionEntries() {
    var out = ACTIONS.slice();
    var count = readShelf().length;
    if (count > 0) {
      out.push({ n: "Saved for later (" + count + ")", k: "action", run: openShelf });
    }
    return out;
  }

  /* ---------------- matching ---------------- */
  function subsequence(needle, hay) {
    var i = 0;
    for (var j = 0; j < hay.length && i < needle.length; j++) {
      if (hay.charCodeAt(j) === needle.charCodeAt(i)) i++;
    }
    return i === needle.length;
  }

  function score(q, name) {
    var n = name.toLowerCase();
    if (!q) return 1;
    var idx = n.indexOf(q);
    if (idx === 0) return 100;
    if (idx > 0) return 60 - Math.min(idx, 40);
    if (subsequence(q, n)) return 10;
    return -1;
  }

  function search(q) {
    q = q.trim().toLowerCase();
    var actions = actionEntries();
    if (!q) return STATIC_ENTRIES.concat(actions); // page links first, then actions
    var pool = STATIC_ENTRIES.concat(leagueEntries || []).concat(actions);
    var scored = [];
    for (var i = 0; i < pool.length; i++) {
      var s = score(q, pool[i].n);
      if (s >= 0) scored.push({ s: s, e: pool[i] });
    }
    scored.sort(function (a, b) { return b.s - a.s; });
    return scored.slice(0, 9).map(function (x) { return x.e; });
  }

  /* ---------------- palette DOM ---------------- */
  var overlay = document.createElement("div");
  overlay.className = "ui-overlay";
  overlay.hidden = true;
  overlay.innerHTML =
    '<div class="ui-panel" role="dialog" aria-label="Command palette">' +
    '<input class="ui-pal-input" type="text" placeholder="Jump to a page, team, or player…" autocomplete="off" spellcheck="false">' +
    '<ul class="ui-pal-list"></ul>' +
    "</div>";

  var help = document.createElement("div");
  help.className = "ui-overlay";
  help.hidden = true;
  help.innerHTML =
    '<div class="ui-panel" role="dialog" aria-label="Keyboard shortcuts">' +
    '<div class="ui-help-body"><h3>Keyboard shortcuts</h3>' +
    "<div><kbd>⌘K</kbd> palette &middot; <kbd>1</kbd>–<kbd>6</kbd> pages (site) &middot; " +
    "<kbd>1</kbd>–<kbd>5</kbd> desks (daily) &middot; <kbd>←</kbd>/<kbd>→</kbd> editions (daily) &middot; " +
    "<kbd>?</kbd> this help</div></div></div>";

  function mount() {
    document.body.appendChild(overlay);
    document.body.appendChild(help);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);

  var input = overlay.querySelector(".ui-pal-input");
  var list = overlay.querySelector(".ui-pal-list");
  var results = [];
  var activeIdx = 0;

  function renderResults(q) {
    results = search(q || "");
    activeIdx = 0;
    list.innerHTML = "";
    if (!results.length) {
      var empty = document.createElement("li");
      empty.className = "ui-pal-empty";
      empty.textContent = "No matches.";
      list.appendChild(empty);
      return;
    }
    results.forEach(function (e, i) {
      var li = document.createElement("li");
      if (i === activeIdx) li.className = "active";
      var name = document.createElement("span");
      name.textContent = e.n;
      var kind = document.createElement("span");
      kind.className = "ui-pal-kind";
      kind.textContent = e.k || "";
      li.appendChild(name);
      li.appendChild(kind);
      li.addEventListener("click", function () { go(e, i); });
      li.addEventListener("mousemove", function () {
        if (activeIdx !== i) { activeIdx = i; highlight(); }
      });
      list.appendChild(li);
    });
  }

  function highlight() {
    var items = list.children;
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", i === activeIdx);
    }
    var el = items[activeIdx];
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function go(entry, idx) {
    if (entry.run) { entry.run(idx); return; }
    closePalette();
    location.href = PREFIX + entry.u;
  }

  function flashRow(idx, text) {
    var li = list.children[idx];
    if (!li || !li.firstChild) return;
    var span = li.firstChild;
    var orig = span.textContent;
    span.textContent = text;
    setTimeout(function () {
      if (span.textContent === text) span.textContent = orig;
    }, 1200);
  }

  function openPalette() {
    help.hidden = true;
    overlay.hidden = false;
    input.value = "";
    renderResults("");
    loadLeagueIndex();
    input.focus();
  }
  function closePalette() { overlay.hidden = true; }

  input.addEventListener("input", function () { renderResults(input.value); });
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      if (results.length) { activeIdx = (activeIdx + 1) % results.length; highlight(); }
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      if (results.length) { activeIdx = (activeIdx - 1 + results.length) % results.length; highlight(); }
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (results[activeIdx]) go(results[activeIdx], activeIdx);
    }
  });
  overlay.addEventListener("mousedown", function (ev) {
    if (ev.target === overlay) closePalette();
  });
  help.addEventListener("mousedown", function (ev) {
    if (ev.target === help) help.hidden = true;
  });

  /* ---------------- global keys ---------------- */
  function inEditable(ev) {
    var t = ev.target;
    if (!t) return false;
    var tag = (t.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || t.isContentEditable;
  }

  document.addEventListener("keydown", function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === "k" || ev.key === "K")) {
      ev.preventDefault();
      if (overlay.hidden) openPalette(); else closePalette();
      return;
    }
    if (ev.key === "Escape") {
      if (!overlay.hidden) { ev.preventDefault(); closePalette(); }
      else if (shelf && !shelf.hidden) { ev.preventDefault(); shelf.hidden = true; }
      else if (!help.hidden) { ev.preventDefault(); help.hidden = true; }
      return;
    }
    if (ev.key === "?" && !inEditable(ev) && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
      ev.preventDefault();
      overlay.hidden = true;
      help.hidden = !help.hidden;
    }
  });

  /* ---------------- service worker ---------------- */
  try {
    if (!isFile && "serviceWorker" in navigator && location.protocol === "https:") {
      navigator.serviceWorker.register(PREFIX + "sw.js").catch(function () { /* ignore */ });
    }
  } catch (e) { /* ignore */ }
})();
