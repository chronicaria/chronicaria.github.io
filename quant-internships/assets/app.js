/* ─────────────────────────────────────────────────────────────
   app.js — one IIFE, no dependencies.

   Reads FIRMS from data.js and renders ONE TABLE ROW PER ROLE.
   The table is the whole point of the file: 145 roles have to be
   scannable in a couple of screens, so everything that is not a
   glanceable column — the verbatim eligibility window, the pay
   string in full, the firm's application-limit policy, the
   interview process — lives in a drawer that opens under the row.

   Firm grouping survives the flattening: roles from one firm stay
   adjacent, and only the first row of a run prints the grade and
   the firm name. That matters because the one-application policies
   are a FIRM-level fact, so the roles competing for a single slot
   still have to be read together.

   Owns six pieces of state — role type, category, grade, location,
   free text, and the applied set (localStorage) — plus the Andrew
   mode flag, which changes the sort key and reveals the fit column.

   Nothing here talks to the network.
   ───────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  var THEME_KEY = "quant-internships-theme";
  var APPLIED_KEY = "quant-internships-applied";
  var ANDREW_KEY = "quant-internships-andrew";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ── fit model ─────────────────────────────────────────────────
     The one place the candidate-specific judgement lives. Every
     number below is a weight on something that is actually on the
     résumé, so changing the résumé means changing this table and
     nothing else.

     Résumé this is scored against: Duke BS Math + BS CS, May 2028,
     GPA 3.96, graduate measure theory / real analysis / advanced
     probability / numerical linear algebra / mathematical finance /
     financial derivatives. Daily-RAPM basketball valuation model over
     49M possessions benchmarked against EPM/RAPTOR/DARKO. Julia PDE
     library for flow on deformed surfaces, manuscript in progress.
     Real-money Polymarket/Kalshi book across four cycles, fractional
     Kelly, hedged across race types. County-level degree-day option
     pricing engine. Founder of a collegiate poker club.
     ───────────────────────────────────────────────────────────── */
  // The grade spread has to exceed the total tag spread, or a topical match at
  // a mid-tier shop outranks a top-tier seat — an early version had Castleton
  // Commodities above every S firm because weather+commodities (18) beat the
  // S-to-B gap (9). Grade dominates; tags break ties inside a tier.
  var GRADE_PTS = { S: 34, A: 26, B: 16, C: 8, D: 3, F: -999 };
  var TYPE_PTS = { QR: 18, QT: 12, QD: 5 };
  var TAG_CAP = 16;

  var TAG_PTS = {
    "event-markets": 14,
    "sports": 12,
    "weather": 12,
    "ml": 8,
    "vol": 7,
    "numerics": 7,
    "commodities": 6,
    "games": 5,
    "stats": 5,
    "options": 4,
    "cpp": 4,
    "microstructure": 3
  };

  var TAG_WHY = {
    "event-markets": "four cycles of real-money Polymarket/Kalshi, Kelly-sized",
    "sports": "DataBallR — daily RAPM over 49M possessions",
    "weather": "county-level degree-day pricing engine",
    "ml": "XGBoost and scikit-learn on the valuation model",
    "vol": "Financial Derivatives coursework",
    "numerics": "4,500-line Julia PDE library, matrix-free solvers",
    "commodities": "weather-derivatives work reads straight across",
    "games": "founded and ran the Duke poker club",
    "stats": "graduate Advanced Probability and Measure & Integration",
    "options": "Financial Derivatives, and the options side of the vol work",
    "cpp": "C++ alongside Python and Julia",
    "microstructure": "market-price divergence work on prediction markets"
  };

  function fitOf(role, firm) {
    var parts = [];
    var n = 0;

    function add(pts, why) {
      if (!pts) return;
      n += pts;
      parts.push({ pts: pts, why: why });
    }

    add(GRADE_PTS[firm.grade] || 0, "grade " + firm.grade);
    add(TYPE_PTS[role.role_type] || 0,
      role.role_type === "QR" ? "research is the long-run career"
        : role.role_type === "QT" ? "trading — the fallback lane"
        : "development — third preference");

    // Tags are scored together and capped, best first, so a role carrying four
    // niche matches cannot out-earn a whole grade tier.
    var budget = TAG_CAP;
    (role.tags || []).slice()
      .sort(function (a, b) { return (TAG_PTS[b] || 0) - (TAG_PTS[a] || 0); })
      .forEach(function (t) {
        var pts = Math.min(TAG_PTS[t] || 0, budget);
        if (pts <= 0) return;
        budget -= pts;
        add(pts, TAG_WHY[t] || t);
      });

    if (role.undergrad_explicit) add(6, "posting names undergraduates explicitly");
    if (role.class_2028 === true) add(4, "graduation window contains May 2028");
    if (role.locations.some(function (l) { return /new york|nyc/i.test(l); })) add(4, "New York — home");
    else if (role.locations.some(function (l) { return /chicago/i.test(l); })) add(1, "Chicago");
    if (firm.one_only) add(-3, "costs the firm's single application");
    if (role.status === "soon") add(-2, "not open yet");
    if (role.closed) add(-40, "applications closed");

    return { score: Math.max(0, Math.min(99, n)), parts: parts };
  }

  /* ── flatten ───────────────────────────────────────────────── */
  var ALL = [];
  FIRMS.forEach(function (firm, fi) {
    firm._i = fi;
    (firm.roles || []).forEach(function (role, ri) {
      role._firm = firm;
      role._i = ri;
      role.locations = role.locations || [];
      var f = fitOf(role, firm);
      role._fit = f.score;
      role._why = f.parts;
      ALL.push(role);
    });
  });

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
  var andrew = true;
  try {
    var stored = localStorage.getItem(ANDREW_KEY);
    if (stored !== null) andrew = stored === "1";
  } catch (e) { /* ignore */ }

  var state = {
    types: new Set(),      // empty = all
    cats: new Set(),
    grades: new Set(),
    locs: new Set(),
    statuses: new Set(),
    q: "",
    hideApplied: false,
    onlyOneOnly: false,
    onlyDeadline: false,
    sort: andrew ? "fit" : "grade",
    dir: 1
  };

  var GRADE_RANK = { S: 0, A: 1, B: 2, C: 3, D: 4, F: 5 };
  var TYPE_RANK_ANDREW = { QR: 0, QT: 1, QD: 2 };
  var TYPE_RANK_PLAIN = { QT: 0, QR: 1, QD: 2 };

  function typeRank(t) {
    var m = andrew ? TYPE_RANK_ANDREW : TYPE_RANK_PLAIN;
    return m[t] === undefined ? 9 : m[t];
  }

  function isNYC(role) {
    return role.locations.some(function (l) { return /new york|nyc/i.test(l); });
  }

  function locBucket(role) {
    if (isNYC(role)) return "NYC";
    if (role.locations.some(function (l) { return /chicago/i.test(l); })) return "Chicago";
    if (role.locations.some(function (l) { return /boston|greenwich|stamford|conn|philadelphia|bala/i.test(l); })) return "Northeast";
    if (role.locations.some(function (l) { return /austin|houston|dallas|miami|jupiter|palm beach|charlotte|atlanta/i.test(l); })) return "South";
    if (role.locations.some(function (l) { return /san francisco|palo alto|menlo|seattle|los angeles|newport|denver|boulder/i.test(l); })) return "West";
    return "Other";
  }

  /* ── filtering ─────────────────────────────────────────────── */
  // The interview panels are the densest text on the page, so search has to reach
  // them — "market making game", "superday", "HackerRank" and "8-month cooldown"
  // are exactly the queries this board should answer. Built once per firm and
  // cached on the object; it never changes.
  function firmHaystack(firm) {
    var d = firm.intel || {};
    var bits = [firm.name, firm.note || "", firm.policy || "", firm.reputation || "",
                firm.firm_type || "", firm.oa || "", firm.cooldown || "",
                d.summary || "", d.oa || "", d.difficulty || "", d.caveat || "",
                (d.topics || []).join(" "), (d.sample_questions || []).join(" "),
                (d.tips || []).join(" ")];
    (d.rounds || []).forEach(function (r) {
      bits.push(r.stage || "", r.format || "", r.content || "");
    });
    return bits.join(" ").toLowerCase();
  }

  function roleMatches(role) {
    var firm = role._firm;
    if (state.types.size && !state.types.has(role.role_type)) return false;
    if (state.cats.size && !state.cats.has(firm.category)) return false;
    if (state.grades.size && !state.grades.has(firm.grade)) return false;
    if (state.locs.size && !state.locs.has(locBucket(role))) return false;
    if (state.statuses.size && !state.statuses.has(role.status || "open")) return false;
    if (state.hideApplied && applied.has(role.id)) return false;
    if (state.onlyOneOnly && !firm.one_only) return false;
    if (state.onlyDeadline && !role.deadline) return false;
    // Andrew mode hides the warning bucket, but asking for F explicitly wins —
    // otherwise the F chip would silently return nothing.
    if (andrew && firm.grade === "F" && !state.grades.has("F")) return false;
    if (state.q) {
      if (firm._hay === undefined) firm._hay = firmHaystack(firm);
      var hay = firm._hay + " " + [role.title, role.role_type, role.locations.join(" "),
                 role.notes || "", role.comp || "", role.eligibility_note || "",
                 (role.tags || []).join(" ")].join(" ").toLowerCase();
      if (hay.indexOf(state.q) === -1) return false;
    }
    return true;
  }

  /* ── sorting ───────────────────────────────────────────────── */
  function roleKey(role) {
    // Inside a firm run, Andrew mode puts QR first; otherwise best fit wins anyway.
    return [typeRank(role.role_type), -(role._fit || 0), role._i];
  }

  var GROUP_SORTS = {
    fit: function (g) { return [-g.top, GRADE_RANK[g.firm.grade], g.firm.name.toLowerCase()]; },
    grade: function (g) { return [GRADE_RANK[g.firm.grade] === undefined ? 9 : GRADE_RANK[g.firm.grade], -g.top, g.firm.name.toLowerCase()]; },
    firm: function (g) { return [g.firm.name.toLowerCase()]; },
    comp: function (g) { return [-(g.pay == null ? -1 : g.pay), g.firm.name.toLowerCase()]; },
    deadline: function (g) { return [g.deadline || "9999", g.firm.name.toLowerCase()]; }
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

  /* ── render ────────────────────────────────────────────────── */
  var rows = $("#rows");
  var board = $("#board");
  var empty = $("#empty");
  var tally = $("#tally-n");
  var tallyLabel = $("#tally-label");
  var summary = $("#summary");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function visibleCols() {
    return $$("#board thead th").filter(function (th) {
      return getComputedStyle(th).display !== "none";
    }).length || 7;
  }

  var CATS = {
    mm: "market maker",
    multistrat: "multistrat fund",
    am: "quant asset manager",
    bank: "bank / sell-side",
    crypto: "digital assets",
    event: "event & sports",
    energy: "energy & commodities",
    boutique: "boutique",
    exchange: "exchange / venue",
    adjacent: "quant-adjacent"
  };

  /* ── column compression ────────────────────────────────────────
     Pay strings run to 70 characters ("$4,900/week (Bachelor's),
     $5,000/week (Master's), $5,500/week (PhD); 10 weeks…"), which is
     the single widest thing on the board. The column shows the lead
     figure and its period; the drawer keeps the string verbatim, and
     a trailing + says there is more to read.
     ───────────────────────────────────────────────────────────── */
  // A period only counts when it is written as a RATE — "/week", "per week",
  // "a week", "weekly". A bare noun does not: "$71,000 total for the 8-week
  // internship" and "$50,000 for 10 weeks" both name a whole-internship figure,
  // and an earlier version of this turned them into $71,000/wk and $50,000/wk.
  var PERIODS = [[/(?:\/\s*|per\s+|an?\s+)h(?:ou)?r\b|hourly/i, "/hr"],
                 [/(?:\/\s*|per\s+|a\s+)week\b|weekly/i, "/wk"],
                 [/(?:\/\s*|per\s+|a\s+)month\b|monthly/i, "/mo"],
                 [/annual|(?:\/\s*|per\s+|a\s+)(?:year|yr)\b|yearly/i, "/yr"]];

  // "to" is a range separator as often as an en-dash on these postings, and a
  // trailing k ("$110k - $120k") has to survive.
  var MONEY = /\$\s?[\d,]*\d(?:\.\d+)?k?(?:\s*(?:[-–—]|to)\s*\$?\s?[\d,]*\d(?:\.\d+)?k?)?/i;
  var BARE_USD = /[\d,]*\d(?:\.\d+)?\s*USD/i;   // "weekly base salary of 5,800 USD"

  function compShort(s) {
    if (!s) return "";
    var fig = s.match(MONEY), bare = false;
    if (!fig) { fig = s.match(BARE_USD); bare = !!fig; }
    if (!fig) return s.length > 16 ? s.slice(0, 15) + "…" : s;
    var num = (bare ? "$" : "") + fig[0]
      .replace(/\s*USD/i, "").replace(/\s+/g, "").replace(/-|—|to/i, "–");
    // Nearest period to the figure wins — "Annual Base Salary: $300,000" has its
    // unit before the number, "$25,000/month base" after it, and "$25 per hour
    // for 40 hours per week" has both.
    var best = "", bestD = 1e9;
    PERIODS.forEach(function (p) {
      var m = s.match(p[0]);
      if (!m) return;
      var d = Math.abs(m.index - fig.index);
      if (d < bestD) { bestD = d; best = p[1]; }
    });
    return num + best;
  }

  // Heuristic, and deliberately slack: a "+" that fires on "$300,000 annualized
  // base" — where the drawer adds nothing — trains the reader to ignore it.
  function compTruncated(role) {
    return !!role.comp && role.comp.trim().length > compShort(role.comp).length + 10;
  }

  /* Self-check. ?selftest in the URL asserts the pay compressor against the
     cases that have actually gone wrong, then reports over the live data.
     A wrong period on a pay figure is the one error on this page that would
     change where someone applies. */
  function selftest() {
    var cases = [
      ["$71,000 total for the 8-week internship including a sign-on bonus", "$71,000"],
      ["$50,000 for 10 weeks, plus a $10,000 housing stipend", "$50,000"],
      ["$2,250 for the one-week program", "$2,250"],
      ["Annual Base Salary: $300,000, plus sign-on bonus", "$300,000/yr"],
      ["$4,500 to $5,800 per week", "$4,500–$5,800/wk"],
      ["$110k - $120k", "$110k–$120k"],
      ["$25 per hour for 40 hours per week", "$25/hr"],
      ["New York: weekly base salary of 5,800 USD, plus signing bonus", "$5,800/wk"],
      ["$4,900/week (Bachelor's), $5,000/week (Master's)", "$4,900/wk"],
      ["$72.12/hr for the Quantitative Researcher Intern role", "$72.12/hr"],
      ["$25,000/month base + $25,000 sign-on", "$25,000/mo"],
      ["$300,000 base salary", "$300,000"],
      ["", ""]
    ];
    var bad = cases.filter(function (c) { return compShort(c[0]) !== c[1]; });
    bad.forEach(function (c) {
      console.error("compShort FAIL", JSON.stringify(c[0]), "→", JSON.stringify(compShort(c[0])),
        "expected", JSON.stringify(c[1]));
    });
    console.log(bad.length ? bad.length + " compShort failures" : "compShort: " + cases.length + " ok");
    console.log("live pay strings:\n" + ALL.filter(function (r) { return r.comp; })
      .map(function (r) { return compShort(r.comp).padEnd(22) + "  ⟵  " + r.comp; }).join("\n"));
  }
  if (location.search.indexOf("selftest") > -1) selftest();

  function locShort(role) {
    var l = role.locations;
    if (!l.length) return '<span class="unknown">—</span>';
    var first = /new york|nyc/i.test(l[0])
      ? '<span class="nyc">' + esc(l[0].replace(/,\s*NY$/, "")) + "</span>"
      : esc(l[0].replace(/,\s*[A-Z]{2}$/, ""));
    return first + (l.length > 1 ? '<span class="more">+' + (l.length - 1) + "</span>" : "");
  }

  /* role.notes doubles as the maintainer's changelog — 28 of 123 open with
     "Re-verified — still live, comp unchanged.", "NEW ROW.", "URL CAVEAT - READ
     THIS:" or similar. Those are bookkeeping addressed to whoever maintains the
     board, not to someone deciding where to apply. Strip the marker and keep
     whatever it was prefixed to, which is usually the real note; drop the row
     entirely when nothing substantial survives. The full string stays in
     data.js and stays searchable — this only governs what is printed. */
  var MAINT_MARKER = /^\s*(?:re-?verified\b[^.]*\.|new row\b[^.]*\.|dedupe before publishing\.?|caveat the maintainer should keep:|url caveat\s*[-–—]\s*read this:|classification call:)\s*/i;

  function candidateNote(s) {
    var t = String(s || ""), prev;
    do { prev = t; t = t.replace(MAINT_MARKER, ""); } while (t !== prev);
    t = t.trim();
    return t.length > 15 ? t : "";
  }

  // 35 of 65 firms carry a policy that states nothing — "Not stated", "No limit
  // stated", "No restriction stated" — and each was rendering a labelled row in
  // the drawer of every one of that firm's roles. The 8 firms with a genuine cap
  // are already flagged by the 1× chip on the row itself.
  function realPolicy(p) {
    return p && !/^(not stated|none stated|no restriction|no limit|no stated)/i.test(p) ? p : "";
  }

  function whyHTML(role) {
    // Only the positive drivers, best first, capped at three — the rail is a
    // nudge, not an audit trail. Negatives show up as a lower score already.
    var top = (role._why || []).filter(function (p) { return p.pts > 0; })
      .sort(function (a, b) { return b.pts - a.pts; })
      .slice(0, 3);
    var neg = (role._why || []).filter(function (p) { return p.pts < 0; });
    var bits = top.map(function (p) { return esc(p.why); });
    if (neg.length) bits.push('<span class="cost">' + esc(neg[0].why) + "</span>");
    return bits.join(" · ");
  }

  /* ── the row ───────────────────────────────────────────────── */
  function rowHTML(role, isFirst) {
    var firm = role._firm;
    var isApplied = applied.has(role.id);
    var open = openRows.has(role.id);

    var applyBtn;
    if (role.closed) {
      applyBtn = '<span class="apply closed" aria-disabled="true">Closed</span>';
    } else if (role.status === "soon") {
      var opensTxt = role.opens || "Opens soon";
      applyBtn = role.apply_url
        ? '<a class="apply soon" href="' + esc(role.apply_url) + '" target="_blank" rel="noopener" title="'
          + esc(opensTxt) + '">Soon</a>'
        : '<span class="apply soon" aria-disabled="true" title="' + esc(opensTxt) + '">Soon</span>';
    } else if (role.apply_url) {
      applyBtn = '<a class="apply" href="' + esc(role.apply_url) + '" target="_blank" rel="noopener">Apply</a>';
    } else {
      applyBtn = '<span class="apply" aria-disabled="true">No link</span>';
    }

    var cls = "r" + (isFirst ? " grp-first" : "") + (open ? " is-open" : "")
      + (isApplied ? " is-applied" : "") + (role.status === "soon" ? " is-soon" : "")
      + (role.closed ? " is-closed" : "");

    return '<tr class="' + cls + '" data-id="' + esc(role.id) + '">'
      + '<td class="c-grade">' + (isFirst
          ? '<span class="grade" data-g="' + esc(firm.grade) + '">' + esc(firm.grade) + "</span>" : "")
      + "</td>"
      + '<td class="c-firm">' + (isFirst
          ? '<span class="fname">' + esc(firm.name) + "</span>"
            + (firm.one_only ? '<span class="one" title="' + esc(firm.policy || "one application only")
                + '">1&times;</span>' : "")
          : "")
      + "</td>"
      // The deadline sits before the title, not after it: the title cell
      // truncates with an ellipsis and a due date that scrolls off the end is
      // the one thing on the row that must never be lost.
      + '<td class="c-role" title="' + esc(role.title) + '">'
        + '<span class="chev" aria-hidden="true">▸</span>'
        + '<span class="rt" data-t="' + esc(role.role_type) + '">' + esc(role.role_type) + "</span>"
        // ISO only. data.js used to carry whole sentences in this field
        // ("Posting states 'Anticipated Posting Close Date: Dec 29, 2025' — that
        // date is in the PAST…"), which both broke the deadline sort and pushed
        // the role title clean off the row. The prose lives in deadline_note now.
        + (/^\d{4}-\d{2}-\d{2}$/.test(role.deadline || "")
            ? '<span class="deadline">' + esc(role.deadline) + "</span>" : "")
        + '<span class="rtitle">' + esc(role.title) + "</span>"
      + "</td>"
      + '<td class="c-loc">' + locShort(role) + "</td>"
      + '<td class="c-pay">' + (role.comp
          ? '<span class="n" data-src="' + esc(role.comp_source || "") + '" title="' + esc(role.comp) + '">'
            + esc(compShort(role.comp)) + (compTruncated(role) ? '<span class="plus">+</span>' : "") + "</span>"
          : '<span class="unknown">—</span>')
      + "</td>"
      + '<td class="c-fit">' + (andrew ? '<span class="fit-n">' + role._fit + "</span>" : "") + "</td>"
      + '<td class="c-act">' + applyBtn
        + '<button class="done" type="button" aria-pressed="' + (isApplied ? "true" : "false")
        + '" data-id="' + esc(role.id) + '" aria-label="Mark applied">'
        + (isApplied ? "✓" : "○") + "</button>"
      + "</td>"
      + "</tr>"
      + (open ? drawerHTML(role) : "");
  }

  /* ── the drawer ────────────────────────────────────────────────
     Everything that used to be printed under every role and made the
     page unscrollable: the verbatim eligibility window, the pay string
     in full, the firm's policy and assessment, and the interview panel.
     Built only for rows that are actually open, so the closed board
     costs nothing.
     ───────────────────────────────────────────────────────────── */
  function drawerHTML(role) {
    var firm = role._firm;
    // The row truncates the title — with an ellipsis on desktop, a two-line clamp
    // on a phone — so the drawer has to state it in full, with the firm, or the
    // longest titles are simply unreadable.
    var bits = '<p class="dw-title">' + esc(firm.name) + " &middot; " + esc(role.title) + "</p>";

    if (andrew && role._why && role._why.length)
      bits += '<p class="why">' + whyHTML(role) + "</p>";

    if (role.eligibility_note)
      bits += '<div class="dw-b"><span class="label">Eligibility, as posted</span><p class="elig">'
        + esc(role.eligibility_note) + "</p></div>";

    var note = candidateNote(role.notes);
    if (note)
      bits += '<div class="dw-b"><span class="label">Note</span><p>' + esc(note) + "</p></div>";

    var facts = [];
    if (role.comp)
      facts.push("<span><b>Pay</b> " + esc(role.comp)
        + (role.comp_source ? ' <i class="src">(' + esc(role.comp_source) + ")</i>" : "") + "</span>");
    if (role.locations.length > 1)
      facts.push("<span><b>Locations</b> " + esc(role.locations.join(" · ")) + "</span>");
    if (role.status === "soon" && role.opens)
      facts.push("<span><b>Opens</b> " + esc(role.opens) + "</span>");
    if (role.deadline_note)
      facts.push("<span><b>Closing</b> " + esc(role.deadline_note) + "</span>");
    if (facts.length) bits += '<p class="dw-facts">' + facts.join("") + "</p>";

    // The firm-level block. Repeated in every row of a firm run on purpose:
    // a drawer has to be readable without scrolling back to the firm's first row.
    var fb = '<span><b>' + esc(CATS[firm.category] || firm.category) + "</b></span>";
    var pol = realPolicy(firm.policy);
    if (pol)
      fb += '<span class="' + (firm.one_only ? "one-only" : "") + '"><b>Applications</b> '
        + esc(pol) + "</span>";
    if (firm.cooldown) fb += '<span class="cool"><b>Cooldown</b> ' + esc(firm.cooldown) + "</span>";
    // firm.oa is set on 8 firms and all 8 also carry intel.oa, which the panel
    // below prints under "The assessment". Only show it when the panel will not.
    if (firm.oa && !(firm.intel && firm.intel.oa))
      fb += "<span><b>Assessment</b> " + esc(firm.oa) + "</span>";
    bits += '<p class="dw-firm">' + fb + "</p>";

    if (firm.note) bits += '<p class="dw-note">' + esc(firm.note) + "</p>";

    // When one application is all you get, the competing roles have to be
    // adjacent and the call has to be made here.
    var pick = "";
    if (andrew && firm.pick) {
      // Hand-written where the rule is too nuanced to compute — Akuna's two
      // firewalled families, Millennium's degree split across its two slots.
      pick = esc(firm.pick);
    } else if (andrew && firm.one_only && (firm.roles || []).length > 1) {
      var ranked = firm.roles.slice().sort(function (a, b) { return b._fit - a._fit; });
      pick = ranked.slice(0, firm.cap || 1).map(function (r) {
        return '<span class="rt" data-t="' + esc(r.role_type) + '">' + esc(r.role_type) + "</span> "
          + esc(r.title);
      }).join(" &nbsp;·&nbsp; ");
    }
    if (pick)
      bits += '<p class="pick"><span class="label">'
        + ((firm.cap || 1) > 1 ? "spend them on" : "spend it on") + "</span>" + pick + "</p>";

    bits += intelHTML(firm);

    // Derived, not literal: the visible column count changes with Andrew mode
    // and with two responsive breakpoints, and a hand-maintained 7 was already
    // wrong with Andrew mode off.
    return '<tr class="d" data-for="' + esc(role.id) + '"><td colspan="' + visibleCols() + '">'
      + '<div class="dw">' + bits + "</div></td></tr>";
  }

  /* ── interview intel ───────────────────────────────────────────
     A native <details> nested inside the drawer. No JS toggle, no ARIA
     to get wrong. render() replaces innerHTML, so the open set is
     tracked below and reapplied.
     ───────────────────────────────────────────────────────────── */
  var openIntel = new Set();
  var openRows = new Set();

  function listHTML(cls, items, limit) {
    if (!items || !items.length) return "";
    return '<ul class="' + cls + '">'
      + items.slice(0, limit || 99).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("")
      + "</ul>";
  }

  function intelHTML(firm) {
    var d = firm.intel;
    if (!d && !firm.reputation) return "";
    d = d || {};
    var isOpen = openIntel.has(firm.key);

    var rounds = (d.rounds || []).map(function (r) {
      return "<li>"
        + '<span class="stage">' + esc(r.stage) + "</span>"
        + (r.format ? '<span class="fmt">' + esc(r.format) + "</span>" : "")
        + "<p>" + esc(r.content) + "</p>"
        + "</li>";
    }).join("");

    var blocks = "";
    if (d.oa) blocks += '<div class="ib"><span class="label">The assessment</span><p>' + esc(d.oa) + "</p></div>";
    if (d.topics && d.topics.length)
      blocks += '<div class="ib"><span class="label">What to study</span>' + listHTML("topics", d.topics, 8) + "</div>";
    if (d.sample_questions && d.sample_questions.length)
      blocks += '<div class="ib"><span class="label">Reported question types</span>'
        + listHTML("qs", d.sample_questions, 8) + "</div>";
    if (d.tips && d.tips.length)
      blocks += '<div class="ib"><span class="label">What candidates say they got wrong</span>'
        + listHTML("tips", d.tips, 6) + "</div>";
    // Claims a second pass went looking for and could not find. Shown rather than
    // silently deleted — knowing a number is unsupported is worth as much as the number.
    if (d.unverified && d.unverified.length)
      blocks += '<div class="ib unver"><span class="label">Could not be corroborated</span>'
        + listHTML("unv", d.unverified, 7) + "</div>";

    var meta = [];
    if (d.timeline) meta.push("<span><b>Timeline</b> " + esc(d.timeline) + "</span>");
    if (d.difficulty) meta.push("<span><b>Difficulty</b> " + esc(d.difficulty) + "</span>");

    var srcs = (d.sources || []).filter(function (s) { return s && s.url; }).map(function (s) {
      return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener nofollow">'
        + esc(s.label || "source") + (s.year ? " (" + esc(s.year) + ")" : "") + "</a>";
    }).join(" · ");

    // Suppress the round-count badge when the count itself is one of the claims a
    // verification pass could not corroborate — the badge is the most glanceable
    // thing here and must not assert what the body below it retracts.
    var countDisputed = (d.unverified || []).some(function (u) { return /round/i.test(u); });

    return '<details class="intel" data-firm="' + esc(firm.key) + '"' + (isOpen ? " open" : "") + ">"
      + "<summary>"
        + '<span class="label">Interview process</span>'
        + (d.rounds && d.rounds.length && !countDisputed
            ? '<span class="nrounds">' + d.rounds.length + " rounds</span>"
            : (d.rounds && d.rounds.length ? '<span class="nrounds">stages below</span>' : ""))
        + '<span class="conf" data-c="' + esc(d.confidence || "low") + '">'
          + esc(d.confidence || "low") + " confidence</span>"
      + "</summary>"
      + '<div class="intel-body">'
        + (d.summary ? '<p class="intel-sum">' + esc(d.summary) + "</p>" : "")
        + (rounds ? '<ol class="rounds">' + rounds + "</ol>" : "")
        + blocks
        + (firm.reputation
            ? '<div class="ib rep"><span class="label">What the community says</span><p>'
              + esc(firm.reputation) + "</p></div>"
            : "")
        + (firm.firm_type
            ? '<p class="ftype"><span class="label">Firm type</span>' + esc(firm.firm_type)
              + (firm.headcount ? " · " + esc(firm.headcount) : "") + "</p>"
            : "")
        + (meta.length ? '<p class="imeta">' + meta.join("") + "</p>" : "")
        + (d.caveat ? '<p class="caveat">' + esc(d.caveat) + "</p>" : "")
        + (srcs ? '<p class="srcs"><span class="label">Reported by</span>' + srcs + "</p>" : "")
        + '<p class="disclaimer">Community reports, not the firm’s own description. '
          + "Formats change between cycles — treat this as a prior, not a promise.</p>"
      + "</div></details>";
  }

  function render() {
    var kept = ALL.filter(roleMatches);

    // Regroup the surviving roles under their firms, preserving firm order.
    var byFirm = {};
    var groups = [];
    kept.forEach(function (role) {
      var f = role._firm;
      if (!byFirm[f.key]) {
        byFirm[f.key] = { firm: f, roles: [], top: 0, pay: null, deadline: "" };
        groups.push(byFirm[f.key]);
      }
      var g = byFirm[f.key];
      g.roles.push(role);
      if (role._fit > g.top) g.top = role._fit;
      if (role.comp_rank != null && (g.pay == null || role.comp_rank > g.pay)) g.pay = role.comp_rank;
      if (role.deadline && (!g.deadline || role.deadline < g.deadline)) g.deadline = role.deadline;
    });

    groups.forEach(function (g) {
      g.roles.sort(function (a, b) { return cmp(roleKey(a), roleKey(b)); });
    });

    var keyFn = GROUP_SORTS[state.sort] || GROUP_SORTS.grade;
    groups.sort(function (a, b) { return cmp(keyFn(a), keyFn(b)) * state.dir; });

    rows.innerHTML = groups.map(function (g) {
      return g.roles.map(function (role, i) { return rowHTML(role, i === 0); }).join("");
    }).join("");

    empty.hidden = groups.length > 0;
    board.hidden = groups.length === 0;

    tally.textContent = kept.length;
    var appliedCount = ALL.filter(function (r) { return applied.has(r.id); }).length;
    tallyLabel.textContent = appliedCount
      ? "roles · " + appliedCount + " applied"
      : "roles at " + groups.length + " firms";

    // Grade + type breakdown of what is currently on screen.
    var byGrade = {}, byType = {};
    kept.forEach(function (r) {
      byGrade[r._firm.grade] = (byGrade[r._firm.grade] || 0) + 1;
      byType[r.role_type] = (byType[r.role_type] || 0) + 1;
    });
    var gBits = ["S", "A", "B", "C", "D"].filter(function (g) { return byGrade[g]; })
      .map(function (g) { return '<span class="grade sm" data-g="' + g + '">' + g + "</span>" + byGrade[g]; });
    var tBits = (andrew ? ["QR", "QT", "QD"] : ["QT", "QR", "QD"]).filter(function (t) { return byType[t]; })
      .map(function (t) { return '<span class="rt" data-t="' + t + '">' + t + "</span>" + byType[t]; });
    summary.innerHTML = gBits.join(" ") + '<span class="sep"></span>' + tBits.join(" ");

    $$(".sortbtn").forEach(function (b) {
      var on = b.dataset.sortkey === state.sort;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.dataset.dir = on && state.dir < 0 ? "up" : "down";
    });

    // .summary lives inside the sticky bar and its content changes on every
    // render, so a filter can rewrap the bar and move where the thead must stick.
    syncStickyOffset();
  }

  /* ── events ────────────────────────────────────────────────── */
  function wireChips(sel, key, prop) {
    $$(sel).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var v = btn.dataset[prop];
        if (state[key].has(v)) state[key].delete(v); else state[key].add(v);
        btn.setAttribute("aria-pressed", state[key].has(v) ? "true" : "false");
        render();
      });
    });
  }
  wireChips(".chip[data-type]", "types", "type");
  wireChips(".chip[data-cat]", "cats", "cat");
  wireChips(".chip[data-grade]", "grades", "grade");
  wireChips(".chip[data-loc]", "locs", "loc");
  wireChips(".chip[data-status]", "statuses", "status");

  function wireToggle(id, key) {
    var btn = $(id);
    if (!btn) return;
    btn.addEventListener("click", function () {
      state[key] = !state[key];
      btn.setAttribute("aria-pressed", state[key] ? "true" : "false");
      render();
    });
  }
  wireToggle("#hide-applied", "hideApplied");
  wireToggle("#only-one", "onlyOneOnly");
  wireToggle("#only-deadline", "onlyDeadline");

  // The nine "kind" chips, five locations and five status toggles are a second
  // row that almost nobody needs on arrival. Off by default; the board starts
  // one row shorter and the table starts higher up the screen.
  var moreBtn = $("#more-toggle"), moreRow = $("#more-filters");
  moreBtn.addEventListener("click", function () {
    var on = moreBtn.getAttribute("aria-pressed") !== "true";
    moreBtn.setAttribute("aria-pressed", on ? "true" : "false");
    moreRow.hidden = !on;
    syncStickyOffset();
  });

  var andrewBtn = $("#andrew");
  function paintAndrew() {
    andrewBtn.setAttribute("aria-pressed", andrew ? "true" : "false");
    document.body.classList.toggle("andrew-on", andrew);
  }
  andrewBtn.addEventListener("click", function () {
    andrew = !andrew;
    try { localStorage.setItem(ANDREW_KEY, andrew ? "1" : "0"); } catch (e) { /* ignore */ }
    state.sort = andrew ? "fit" : "grade";
    state.dir = 1;
    paintAndrew();
    render();
  });
  paintAndrew();

  $$(".sortbtn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var s = btn.dataset.sortkey;
      if (state.sort === s) state.dir = -state.dir;
      else { state.sort = s; state.dir = 1; }
      render();
    });
  });

  var search = $("#search");
  search.addEventListener("input", function () {
    state.q = search.value.trim().toLowerCase();
    render();
  });

  $("#reset").addEventListener("click", function () {
    state.types.clear(); state.cats.clear(); state.grades.clear();
    state.locs.clear(); state.statuses.clear();
    state.q = ""; state.hideApplied = false;
    state.onlyOneOnly = false; state.onlyDeadline = false;
    state.sort = andrew ? "fit" : "grade"; state.dir = 1;
    search.value = "";
    openRows.clear();
    $$(".chip").forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
    moreRow.hidden = true;
    render();
  });

  rows.addEventListener("click", function (e) {
    var done = e.target.closest(".done");
    if (done) {
      var id = done.dataset.id;
      if (applied.has(id)) applied.delete(id); else applied.add(id);
      persistApplied();
      render();
      return;
    }
    // Anything inside the open drawer — a source link, the intel disclosure —
    // must not collapse the row out from under the click.
    if (e.target.closest(".apply") || e.target.closest(".d")) return;
    var tr = e.target.closest("tr.r");
    if (!tr) return;
    var rid = tr.dataset.id;
    if (openRows.has(rid)) openRows.delete(rid); else openRows.add(rid);
    render();
  });

  // render() replaces innerHTML, so an expanded <details> would collapse on the
  // next keystroke in the search box. Track the open set and reapply it.
  // "toggle" does not bubble, hence the capture phase.
  rows.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains("intel")) return;
    if (d.open) openIntel.add(d.dataset.firm); else openIntel.delete(d.dataset.firm);
  }, true);

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
  // The controls bar is sticky at top:0 and wraps on narrow screens, and the
  // table head is sticky under it, so both need to be told where it ends.
  var controls = $(".controls");
  function syncStickyOffset() {
    var h = controls && getComputedStyle(controls).position === "sticky"
      ? Math.ceil(controls.getBoundingClientRect().height)
      : 0;
    document.documentElement.style.setProperty("--controls-h", h + "px");
  }
  syncStickyOffset();
  window.addEventListener("resize", syncStickyOffset);
  // Measured before the webfonts swap in, .controls came out 94px against an
  // actual 97px and the sticky thead clipped the top of the first row until
  // something else triggered a resync.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncStickyOffset);

  /* ── keyboard ──────────────────────────────────────────────── */
  document.addEventListener("keydown", function (e) {
    if (e.target.matches("input, textarea")) {
      if (e.key === "Escape") { search.value = ""; state.q = ""; render(); search.blur(); }
      return;
    }
    if (e.key === "/") { e.preventDefault(); search.focus(); return; }
    if (e.key === "a" || e.key === "A") { andrewBtn.click(); return; }
    var map = { "1": "QR", "2": "QT", "3": "QD" };
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
  syncStickyOffset();
})();
