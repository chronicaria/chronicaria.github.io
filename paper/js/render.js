/* The Personal Newspaper — broadsheet edition renderer.
   Plain ES, no framework, no build. Fetches the edition JSON and fills the
   data-np-* mounts, emitting the Contract-B DOM. Helpers el/link/relTime/
   sparkline/longDate/roman are ported from v1 daily.js (restyled, not
   re-themed). Soft-fail throughout: a missing optional field renders nothing,
   never throws. */
(() => {
  "use strict";

  /* ============================================================= *
   *  Constants                                                    *
   * ============================================================= */

  const LOCK = "\u{1F512}\u{FE0E}"; // 🔒 paywall mark, text-presentation (monochrome)
  const MIDDOT = " · "; // · separator

  // Per-desk caps for the capped front page (PLAN §3.1).
  const CAPS = {
    markets: 6, ai: 5, science: 3, world: 4, politics: 3,
    sports: 4, business: 3, ideas: 3, culture: 2,
  };

  // Display order of section fronts on the front page.
  const DESK_ORDER = [
    "markets", "ai", "science", "world", "politics",
    "sports", "business", "ideas", "culture",
  ];

  // Canonical desk key -> display name.
  const DESK_NAMES = {
    markets: "Markets & Finance",
    ai: "AI & Models",
    science: "Science & Mathematics",
    world: "World & Nation",
    politics: "Politics & Elections",
    sports: "Sports",
    business: "Business & Tech",
    ideas: "Ideas & Long-Reads",
    culture: "Culture",
  };

  /* ============================================================= *
   *  Tiny DOM + format helpers (ported from v1 daily.js)          *
   * ============================================================= */

  const $ = (sel, root) => (root || document).querySelector(sel);

  // el(tag, cls, text) — ported verbatim from v1.
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  // link(href, text, cls) — ported verbatim from v1.
  const link = (href, text, cls) => {
    const a = el("a", cls, text);
    a.href = href;
    if (/^https?:/.test(href)) { a.target = "_blank"; a.rel = "noopener"; }
    return a;
  };

  // relTime(iso) — enhanced from v1: adds a same-day clock-time branch.
  //   same calendar day  -> "6:10 a.m." (lower-case a.m./p.m.)
  //   < 48h older        -> "3h ago" / "yesterday"
  //   else               -> "Jun 14"
  const relTime = (iso) => {
    if (!iso) return "";
    const then = new Date(iso);
    if (isNaN(then.getTime())) return "";
    const now = new Date();
    // Same calendar day -> clock time.
    if (
      then.getFullYear() === now.getFullYear() &&
      then.getMonth() === now.getMonth() &&
      then.getDate() === now.getDate()
    ) {
      return clockTime(then);
    }
    const mins = Math.round((now.getTime() - then.getTime()) / 60000);
    if (mins >= 0 && mins < 60) return `${Math.max(mins, 1)}m ago`;
    if (mins >= 0 && mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
    if (mins >= 0 && mins < 60 * 48) return "yesterday";
    return then.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  // Clock time formatted with lower-case a.m./p.m. like "6:10 a.m."
  const clockTime = (d) => {
    const date = d instanceof Date ? d : new Date(d);
    if (isNaN(date.getTime())) return "";
    let h = date.getHours();
    const m = date.getMinutes();
    const mer = h < 12 ? "a.m." : "p.m.";
    h = h % 12;
    if (h === 0) h = 12;
    return `${h}:${String(m).padStart(2, "0")} ${mer}`;
  };

  const NS = "http://www.w3.org/2000/svg";

  // sparkline(values) — ported from v1: an inline SVG sparkline whose class is
  // "spark up"/"spark down" by trend (last vs first).
  const sparkline = (values) => {
    if (!Array.isArray(values) || values.length < 2) return el("span", "spark");
    const up = values[values.length - 1] >= values[0];
    const w = 120, h = 30;
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    const X = (i) => (i / (values.length - 1)) * w;
    const Y = (v) => h - 2 - ((v - min) / span) * (h - 4);
    const pts = values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", `spark ${up ? "up" : "down"}`);
    const area = document.createElementNS(NS, "polygon");
    area.setAttribute("points", `0,${h} ${pts} ${w},${h}`);
    area.setAttribute("class", "fillarea");
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("points", pts);
    line.setAttribute("fill", "none");
    svg.append(area, line);
    return svg;
  };

  // longDate(iso) — ported from v1: "Thursday, June 18, 2026".
  const longDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso + "T12:00:00");
    if (isNaN(d.getTime())) return "";
    return d.toLocaleDateString("en-US", {
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
  };

  // roman(n) — ported from v1: small Roman numerals for the volume folio.
  const roman = (n) => {
    const R = [
      [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"],
      [100, "C"], [90, "XC"], [50, "L"], [40, "XL"],
      [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
    ];
    let out = "";
    for (const [v, s] of R) while (n >= v) { out += s; n -= v; }
    return out || "I";
  };

  const pct = (p) => `${Math.round((p || 0) * 100)}%`;

  /* ============================================================= *
   *  storyEl — the core unit (Contract B.1 / B.2)                 *
   * ============================================================= */

  function storyEl(story, opts) {
    const lead = !!(opts && opts.lead);
    const art = el("article", "story" + (lead ? " story--lead" : ""));
    if (story && story.id) art.id = story.id;
    if (!story) return art;

    // kicker
    if (story.kicker) art.appendChild(el("p", "kicker", story.kicker));

    // headline > a[href] (title), with lock mark when the story is paywalled.
    const h2 = el("h2", "headline " + (lead ? "headline--lead" : "headline--2"));
    const a = link(story.url || "#", story.title || "");
    a.title = story.title || "";
    h2.appendChild(a);
    art.appendChild(h2);

    // deck (omit if empty)
    if (story.deck) art.appendChild(el("p", "deck", story.deck));

    // byline: span.by "By" · BYLINE · span.when relTime(published) · span.alsoin
    art.appendChild(bylineEl(story));

    // summary. The lead gets a multi-column .article-body wrapper whose first
    // paragraph is p.summary.lede (drop cap).
    if (lead) {
      const body = el("div", "article-body");
      if (story.summary) {
        // Drop cap as a real floated span (a ::first-letter float misplaces
        // inside CSS multi-columns); the span anchors to the first column.
        const p = el("p", "summary lede");
        const t = story.summary;
        p.appendChild(el("span", "dropcap", t.charAt(0)));
        p.appendChild(document.createTextNode(t.slice(1)));
        body.appendChild(p);
      }
      art.appendChild(body);
    } else if (story.summary) {
      art.appendChild(el("p", "summary", story.summary));
    }

    return art;
  }

  function bylineEl(story) {
    const p = el("p", "byline");
    p.appendChild(el("span", "by", "By"));
    p.appendChild(document.createTextNode(" "));
    p.appendChild(document.createTextNode((story.byline || "").toUpperCase()));
    // paywall mark sits on the source, not in the headline.
    if (story.paywalled) {
      p.appendChild(document.createTextNode(" "));
      p.appendChild(el("span", "lock", LOCK));
    }

    if (story.published) {
      p.appendChild(document.createTextNode(MIDDOT));
      p.appendChild(el("span", "when", relTime(story.published)));
    }

    // "also: A · B" from sources[1..] when there is more than one source.
    const srcs = Array.isArray(story.sources) ? story.sources : [];
    if (srcs.length > 1) {
      const extras = srcs.slice(1).map((s) => {
        const name = s && s.source ? s.source : "";
        return s && s.paywalled ? name + LOCK : name;
      }).filter(Boolean);
      if (extras.length) {
        p.appendChild(document.createTextNode(" "));
        p.appendChild(el("span", "alsoin", "also: " + extras.join(MIDDOT)));
      }
    }
    return p;
  }

  /* ============================================================= *
   *  Widgets                                                      *
   * ============================================================= */

  // marketTable(rows) — builds table.market from a [QUOTE,…] OR [RATE,…] array.
  // QUOTE rows are detected by the presence of `pct`/`spark`; RATE rows carry
  // `value`/`note`.
  function marketTable(rows) {
    const table = el("table", "market");
    if (!Array.isArray(rows) || !rows.length) return table;
    const isRate = !("pct" in rows[0]) && ("value" in rows[0]);

    const thead = el("thead");
    const htr = el("tr");
    if (isRate) {
      ["", "Rate", "Chg"].forEach((t, i) => {
        const th = el("th", i === 0 ? "label" : "num", t);
        htr.appendChild(th);
      });
    } else {
      ["", "Last", "Chg %", ""].forEach((t, i) => {
        const cls = i === 0 ? "label" : (i === 3 ? "spark-col" : "num");
        htr.appendChild(el("th", cls, t));
      });
    }
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = el("tbody");
    for (const r of rows) {
      const tr = el("tr");
      if (isRate) {
        tr.appendChild(el("td", "label", r.label || ""));
        tr.appendChild(el("td", "num", fmtNum(r.value)));
        const note = r.note || "";
        const dir = /^-/.test(String(note).trim()) ? "down"
          : /^\+/.test(String(note).trim()) ? "up" : "";
        tr.appendChild(el("td", "num note " + dir, note));
      } else {
        tr.appendChild(el("td", "label", r.label || r.sym || ""));
        tr.appendChild(el("td", "num", fmtNum(r.price)));
        const up = (r.pct || 0) >= 0;
        const pctCell = el("td", "num " + (up ? "up" : "down"),
          `${up ? "+" : ""}${fmtNum(r.pct, 2)}%`);
        tr.appendChild(pctCell);
        const sparkCell = el("td", "spark-col");
        sparkCell.appendChild(sparkline(r.spark || []));
        tr.appendChild(sparkCell);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  function fmtNum(v, dp) {
    if (v == null || v === "") return "";
    const n = Number(v);
    if (isNaN(n)) return String(v);
    if (dp != null) return n.toFixed(dp);
    // price-style: thousands separators, up to 2 decimals.
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  // scoreboard(games) — .scoreboard > .game*. Each .game shows league, away@home
  // with scores when Final, or tip time when scheduled.
  function scoreboard(games) {
    const box = el("div", "scoreboard");
    if (!Array.isArray(games)) return box;
    for (const g of games) {
      const game = el("div", "game");
      game.appendChild(el("span", "league", g.league || ""));

      const matchup = el("span", "matchup");
      const isFinal = /final/i.test(g.status || "") || g.hs != null || g.as != null;
      if (isFinal && g.hs != null && g.as != null) {
        // AWAY score @ HOME score
        matchup.appendChild(el("span", "team away", g.away || ""));
        matchup.appendChild(el("span", "score", String(g.as)));
        matchup.appendChild(document.createTextNode(" @ "));
        matchup.appendChild(el("span", "team home", g.home || ""));
        matchup.appendChild(el("span", "score", String(g.hs)));
      } else {
        matchup.appendChild(el("span", "team away", g.away || ""));
        matchup.appendChild(document.createTextNode(" @ "));
        matchup.appendChild(el("span", "team home", g.home || ""));
      }
      game.appendChild(matchup);

      const statusText = isFinal && g.hs != null
        ? (g.status || "Final")
        : (g.tip ? (relTime(g.tip) || clockTime(g.tip)) : (g.status || ""));
      game.appendChild(el("span", "status", statusText));
      box.appendChild(game);
    }
    return box;
  }

  // oddsBar(odds) — .odds-bar from an ODDS object: title + a proportional bar of
  // its outcomes[] with labels and price as percent.
  // Emits the structure newspaper.css styles: .odds-track > .odds-seg(.is-r/.is-d),
  // .odds-legend > .pct, .odds-vol. The percentage sits inside each colored seg.
  const oddsParty = (label) => {
    const l = (label || "").toLowerCase();
    if (l.indexOf("republican") >= 0 || l === "gop" || l === "r") return " is-r";
    if (l.indexOf("democrat") >= 0 || l === "dem" || l === "d") return " is-d";
    return "";
  };

  function oddsBar(odds) {
    const wrap = el("div", "odds-bar");
    if (!odds) return wrap;
    if (odds.title) wrap.appendChild(el("p", "odds-title", odds.title));

    const outcomes = Array.isArray(odds.outcomes) ? odds.outcomes : [];
    if (!outcomes.length) return wrap;
    const total = outcomes.reduce((s, o) => s + (o.price || 0), 0) || 1;

    const track = el("div", "odds-track");
    outcomes.forEach((o) => {
      const seg = el("div", "odds-seg" + oddsParty(o.label), pct(o.price));
      seg.style.width = `${((o.price || 0) / total) * 100}%`;
      seg.title = `${o.label || ""} ${pct(o.price)}`;
      track.appendChild(seg);
    });
    wrap.appendChild(track);

    const legend = el("div", "odds-legend");
    outcomes.forEach((o) => {
      const item = el("span", "odds-legend-item");
      item.appendChild(document.createTextNode((o.label || "") + " "));
      item.appendChild(el("span", "pct", pct(o.price)));
      legend.appendChild(item);
    });
    wrap.appendChild(legend);

    if (odds.url || odds.volume) {
      const vol = el("p", "odds-vol");
      const txt = odds.volume
        ? `Polymarket · $${(odds.volume / 1e6).toFixed(1)}M traded`
        : "Polymarket";
      vol.appendChild(odds.url ? link(odds.url, txt) : document.createTextNode(txt));
      wrap.appendChild(vol);
    }
    return wrap;
  }

  /* ============================================================= *
   *  Composite blocks (rail modules, desks, reading, map, etc.)  *
   * ============================================================= */

  // A boxed rail module: .rail-mod > .rail-mod-head + content.
  function railMod(title, content) {
    const mod = el("section", "rail-mod");
    if (title) mod.appendChild(el("h3", "rail-mod-head", title));
    if (content) mod.appendChild(content);
    return mod;
  }

  // A section front (Contract B.3). storiesCap is the desk cap on the front
  // page; on a desk page pass Infinity for the full uncapped desk.
  function deskSection(key, section, storiesCap) {
    const sec = el("section", "desk");
    sec.setAttribute("data-desk", key);

    const bar = el("div", "section-bar");
    bar.appendChild(el("span", "section-label", DESK_NAMES[key] || key));
    sec.appendChild(bar);

    if (section && section.blurb) {
      sec.appendChild(el("p", "desk-blurb", section.blurb));
    }

    const cols = el("div", "desk-cols");
    const stories = (section && Array.isArray(section.stories)) ? section.stories : [];
    const cap = storiesCap == null ? Infinity : storiesCap;
    stories.slice(0, cap).forEach((s) => cols.appendChild(storyEl(s, { lead: false })));
    sec.appendChild(cols);
    return sec;
  }

  // A "reading room" list (READ items) used by markets + back page.
  function readingList(items, heading) {
    const wrap = el("div", "reading");
    if (heading) wrap.appendChild(el("h3", "reading-head", heading));
    const ol = el("ol", "reading-list");
    (Array.isArray(items) ? items : []).forEach((r) => {
      const li = el("li", "reading-item");
      li.appendChild(link(r.url || "#", r.title || ""));
      if (r.source) {
        li.appendChild(document.createTextNode(" "));
        li.appendChild(el("span", "reading-src", r.source));
      }
      ol.appendChild(li);
    });
    wrap.appendChild(ol);
    return wrap;
  }

  // The AI "Research / Papers" block: papers rendered as compact stories.
  function papersBlock(papers) {
    const wrap = el("section", "papers");
    wrap.appendChild(el("h3", "papers-head", "Research / Papers"));
    const cols = el("div", "papers-cols");
    (Array.isArray(papers) ? papers : []).forEach((p) =>
      cols.appendChild(storyEl(p, { lead: false })));
    wrap.appendChild(cols);
    return wrap;
  }

  // The politics "Key races" compact agate table, one per chamber.
  // mapByChamber is the object { state/district: RACE }.
  function racesTable(chamber, mapByChamber) {
    // Emits the structure newspaper.css styles: table.races > caption, with
    // td.race-state / td.race-pct / td.race-chg and lowercase .party-r/.party-d.
    const table = el("table", "races");
    table.appendChild(el("caption", null, `Key races — ${chamber}`));
    const thead = el("thead");
    const htr = el("tr");
    [["Seat", "race-state"], ["Favorite", ""], ["Price", "race-pct"], ["Chg", "race-chg"]]
      .forEach(([t, c]) => htr.appendChild(el("th", c, t)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");
    Object.keys(mapByChamber || {}).forEach((seat) => {
      const race = mapByChamber[seat] || {};
      const fav = race.fav || {};
      const tr = el("tr");
      const seatCell = el("td", "race-state");
      if (race.url) seatCell.appendChild(link(race.url, seat));
      else seatCell.textContent = seat;
      tr.appendChild(seatCell);
      const party = (fav.party || "").toLowerCase();
      tr.appendChild(el("td", "fav party-" + party, fav.label || (fav.party || "")));
      tr.appendChild(el("td", "race-pct tabular", pct(fav.price)));
      const chg = race.chg;
      const dir = chg > 0 ? "up" : chg < 0 ? "down" : "";
      // A genuine zero (or missing) day-change reads as "no movement" -> em dash,
      // not a misleading column of "0"s.
      const chgTxt = (chg == null || chg === 0) ? "—"
        : `${chg > 0 ? "+" : ""}${Math.round(chg * 100)}`;
      tr.appendChild(el("td", "race-chg " + dir, chgTxt));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  /* ============================================================= *
   *  Masthead (Contract B.4)                                      *
   * ============================================================= */

  function masthead(edition) {
    const head = el("header", "masthead");

    head.appendChild(el("p", "edition-kicker", "PERSONAL EDITION"));
    head.appendChild(el("h1", "nameplate", edition.nameplate || "The Gothic Times"));

    const folio = el("div", "folio");
    // VOL (roman of years since 2025) · NO (edition #)
    const yr = edition.date ? new Date(edition.date + "T12:00:00").getFullYear() : 0;
    const vol = roman(Math.max(1, (yr || 2026) - 2025));
    folio.appendChild(el("span", "folio-left",
      `Vol. ${vol} · No. ${edition.edition != null ? edition.edition : ""}`));
    folio.appendChild(el("span", "folio-mid", longDate(edition.date)));
    folio.appendChild(el("span", "folio-right", edition.dateline || dateline(edition)));
    head.appendChild(folio);

    // weather ear
    const w = edition.weather;
    if (w) {
      const ear = el("div", "weather-ear");
      ear.appendChild(el("span", "wx-place", w.place || ""));
      const bits = [];
      if (w.desc) bits.push(w.desc);
      if (w.now != null) bits.push(`${w.now}°`);
      if (w.hi != null && w.lo != null) bits.push(`${w.hi}° / ${w.lo}°`);
      ear.appendChild(el("span", "wx-data",
        bits.length ? MIDDOT + bits.join(MIDDOT) : ""));
      head.appendChild(ear);
    }
    return head;
  }

  // The fixture has no top-level dateline field; derive from the weather place.
  function dateline(edition) {
    const place = edition.weather && edition.weather.place;
    return place ? place.toUpperCase() : "";
  }

  /* ============================================================= *
   *  Mount helpers                                                *
   * ============================================================= */

  const fill = (node, child) => {
    if (!node) return;
    node.innerHTML = "";
    if (child) node.appendChild(child);
  };
  const append = (node, child) => { if (node && child) node.appendChild(child); };

  /* ============================================================= *
   *  Page renderers                                               *
   * ============================================================= */

  function renderFront(edition) {
    const S = edition.sections || {};

    // [data-np-brief] — ol/li
    const briefMount = $("[data-np-brief]");
    if (briefMount) {
      briefMount.innerHTML = "";
      const ol = el("ol");
      (Array.isArray(edition.brief) ? edition.brief : []).forEach((b) =>
        ol.appendChild(el("li", null, b)));
      briefMount.appendChild(ol);
    }

    // [data-np-lead] — the front-page "well": the lead, then the rest of the
    // markets desk (the reader's #1 interest) as secondary stories in two ruled
    // columns. This fills the lead zone to the rail's height instead of leaving
    // it sparse, and markets is dropped from the desk fronts below (no dup).
    const leadMount = $("[data-np-lead]");
    if (leadMount) {
      leadMount.innerHTML = "";
      if (edition.lead) leadMount.appendChild(storyEl(edition.lead, { lead: true }));
      const leadId = edition.lead && edition.lead.id;
      const mk = (S.markets && Array.isArray(S.markets.stories)) ? S.markets.stories : [];
      const secs = mk.filter((s) => s.id !== leadId).slice(0, 4);
      if (secs.length) {
        const wrap = el("div", "well-secondary");
        secs.forEach((s) => wrap.appendChild(storyEl(s, { lead: false })));
        leadMount.appendChild(wrap);
      }
    }

    // [data-np-rail] — the rail modules
    const railMount = $("[data-np-rail]");
    if (railMount) {
      railMount.innerHTML = "";
      const rail = el("aside", "rail");

      if (S.markets && Array.isArray(S.markets.quotes)) {
        rail.appendChild(railMod("Markets at a glance", marketTable(S.markets.quotes)));
      }
      const balance = S.politics && S.politics.markets_odds && S.politics.markets_odds.balance;
      if (balance) {
        rail.appendChild(railMod("Control of Congress", oddsBar(balance)));
      }
      if (S.sports && Array.isArray(S.sports.today) && S.sports.today.length) {
        rail.appendChild(railMod("Today", scoreboard(S.sports.today)));
      }
      // weather ear in the rail
      if (edition.weather) {
        const w = edition.weather;
        const wx = el("div", "rail-weather");
        wx.appendChild(el("p", "wx-place", w.place || ""));
        const bits = [];
        if (w.desc) bits.push(w.desc);
        if (w.now != null) bits.push(`Now ${w.now}°`);
        if (w.hi != null) bits.push(`High ${w.hi}°`);
        if (w.lo != null) bits.push(`Low ${w.lo}°`);
        wx.appendChild(el("p", "wx-data", bits.join(MIDDOT)));
        rail.appendChild(railMod("Weather", wx));
      }
      railMount.appendChild(rail);
    }

    // Each [data-np-desk="<key>"] — capped section front. Markets is the well
    // above, so it is skipped here to avoid showing the same desk twice.
    DESK_ORDER.forEach((key) => {
      if (key === "markets") return;
      const deskMount = $(`[data-np-desk="${key}"]`);
      if (!deskMount) return;
      fill(deskMount, deskSection(key, S[key], CAPS[key]));
    });

    // [data-np-backpage]
    renderBackpage(edition.backpage);
  }

  function renderBackpage(bp) {
    const m = $("[data-np-backpage]");
    if (!m) return;
    m.innerHTML = "";
    bp = bp || {};

    // Poem
    if (bp.poem) {
      const sec = el("section", "back-mod poem");
      sec.appendChild(el("h3", "back-head", "Poetry Corner"));
      if (bp.poem.title) sec.appendChild(el("p", "poem-title", bp.poem.title));
      if (bp.poem.poet) sec.appendChild(el("p", "poem-poet", bp.poem.poet));
      const body = el("div", "poem-body");
      (Array.isArray(bp.poem.lines) ? bp.poem.lines : []).forEach((ln) =>
        body.appendChild(el("p", "poem-line", ln)));
      sec.appendChild(body);
      if (bp.poem.source) sec.appendChild(el("p", "poem-source", bp.poem.source));
      m.appendChild(sec);
    }

    // Puzzle
    if (bp.puzzle) {
      const sec = el("section", "back-mod puzzle");
      sec.appendChild(el("h3", "back-head", "The Puzzle"));
      if (bp.puzzle.q) sec.appendChild(el("p", "puzzle-q", bp.puzzle.q));
      if (bp.puzzle.a) {
        const det = el("details", "puzzle-a");
        det.appendChild(el("summary", null, "Answer"));
        det.appendChild(el("p", null, bp.puzzle.a));
        sec.appendChild(det);
      }
      m.appendChild(sec);
    }

    // Reading list
    if (Array.isArray(bp.reading) && bp.reading.length) {
      const sec = el("section", "back-mod");
      sec.appendChild(readingList(bp.reading, "Reading Room"));
      m.appendChild(sec);
    }

    // On this day
    if (Array.isArray(bp.on_this_day) && bp.on_this_day.length) {
      const sec = el("section", "back-mod onthisday");
      sec.appendChild(el("h3", "back-head", "On This Day"));
      const ul = el("ul", "otd-list");
      bp.on_this_day.forEach((e) => {
        const li = el("li", "otd-item");
        li.appendChild(el("span", "otd-year", String(e.year || "")));
        li.appendChild(document.createTextNode(" " + (e.text || "")));
        ul.appendChild(li);
      });
      sec.appendChild(ul);
      m.appendChild(sec);
    }
  }

  // A full (uncapped) desk page + that desk's specialized widget(s).
  function renderDeskPage(page, edition) {
    const S = edition.sections || {};
    const section = S[page];
    const deskMount = $(`[data-np-desk="${page}"]`);
    if (deskMount) fill(deskMount, deskSection(page, section, Infinity));
    if (!section) return;

    switch (page) {
      case "markets": {
        if (Array.isArray(section.quotes)) {
          append(deskMount, railMod("Markets", marketTable(section.quotes)));
        }
        if (Array.isArray(section.rates)) {
          append(deskMount, railMod("Rates & Macro", marketTable(section.rates)));
        }
        if (Array.isArray(section.reading)) {
          append(deskMount, readingList(section.reading, "Reading Room"));
        }
        break;
      }
      case "ai": {
        if (Array.isArray(section.papers)) {
          append(deskMount, papersBlock(section.papers));
        }
        break;
      }
      case "politics": {
        const odds = section.markets_odds || {};
        ["senate", "house", "balance"].forEach((k) => {
          if (odds[k]) append(deskMount, railMod(null, oddsBar(odds[k])));
        });
        const map = section.map || {};
        if (map.senate) append(deskMount, racesTable("Senate", map.senate));
        if (map.governor) append(deskMount, racesTable("Governor", map.governor));
        if (map.house) append(deskMount, racesTable("House", map.house));
        break;
      }
      case "sports": {
        // Only render a scoreboard block when it actually has games — an empty
        // heading reads as missing data (common in the offseason).
        if (Array.isArray(section.scoreboard) && section.scoreboard.length) {
          append(deskMount, railMod("Scoreboard", scoreboard(section.scoreboard)));
        }
        if (Array.isArray(section.today) && section.today.length) {
          append(deskMount, railMod("Today", scoreboard(section.today)));
        }
        break;
      }
      default:
        break; // science/world/business/ideas/culture: stories only.
    }
  }

  /* ============================================================= *
   *  render(edition, {page}) — top-level dispatch                 *
   * ============================================================= */

  function render(edition, opts) {
    edition = edition || {};
    const page = (opts && opts.page) ||
      (document.body && document.body.getAttribute("data-page")) || "front";

    // Masthead is on every page.
    const mastMount = $("[data-np-masthead]");
    if (mastMount) fill(mastMount, masthead(edition));

    if (page === "front") {
      renderFront(edition);
    } else if (page === "archive") {
      // Archive page reuses the front layout for whichever date is loaded.
      renderFront(edition);
    } else if (DESK_NAMES[page]) {
      renderDeskPage(page, edition);
    }
  }

  /* ============================================================= *
   *  Data loading                                                 *
   * ============================================================= */

  const qs = new URLSearchParams(location.search);
  const wantedDate = /^\d{4}-\d{2}-\d{2}$/.test(qs.get("date") || "")
    ? qs.get("date") : null;
  const BUST = new Date().toISOString().slice(0, 10); // daily cache-bust

  function grab(path) {
    return fetch(`${path}?v=${BUST}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`fetch ${path}: ${r.status}`))));
  }

  const editionFile = wantedDate
    ? `data/archive/${wantedDate}.json`
    : "data/latest.json";

  function showLoadError() {
    const note = $("[data-np-notice]");
    if (note) {
      note.hidden = false;
      note.textContent = "Couldn't load the edition. If you're opening this file " +
        "directly, serve it over HTTP instead (e.g. python3 -m http.server).";
    } else {
      // eslint-disable-next-line no-console
      console.error("Personal Newspaper: failed to load", editionFile);
    }
  }

  function boot() {
    const page = (document.body && document.body.getAttribute("data-page")) || "front";

    Promise.allSettled([
      grab(editionFile),
      grab("data/index.json"),
    ]).then(([ed, idx]) => {
      if (ed.status !== "fulfilled") { showLoadError(); return; }
      const index = idx.status === "fulfilled" ? idx.value : [];
      try {
        render(ed.value, { page });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Personal Newspaper render error:", err);
      }
      if (page === "archive") setupArchive(ed.value, index);
    });
  }

  /* ============================================================= *
   *  Archive prev/next + keyboard nav                             *
   * ============================================================= */

  // index.json may be ["YYYY-MM-DD", …] or [{date:"…"}, …]; normalize to a
  // sorted ascending array of date strings.
  function indexDates(index) {
    const dates = (Array.isArray(index) ? index : [])
      .map((e) => (typeof e === "string" ? e : (e && e.date)))
      .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d || ""));
    return dates.sort();
  }

  function setupArchive(edition, index) {
    const dates = indexDates(index);
    const cur = (edition && edition.date) || wantedDate;
    let i = dates.indexOf(cur);
    if (i === -1 && dates.length) i = dates.length - 1;
    const prev = i > 0 ? dates[i - 1] : null;
    const next = i >= 0 && i < dates.length - 1 ? dates[i + 1] : null;
    const newest = dates.length ? dates[dates.length - 1] : null;

    const hrefFor = (d) => {
      if (!d) return null;
      return d === newest ? location.pathname : `?date=${d}`;
    };

    const prevA = $("[data-np-archive-prev]");
    const nextA = $("[data-np-archive-next]");
    if (prevA) {
      if (prev) prevA.href = `?date=${prev}`;
      else prevA.classList.add("disabled");
    }
    if (nextA) {
      const h = hrefFor(next);
      if (h) nextA.href = h;
      else nextA.classList.add("disabled");
    }

    // The date picker: clamp to available editions, jump on change.
    const dateInput = $("[data-np-archive-date]");
    if (dateInput) {
      if (cur) dateInput.value = cur;
      if (dates.length) { dateInput.min = dates[0]; dateInput.max = newest; }
      dateInput.addEventListener("change", () => {
        if (dateInput.value) location.search = `?date=${dateInput.value}`;
      });
    }

    document.addEventListener("keydown", (e) => {
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowLeft" && prev) {
        location.search = `?date=${prev}`;
      } else if (e.key === "ArrowRight" && next) {
        const h = hrefFor(next);
        if (h && h.startsWith("?")) location.search = h;
        else if (h) location.assign(h);
      }
    });
  }

  /* ============================================================= *
   *  Boot                                                         *
   * ============================================================= */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // Expose helpers for testing / debugging (no harm in the browser).
  if (typeof window !== "undefined") {
    window.NP = {
      el, link, relTime, sparkline, longDate, roman,
      storyEl, marketTable, scoreboard, oddsBar, render,
    };
  }
})();
