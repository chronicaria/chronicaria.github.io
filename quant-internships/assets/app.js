/* ─────────────────────────────────────────────────────────────
   app.js — one IIFE, no dependencies.

   Reads ROLES from data.js, renders the table, and owns four
   pieces of state: role-type filter, location filter, free text,
   and the applied set (localStorage). Sorting is a stable sort on
   a key function. Nothing here talks to the network.
   ───────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  var THEME_KEY = "quant-internships-theme";
  var APPLIED_KEY = "quant-internships-applied";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ── applied set ───────────────────────────────────────────── */
  var applied = new Set();
  try {
    var raw = localStorage.getItem(APPLIED_KEY);
    if (raw) JSON.parse(raw).forEach(function (id) { applied.add(id); });
  } catch (e) { /* private mode, ignore */ }

  function persistApplied() {
    // Array.from, not slice.call — a Set has no length, so slice yields [].
    var out = [];
    applied.forEach(function (id) { out.push(id); });
    try { localStorage.setItem(APPLIED_KEY, JSON.stringify(out)); }
    catch (e) { /* private mode, ignore */ }
  }

  /* ── state ─────────────────────────────────────────────────── */
  var state = {
    types: new Set(),      // empty = all
    locs: new Set(),       // empty = all
    statuses: new Set(),   // empty = all; "open" | "soon"
    q: "",
    hideApplied: false,
    sort: "priority",
    dir: 1
  };

  // QT before QR before QD; then tier; then NYC first; then curation order.
  // Curation order is the order rows appear in data.js — within a tier that
  // encodes the judgement call alphabetical sorting would throw away.
  var TYPE_RANK = { QT: 0, QR: 1, QD: 2 };
  ROLES.forEach(function (r, i) { r._i = i; });

  function isNYC(role) {
    return role.locations.some(function (l) { return /new york|nyc/i.test(l); });
  }

  function priority(role) {
    return [
      TYPE_RANK[role.role_type] === undefined ? 9 : TYPE_RANK[role.role_type],
      role.tier || 9,
      isNYC(role) ? 0 : 1,
      role._i
    ];
  }

  var SORTS = {
    priority: priority,
    firm: function (r) { return [r.firm.toLowerCase()]; },
    type: function (r) { return [TYPE_RANK[r.role_type] === undefined ? 9 : TYPE_RANK[r.role_type], r.firm.toLowerCase()]; },
    tier: function (r) { return [r.tier || 9, TYPE_RANK[r.role_type] || 9, r.firm.toLowerCase()]; },
    comp: function (r) { return [r.comp_rank == null ? -1 : r.comp_rank, r.firm.toLowerCase()]; }
  };

  function cmp(a, b) {
    for (var i = 0; i < Math.max(a.length, b.length); i++) {
      var x = a[i], y = b[i];
      if (x === undefined) return -1;
      if (y === undefined) return 1;
      if (x < y) return -1;
      if (x > y) return 1;
    }
    return 0;
  }

  /* ── filtering ─────────────────────────────────────────────── */
  function locBucket(role) {
    if (isNYC(role)) return "NYC";
    if (role.locations.some(function (l) { return /chicago/i.test(l); })) return "Chicago";
    return "Other";
  }

  function matches(role) {
    if (state.types.size && !state.types.has(role.role_type)) return false;
    if (state.locs.size && !state.locs.has(locBucket(role))) return false;
    if (state.statuses.size && !state.statuses.has(role.status || "open")) return false;
    if (state.hideApplied && applied.has(role.id)) return false;
    if (state.q) {
      var hay = [role.firm, role.title, role.role_type, role.locations.join(" "),
                 role.notes || "", role.comp || ""].join(" ").toLowerCase();
      if (hay.indexOf(state.q) === -1) return false;
    }
    return true;
  }

  /* ── render ────────────────────────────────────────────────── */
  var tbody = $("#rows");
  var empty = $("#empty");
  var tally = $("#tally-n");
  var tallyLabel = $("#tally-label");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function locHTML(role) {
    return role.locations.map(function (l) {
      return /new york|nyc/i.test(l)
        ? '<span class="nyc">' + esc(l) + "</span>"
        : esc(l);
    }).join(", ");
  }

  function rowHTML(role) {
    var isApplied = applied.has(role.id);
    var compCls = role.comp ? "comp" : "comp unknown";
    var compInner = role.comp
      ? esc(role.comp) + (role.comp_source ? '<span class="src">' + esc(role.comp_source) + "</span>" : "")
      : "not disclosed";
    // Explicit flag, not a regex on the prose: "bundle several roles in one
    // application" is permissive and was being flagged as a restriction.
    var multiCls = role.one_only ? "multi one-only" : "multi";
    var applyBtn;
    if (role.status === "soon") {
      applyBtn = role.apply_url
        ? '<a class="apply soon" href="' + esc(role.apply_url) + '" target="_blank" rel="noopener">'
          + esc(role.opens || "Opens soon") + "</a>"
        : '<span class="apply soon" aria-disabled="true">' + esc(role.opens || "Opens soon") + "</span>";
    } else if (role.apply_url) {
      applyBtn = '<a class="apply" href="' + esc(role.apply_url) + '" target="_blank" rel="noopener">Apply &rarr;</a>';
    } else {
      applyBtn = '<span class="apply" aria-disabled="true">No link</span>';
    }

    return '<tr class="' + (isApplied ? "is-applied " : "") + (role.status === "soon" ? "is-soon" : "")
      + '" data-id="' + esc(role.id) + '">'
      + '<td class="firm">' + esc(role.firm)
        + (role.firm_note ? '<span class="sub">' + esc(role.firm_note) + "</span>" : "")
      + "</td>"
      + '<td class="role-title">' + esc(role.title)
        + (role.eligibility_note ? '<span class="elig">' + esc(role.eligibility_note) + "</span>" : "")
      + "</td>"
      + '<td><span class="rt" data-t="' + esc(role.role_type) + '">' + esc(role.role_type) + "</span></td>"
      + '<td><span class="tier" data-tier="' + esc(role.tier) + '">T' + esc(role.tier) + "</span></td>"
      + '<td class="loc">' + locHTML(role) + "</td>"
      + '<td class="' + compCls + '">' + compInner + "</td>"
      + '<td class="' + multiCls + '">' + esc(role.multi_apply || "unknown") + "</td>"
      + "<td>" + applyBtn + "</td>"
      + '<td><button class="done" type="button" aria-pressed="' + (isApplied ? "true" : "false")
        + '" data-id="' + esc(role.id) + '">' + (isApplied ? "✓ done" : "mark") + "</button></td>"
      + "</tr>";
  }

  function render() {
    var list = ROLES.filter(matches);
    var keyFn = SORTS[state.sort] || priority;
    list = list.slice().sort(function (a, b) { return cmp(keyFn(a), keyFn(b)) * state.dir; });

    tbody.innerHTML = list.map(rowHTML).join("");
    empty.hidden = list.length > 0;

    tally.textContent = list.length;
    var appliedCount = ROLES.filter(function (r) { return applied.has(r.id); }).length;
    tallyLabel.textContent = appliedCount
      ? "shown · " + appliedCount + " applied"
      : "roles shown";

    $$("thead th[data-sort]").forEach(function (th) {
      if (th.dataset.sort === state.sort) th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
  }

  /* ── events ────────────────────────────────────────────────── */
  $$(".chip[data-type]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var v = btn.dataset.type;
      if (state.types.has(v)) state.types.delete(v); else state.types.add(v);
      btn.setAttribute("aria-pressed", state.types.has(v) ? "true" : "false");
      render();
    });
  });

  $$(".chip[data-loc]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var v = btn.dataset.loc;
      if (state.locs.has(v)) state.locs.delete(v); else state.locs.add(v);
      btn.setAttribute("aria-pressed", state.locs.has(v) ? "true" : "false");
      render();
    });
  });

  $$(".chip[data-status]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var v = btn.dataset.status;
      if (state.statuses.has(v)) state.statuses.delete(v); else state.statuses.add(v);
      btn.setAttribute("aria-pressed", state.statuses.has(v) ? "true" : "false");
      render();
    });
  });

  var hideBtn = $("#hide-applied");
  hideBtn.addEventListener("click", function () {
    state.hideApplied = !state.hideApplied;
    hideBtn.setAttribute("aria-pressed", state.hideApplied ? "true" : "false");
    render();
  });

  var search = $("#search");
  search.addEventListener("input", function () {
    state.q = search.value.trim().toLowerCase();
    render();
  });

  $("#reset").addEventListener("click", function () {
    state.types.clear(); state.locs.clear(); state.statuses.clear();
    state.q = ""; state.hideApplied = false;
    state.sort = "priority"; state.dir = 1;
    search.value = "";
    $$(".chip").forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
    render();
  });

  $$("thead th[data-sort]").forEach(function (th) {
    th.addEventListener("click", function () {
      var s = th.dataset.sort;
      if (state.sort === s) state.dir = -state.dir;
      else { state.sort = s; state.dir = 1; }
      render();
    });
  });

  tbody.addEventListener("click", function (e) {
    var btn = e.target.closest(".done");
    if (!btn) return;
    var id = btn.dataset.id;
    if (applied.has(id)) applied.delete(id); else applied.add(id);
    persistApplied();
    render();
  });

  /* ── theme ─────────────────────────────────────────────────── */
  var toggle = $(".theme-toggle");
  function paintToggle() {
    var dark = document.documentElement.dataset.theme === "dark";
    toggle.textContent = dark ? "◑ light" : "◐ dark";
    toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  toggle.addEventListener("click", function () {
    var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
    paintToggle();
  });
  paintToggle();

  /* ── sticky offset ─────────────────────────────────────────── */
  // The controls bar is sticky at top:0 and wraps to two rows on narrow
  // screens, so the table head has to be told where it actually ends.
  var controls = $(".controls");
  function syncStickyOffset() {
    // getBoundingClientRect keeps the sub-pixel height; offsetHeight rounds it
    // down and leaves a sliver of row visible above the sticky header.
    var h = controls && getComputedStyle(controls).position === "sticky"
      ? Math.ceil(controls.getBoundingClientRect().height)
      : 0;
    document.documentElement.style.setProperty("--controls-h", h + "px");
  }
  syncStickyOffset();
  window.addEventListener("resize", syncStickyOffset);

  /* ── keyboard ──────────────────────────────────────────────── */
  document.addEventListener("keydown", function (e) {
    if (e.target.matches("input, textarea")) {
      if (e.key === "Escape") { search.value = ""; state.q = ""; render(); search.blur(); }
      return;
    }
    if (e.key === "/") { e.preventDefault(); search.focus(); return; }
    var map = { "1": "QT", "2": "QR", "3": "QD" };
    if (map[e.key]) {
      var v = map[e.key];
      if (state.types.has(v)) state.types.delete(v); else state.types.add(v);
      var btn = $('.chip[data-type="' + v + '"]');
      if (btn) btn.setAttribute("aria-pressed", state.types.has(v) ? "true" : "false");
      render();
    }
    if (e.key === "0") { $("#reset").click(); }
  });

  render();
})();
