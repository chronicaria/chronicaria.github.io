/* The Gothic Times — edition renderer.
   Self-contained (does not load site.js): daily/ pages live in a
   subdirectory, so paths and keyboard shortcuts differ from the
   rest of the site. */
(() => {
  "use strict";

  const PAGE = document.body.dataset.paper || "front";
  const PAGES = ["index.html", "sports.html", "ai.html", "markets.html", "elections.html", "math.html"];

  /* ---------- shared chrome (burger / theme / year) ---------- */
  const burger = document.querySelector("[data-nav-burger]");
  const nav = document.querySelector(".primary-nav");
  if (burger && nav) burger.addEventListener("click", () => nav.classList.toggle("open"));
  document.querySelectorAll(".nav-drop > .nav-drop-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const drop = btn.parentElement;
      document.querySelectorAll(".nav-drop.open").forEach((d) => d !== drop && d.classList.remove("open"));
      drop.classList.toggle("open");
    });
  });
  document.addEventListener("click", () => {
    document.querySelectorAll(".nav-drop.open").forEach((d) => d.classList.remove("open"));
  });
  document.querySelectorAll("[data-year]").forEach((n) => (n.textContent = new Date().getFullYear()));
  const toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    const apply = () => { toggle.textContent = document.documentElement.dataset.theme === "light" ? "◑ dark mode" : "◐ light mode"; };
    apply();
    toggle.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
      apply();
    });
  }

  /* ---------- tiny DOM + format helpers ---------- */
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const link = (href, text, cls) => {
    const a = el("a", cls, text);
    a.href = href;
    if (/^https?:/.test(href)) { a.target = "_blank"; a.rel = "noopener"; }
    return a;
  };
  const relTime = (iso) => {
    if (!iso) return "";
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 60) return `${Math.max(mins, 1)}m ago`;
    if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
    if (mins < 60 * 48) return "yesterday";
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
  const cents = (p) => `${Math.round(p * 100)}¢`;
  const NS = "http://www.w3.org/2000/svg";
  const sparkline = (values, up) => {
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
    /* min / max dots */
    for (const [v, cls] of [[max, "hi"], [min, "lo"]]) {
      const i = values.indexOf(v);
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", X(i).toFixed(1));
      dot.setAttribute("cy", Y(v).toFixed(1));
      dot.setAttribute("r", "1.6");
      dot.setAttribute("class", `dot ${cls}`);
      svg.appendChild(dot);
    }
    /* crosshair */
    const ch = document.createElementNS(NS, "line");
    ch.setAttribute("class", "xhair");
    ch.setAttribute("y1", "0"); ch.setAttribute("y2", h);
    ch.style.display = "none";
    svg.appendChild(ch);
    const lbl = el("span", "spark-readout");
    lbl.style.display = "none";
    svg.addEventListener("mousemove", (e) => {
      const r = svg.getBoundingClientRect();
      const i = Math.min(values.length - 1, Math.max(0, Math.round(((e.clientX - r.left) / r.width) * (values.length - 1))));
      ch.setAttribute("x1", X(i)); ch.setAttribute("x2", X(i));
      ch.style.display = "";
      lbl.textContent = values[i].toLocaleString();
      lbl.style.display = "";
    });
    svg.addEventListener("mouseleave", () => { ch.style.display = "none"; lbl.style.display = "none"; });
    const wrap = el("span", "spark-wrap");
    wrap.append(svg, lbl);
    return wrap;
  };
  const longDate = (iso) =>
    new Date(iso + "T12:00:00").toLocaleDateString("en-US",
      { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  const roman = (n) => { // volume = years since launch, kept simple
    const R = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
    let out = "";
    for (const [v, s] of R) while (n >= v) { out += s; n -= v; }
    return out || "I";
  };

  /* ---------- data loading ---------- */
  const qs = new URLSearchParams(location.search);
  const wanted = /^\d{4}-\d{2}-\d{2}$/.test(qs.get("date") || "") ? qs.get("date") : null;
  const BUST = new Date().toISOString().slice(0, 10);   // defeats the Pages edge cache once a day
  const grab = (path) => fetch(`${path}?v=${BUST}`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(path))));

  const editionFile = wanted ? `../data/daily/${wanted}.json` : "../data/daily/latest.json";
  Promise.allSettled([
    grab(editionFile),
    grab("../data/daily/index.json"),
    grab("../data/sports.json"),
    PAGE === "front" ? grab("../data/daily/poems.json") : Promise.resolve(null),
  ]).then(([ed, idx, sports, poems]) => {
    if (ed.status !== "fulfilled") {
      const note = $("[data-gt-notice]");
      if (note) {
        note.hidden = false;
        note.textContent = "Couldn't load the edition. If you're opening this file directly, serve the site over HTTP instead (e.g. python3 -m http.server).";
      }
      return;
    }
    render(ed.value,
      idx.status === "fulfilled" ? idx.value : [],
      sports.status === "fulfilled" ? sports.value : null,
      poems && poems.status === "fulfilled" ? poems.value : null);
  });

  /* ---------- building blocks ---------- */
  function metaLine(it, { team = false } = {}) {
    const meta = el("div", "meta");
    const src = el("span", "src", it.source);
    meta.appendChild(src);
    if (it.paywalled) meta.appendChild(el("span", "lock", " 🔒"));
    if (team && it.tags && it.tags[1]) {
      meta.appendChild(document.createTextNode(" · "));
      meta.appendChild(el("span", "team", it.tags[1]));
    }
    if (it.published) meta.appendChild(document.createTextNode(` · ${relTime(it.published)}`));
    if (it.points) meta.appendChild(document.createTextNode(` · ▲${it.points}`));
    return meta;
  }

  function entry(it, { blurb = true, team = false, big = false } = {}) {
    const art = el("article", "gt-entry" + (big ? " lead-of-block" : ""));
    art.id = `s-${it.id}`;
    const h3 = el("h3");
    h3.appendChild(link(it.url, it.title));
    const perma = el("a", "permalink", "#");
    perma.href = `#s-${it.id}`;
    perma.title = "Link to this story";
    h3.appendChild(perma);
    art.appendChild(h3);
    art.appendChild(metaLine(it, { team }));
    const echo = it.blurb && it.blurb.replace(/…$/, "").toLowerCase().startsWith(it.title.slice(0, 40).toLowerCase());
    if (blurb && it.blurb && !echo) art.appendChild(el("p", "blurb", it.blurb));
    return art;
  }

  function wire(items, { points = false } = {}) {
    const ul = el("ul", "gt-wire");
    for (const it of items) {
      const li = el("li");
      li.appendChild(link(it.url, it.title));
      li.appendChild(el("span", "src", points && it.points ? `▲${it.points}` : it.source));
      ul.appendChild(li);
    }
    return ul;
  }

  function controlRow(chamber, ctrl) {
    const row = el("div", "gt-control-row");
    const dem = (ctrl.outcomes.find((o) => /democrat/i.test(o.label)) || {}).price;
    const rep = (ctrl.outcomes.find((o) => /republican/i.test(o.label)) || {}).price;
    if (dem == null || rep == null) return null;
    const lbl = el("div", "lbl-row");
    lbl.appendChild(el("span", "chamber", chamber));
    const odds = el("span", "odds");
    const d = el("b", "d", `D ${cents(dem)}`);
    const r = el("b", "r", `R ${cents(rep)}`);
    odds.append(d, document.createTextNode(" · "), r);
    lbl.appendChild(odds);
    row.appendChild(lbl);
    const bar = el("div", "gt-control-bar");
    const total = dem + rep;
    const dSpan = el("span", "d"); dSpan.style.width = `${(dem / total) * 100}%`;
    const rSpan = el("span", "r"); rSpan.style.width = `${(rep / total) * 100}%`;
    bar.append(dSpan, rSpan);
    row.appendChild(bar);
    const linkP = el("p", "small-copy muted");
    linkP.style.margin = ".25rem 0 0";
    linkP.appendChild(link(ctrl.url, `Polymarket · $${(ctrl.volume / 1e6).toFixed(1)}M traded`));
    row.appendChild(linkP);
    return row;
  }

  /* ---------- scoreboard helpers (from sports.json) ---------- */
  function recentFinals(sports, hours) {
    if (!sports) return [];
    const cutoff = Date.now() - hours * 36e5;
    return sports.teams
      .flatMap((t) => (t.form || []).map((g) => ({ t, g })))
      .filter(({ g }) => new Date(g.date).getTime() > cutoff)
      .sort((a, b) => b.g.date.localeCompare(a.g.date));
  }
  function todaysGames(sports) {
    if (!sports) return [];
    const today = new Date().toDateString();
    return sports.teams
      .flatMap((t) => (t.next || []).map((g) => ({ t, g })))
      .filter(({ g }) => new Date(g.date).toDateString() === today)
      .sort((a, b) => (a.t.tier - b.t.tier) || a.g.date.localeCompare(b.g.date));
  }
  function scoreLine({ t, g }) {
    const div = el(g.url ? "a" : "div", "score-line");
    if (g.url) { div.href = g.url; div.target = "_blank"; div.rel = "noopener"; div.title = "Open on ESPN"; }
    const match = el("span", "score-match");
    const strong = el("strong", null, t.label);
    match.appendChild(strong);
    if (g.res) {
      match.appendChild(document.createTextNode(` ${g.score} ${g.home ? "vs" : "at"} ${g.opp}`));
      const st = el("span", `score-status ${g.res === "W" ? "win" : g.res === "L" ? "loss" : ""}`, g.res);
      div.append(match, st);
    } else {
      match.appendChild(document.createTextNode(` ${g.home ? "vs" : "at"} ${g.opp}`));
      if (g.odds) match.appendChild(el("span", "odds-line", ` ${g.odds}`));
      const when = g.tbd ? "TBD" :
        new Date(g.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      div.append(match, el("span", "score-status", when));
    }
    return div;
  }

  /* ---------- masthead ---------- */
  function fillMasthead(data, index) {
    const set = (sel, text) => { const n = $(sel); if (n) n.textContent = text; };
    set("[data-gt-date]", longDate(data.date));
    set("[data-gt-edition]", `Vol. ${roman(new Date(data.date).getFullYear() - 2025)} · No. ${data.edition}`);
    if (data.weather) {
      const w = $("[data-gt-weather]");
      if (w) {
        w.innerHTML = "";
        w.appendChild(el("strong", null, data.weather.place));
        w.appendChild(document.createTextNode(` ${data.weather.desc} · ${data.weather.hi}° / ${data.weather.lo}°`));
      }
    }
    if (data.generated_at) {
      set("[data-gt-printed]", `printed ${new Date(data.generated_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`);
    }
    // archive arrows
    const cur = data.date;
    const i = index.indexOf(cur);
    const prev = i > 0 ? index[i - 1] : null;
    const next = i >= 0 && i < index.length - 1 ? index[i + 1] : null;
    const prevA = $("[data-gt-prev]"), nextA = $("[data-gt-next]");
    if (prevA) { if (prev) prevA.href = `?date=${prev}`; else prevA.classList.add("disabled"); }
    if (nextA) {
      if (next) nextA.href = next === index[index.length - 1] ? location.pathname : `?date=${next}`;
      else nextA.classList.add("disabled");
    }
    // keep paper-nav links on the same date when browsing the archive
    if (wanted) {
      document.querySelectorAll(".gt-nav a").forEach((a) => {
        a.href = a.getAttribute("href").split("?")[0] + `?date=${wanted}`;
      });
    }
  }

  /* ---------- page renderers ---------- */
  function render(data, index, sports, poems) {
    fillMasthead(data, index);
    /* stale-press warning: the cron should print every morning */
    if (!wanted && data.generated_at &&
        Date.now() - new Date(data.generated_at).getTime() > 30 * 36e5) {
      const note = $("[data-gt-notice]");
      if (note) {
        note.hidden = false;
        note.textContent = `This edition was printed ${longDate(data.date)} — the press may have jammed. Check the repo's Actions tab.`;
      }
    }
    const S = data.sections;
    if (PAGE === "front") { renderFront(data, S, index, sports, poems); frontNewDots(data, index); }
    if (PAGE === "sports") { renderSports(S.sports, sports); renderExtrasSports(sports); }
    if (PAGE === "ai") { renderAI(S.ai); renderBenchmarks(); }
    if (PAGE === "markets") { renderMarkets(S.markets); renderWatchlist(S.markets); }
    if (PAGE === "elections") { renderElections(S.elections); renderExtrasElections(S.elections); }
    if (PAGE === "math") { renderMath(S.math || {}); }
    setupOfflineChip();
    setupStoryKeys();
  }

  function renderFront(data, S, index, sports, poems) {
    /* game-day banner */
    const today = todaysGames(sports);
    const banner = $("[data-gt-gameday]");
    if (banner && today.length) {
      banner.hidden = false;
      banner.appendChild(el("span", "tag", "Game day"));
      today.slice(0, 2).forEach(({ t, g }) => {
        const s = el("span");
        s.appendChild(el("strong", null, `${t.label} ${g.home ? "vs" : "at"} ${g.opp}`));
        const when = g.tbd ? " · TBD" :
          ` · ${new Date(g.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
        const w = el("span", "when", when);
        banner.append(s, w);
      });
    }

    /* the brief */
    const briefBox = $("[data-gt-briefs]");
    if (briefBox && data.briefs) {
      data.briefs.forEach((b, i) => {
        const d = el("div", "gt-brief-item");
        d.appendChild(el("span", "n", String(i + 1)));
        d.appendChild(link(b.url, b.title));
        d.appendChild(el("span", "src", `${b.section} · ${b.source}`));
        briefBox.appendChild(d);
      });
    }

    /* lead story */
    const leadBox = $("[data-gt-lead]");
    if (leadBox && data.lead) {
      const it = data.lead;
      const kick = el("div", "kicker");
      kick.appendChild(el("span", "tag", it.section === "ai" ? "AI & Models" : it.section));
      kick.appendChild(el("span", "eyebrow", "Lead story"));
      kick.lastChild.style.margin = "0";
      leadBox.appendChild(kick);
      const h2 = el("h2", "headline");
      h2.appendChild(link(it.url, it.title));
      leadBox.appendChild(h2);
      if (it.blurb) leadBox.appendChild(el("p", "deck", it.blurb));
      const meta = el("p", "meta");
      meta.append(link(it.url, it.source), document.createTextNode(` · ${relTime(it.published)} · `),
        link(it.url, "Continue reading ↗"));
      leadBox.appendChild(meta);
    }

    /* rail: market mini-quotes */
    const quotes = $("[data-gt-quotes]");
    if (quotes && S.markets.snapshot) {
      S.markets.snapshot.slice(0, 6).forEach((q) => {
        const lineEl = el("div", "gt-quote-line");
        lineEl.appendChild(el("span", "lbl", q.label));
        const val = el("span", `val ${q.chg >= 0 ? "up" : "down"}`);
        const px = q.kind === "yield" ? `${q.price.toFixed(2)}%` : q.price.toLocaleString();
        val.textContent = `${px} ${q.chg >= 0 ? "▲" : "▼"}${Math.abs(q.chgPct).toFixed(1)}%`;
        lineEl.appendChild(val);
        quotes.appendChild(lineEl);
      });
    }

    /* rail: control of congress */
    const ctrlBox = $("[data-gt-control]");
    if (ctrlBox && S.elections.control) {
      for (const [key, label] of [["senate", "Senate"], ["house", "House"]]) {
        const c = S.elections.control[key];
        if (!c) continue;
        const row = controlRow(label, c);
        if (row) ctrlBox.appendChild(row);
      }
    }

    /* rail: today's slate / latest finals */
    const todayBox = $("[data-gt-today]");
    if (todayBox) {
      const games = today.length ? today : recentFinals(sports, 36);
      const head = $("[data-gt-today-head]");
      if (head && !today.length) head.textContent = "Latest finals";
      games.slice(0, 5).forEach((g) => todayBox.appendChild(scoreLine(g)));
      if (!games.length) {
        /* off-season: count down to the next tier-1 game instead */
        const next = (sports ? sports.teams : [])
          .filter((t) => t.tier === 1)
          .flatMap((t) => (t.next || []).map((g) => ({ t, g })))
          .sort((a, b) => a.g.date.localeCompare(b.g.date))[0];
        if (next) {
          const days = Math.ceil((new Date(next.g.date) - Date.now()) / 864e5);
          todayBox.appendChild(el("p", "small-copy muted",
            `${next.t.label} ${next.g.home ? "vs" : "at"} ${next.g.opp} in ${days} days — the countdown is on.`));
        } else {
          todayBox.appendChild(el("p", "small-copy muted", "No games on the slate."));
        }
      }
    }

    /* section blocks */
    const blocks = [
      ["sports", S.sports.items, { team: true }],
      ["ai", S.ai.items, {}],
      ["elections", S.elections.items, {}],
      ["markets", S.markets.items, {}],
    ];
    for (const [sec, items, opts] of blocks) {
      const box = $(`[data-gt-block-${sec}]`);
      if (!box) continue;
      if (!items.length) { box.appendChild(el("p", "small-copy muted", "A quiet day on this desk.")); continue; }
      items.slice(0, 4).forEach((it, i) => {
        box.appendChild(entry(it, { blurb: i === 0, big: i === 0, team: opts.team }));
      });
    }

    /* across the wire: best of what didn't make the blocks */
    const wireBox = $("[data-gt-frontwire]");
    if (wireBox) {
      const leftovers = [
        ...S.sports.items.slice(4), ...S.ai.items.slice(4),
        ...S.elections.items.slice(4), ...S.markets.items.slice(4),
        ...(S.ai.papers || []).slice(0, 2),
      ].sort((a, b) => b.score - a.score).slice(0, 7);
      if (leftovers.length) {
        $("[data-gt-wire-card]").hidden = false;
        for (const it of leftovers) {
          const li = el("li");
          li.appendChild(el("span", `sec sec-${it.section}`, it.section === "elections" ? "midterms" : it.section));
          li.appendChild(link(it.url, it.title));
          li.appendChild(el("span", "src", it.source));
          wireBox.appendChild(li);
        }
      }
    }

    /* the week (Sunday edition) */
    const weekBox = $("[data-gt-week]");
    if (weekBox && data.week) {
      weekBox.hidden = false;
      if (data.week.story) {
        const p = el("p", "blurb");
        p.append("Story of the week: ", link(data.week.story.url, data.week.story.title),
          ` (${data.week.story.source}).`);
        weekBox.appendChild(p);
      }
      if (data.week.mover) {
        const m = data.week.mover;
        const p = el("p", "blurb");
        const up = m.chg > 0;
        p.append("Mover of the week: ", link(m.url,
          `${STATE_NAMES[m.key.slice(0, 2)] || m.key} ${OFFICE_LABEL[m.office] || m.office}`),
          ` — Democrats ${up ? "▲" : "▼"}${Math.abs(Math.round(m.chg * 100))}¢ since ${longDate(data.week.from)}.`);
        weekBox.appendChild(p);
      }
    }

    /* puzzle + league pulse (back page) */
    const puzzleBox = $("[data-gt-puzzle]");
    if (puzzleBox && data.puzzle) {
      puzzleBox.appendChild(el("p", "blurb", data.puzzle.q));
      const det = el("details", "puzzle-answer");
      det.appendChild(el("summary", null, "Reveal the answer"));
      det.appendChild(el("p", "blurb", data.puzzle.a));
      puzzleBox.appendChild(det);
    }
    const leagueBox = $("[data-gt-league]");
    if (leagueBox && data.league) {
      const p = el("p", "blurb");
      p.append(`The SMP season sits at day ${data.league.day}. `,
        link("../league/index.html", "Standings, box scores & the playoff race →"));
      leagueBox.appendChild(p);
    }

    /* back page: poem, reading room, archive */
    if (poems && poems.length) {
      const p = poems[(data.edition - 1 + poems.length * 100) % poems.length];
      const box = $("[data-gt-poem]");
      if (box) {
        box.appendChild(el("blockquote", null, p.lines.join("\n")));
        const attr = el("p", "attr");
        attr.append(document.createTextNode("— "), el("em", null, p.title), document.createTextNode(`, ${p.poet}`));
        box.appendChild(attr);
      }
    }
    const reading = $("[data-gt-reading]");
    if (reading && S.markets.reading) {
      const r = Array.isArray(S.markets.reading) ? S.markets.reading[0] : S.markets.reading;
      const h3 = el("h3");
      h3.appendChild(link(r.url, r.title));
      reading.append(h3, el("p", "who", r.source || r.who || ""));
      if (r.note) reading.appendChild(el("p", "note", r.note));
    }
    const arch = $("[data-gt-archive]");
    if (arch && index.length > 1) {
      index.slice(0, -1).slice(-7).reverse().forEach((d) => {
        const li = el("li");
        li.appendChild(link(`?date=${d}`, longDate(d)));
        arch.appendChild(li);
      });
    } else if (arch) {
      arch.appendChild(el("li", "muted", "This is the first edition. History starts tomorrow."));
    }
  }

  function renderSports(sec, sports) {
    const sb = $("[data-gt-scoreboard]");
    if (sb) {
      const today = todaysGames(sports), finals = recentFinals(sports, 36);
      [...finals.slice(0, 4), ...today.slice(0, 4)].forEach((g) => sb.appendChild(scoreLine(g)));
      if (!today.length && !finals.length)
        sb.appendChild(el("p", "small-copy muted", "Nothing on the slate in the last day and a half."));
    }

    const byTeam = {};
    const tiers = { 1: [], 2: [], 3: [] };
    sec.items.forEach((it) => {
      const m = it.tags.find((t) => /^tier\d$/.test(t));
      const tier = m ? +m[4] : 3;
      tiers[tier].push(it);
      if (tier === 1) (byTeam[it.tags[0]] = byTeam[it.tags[0]] || []).push(it);
    });

    /* tier 1: one desk card per team, logo + record from sports.json */
    const desks = $("[data-gt-team-desks]");
    if (desks) {
      const meta = {};
      (sports ? sports.teams : []).forEach((t) => (meta[t.key] = t));
      const order = ["duke-mbb", "duke-fb", "mavs"].filter((k) => byTeam[k]);
      Object.keys(byTeam).forEach((k) => { if (!order.includes(k)) order.push(k); });
      if (!order.length) desks.appendChild(el("p", "small-copy muted", "A quiet day at the top of the rooting order."));
      for (const key of order) {
        const t = meta[key] || {};
        const card = el("section", "card gt-team-desk");
        if (t.color) card.style.setProperty("--team", `#${t.color}`);
        const head = el("div", "desk-head");
        if (t.logo) {
          const img = el("img");
          img.src = t.logo; img.alt = ""; img.loading = "lazy";
          img.addEventListener("error", () => img.remove());
          head.appendChild(img);
        }
        const who = el("div", "who");
        who.appendChild(el("h3", null, t.label || byTeam[key][0].tags[1]));
        if (t.record) who.appendChild(el("div", "rec", `${t.record}${t.standing ? " · " + t.standing : ""}`));
        head.appendChild(who);
        card.appendChild(head);
        byTeam[key].forEach((it, i) => card.appendChild(entry(it, { blurb: i < 2, big: i === 0 })));
        desks.appendChild(card);
      }
    }

    /* tiers 2–3: one compact card */
    const rest = $("[data-gt-rest]");
    if (rest) {
      if (!tiers[2].length && !tiers[3].length) {
        rest.appendChild(el("p", "small-copy muted", "Quiet day around the rest of the leagues."));
      }
      tiers[2].forEach((it, i) => rest.appendChild(entry(it, { team: true, blurb: i === 0 })));
      if (tiers[3].length) rest.appendChild(wire(tiers[3].map((it) => ({ ...it, source: `${it.tags[1]} · ${it.source}` }))));
    }
  }

  const LAB_META = {
    "Anthropic":       { hue: "#d97757" },
    "OpenAI":          { hue: "#9fb7c9" },
    "Google DeepMind": { hue: "#4285f4" },
    "DeepSeek":        { hue: "#4d6bfe" },
    "xAI":             { hue: "#cbd2dc" },
    "Mistral":         { hue: "#fa520f" },
  };

  function renderAITimeline() {
    const strip = $("[data-gt-ai-timeline]");
    if (!strip) return;
    grab("../data/daily/ai-releases.json").then((releases) => {
      releases.slice(-9).forEach((r) => {
        const d = el("div", "gt-release");
        d.appendChild(el("span", "when", r.when));
        d.appendChild(el("span", "what", r.label));
        d.appendChild(el("span", "who", r.who));
        strip.appendChild(d);
      });
    }).catch(() => { strip.parentElement.hidden = true; });
  }

  function renderAI(sec) {
    renderAITimeline();
    const labs = sec.items.filter((i) => i.bucket === "labs");

    /* featured story — the desk's front page */
    const featBox = $("[data-gt-ai-feature]");
    if (featBox && labs.length) {
      const it = labs[0];
      const kick = el("div", "kicker");
      kick.appendChild(el("span", "tag", it.source));
      featBox.appendChild(kick);
      const h2 = el("h2", "headline");
      h2.appendChild(link(it.url, it.title));
      featBox.appendChild(h2);
      if (it.blurb) featBox.appendChild(el("p", "deck", it.blurb));
      const meta = el("p", "meta");
      meta.append(document.createTextNode(`${relTime(it.published)} · `), link(it.url, "Read at the source ↗"));
      featBox.appendChild(meta);
    }

    /* lab board: one tile per lab — latest item + recency pulse */
    const board = $("[data-gt-ai-labs-board]");
    if (board) {
      for (const [lab, meta] of Object.entries(LAB_META)) {
        const items = labs.filter((i) => i.source === lab);
        const tile = el("a", "gt-lab" + (items.length ? "" : " quiet"));
        tile.style.setProperty("--lab", meta.hue);
        const head = el("div", "lab-head");
        head.appendChild(el("span", "lab-dot"));
        head.appendChild(el("span", "lab-name", lab));
        tile.appendChild(head);
        if (items.length) {
          const top = items[0];
          tile.href = top.url; tile.target = "_blank"; tile.rel = "noopener";
          tile.appendChild(el("p", "lab-latest", top.title));
          tile.appendChild(el("span", "lab-when", relTime(top.published)));
        } else {
          tile.appendChild(el("p", "lab-latest muted", "Nothing new this cycle."));
        }
        board.appendChild(tile);
      }
    }

    /* the rest of the wire */
    const labsBox = $("[data-gt-ai-labs]");
    if (labsBox) {
      const rest = labs.slice(1);
      if (!rest.length) labsBox.appendChild(el("p", "small-copy muted", "A one-story day."));
      rest.forEach((it, i) => labsBox.appendChild(entry(it, { blurb: i < 4 })));
    }

    /* papers with upvote bars */
    const papersBox = $("[data-gt-ai-papers]");
    if (papersBox) {
      const papers = sec.papers || [];
      const maxPts = Math.max(...papers.map((p) => p.points || 0), 1);
      papers.forEach((p) => {
        const div = el("div", "gt-paper");
        const h3 = el("h3");
        h3.appendChild(link(p.url, p.title));
        div.appendChild(h3);
        const meta = el("div", "meta");
        meta.appendChild(el("span", "src", p.source));
        if (p.points) meta.appendChild(document.createTextNode(` · ▲${p.points}`));
        div.appendChild(meta);
        if (p.points) {
          const bar = el("div", "votebar");
          const fill = el("span");
          fill.style.width = `${Math.max((p.points / maxPts) * 100, 6)}%`;
          bar.appendChild(fill);
          div.appendChild(bar);
        }
        papersBox.appendChild(div);
      });
    }
  }

  function renderMath(sec) {
    const items = (sec && sec.items) || [];
    const groups = [
      ["pde", "[data-gt-math-pde]"],
      ["astro", "[data-gt-math-astro]"],
      ["string", "[data-gt-math-string]"],
    ];
    for (const [bucket, sel] of groups) {
      const box = $(sel);
      if (!box) continue;
      const list = items.filter((i) => i.bucket === bucket);
      if (!list.length) {
        box.appendChild(el("p", "small-copy muted", "Quiet on the preprint server today — check back tomorrow."));
        continue;
      }
      list.forEach((it, i) => box.appendChild(entry(it, { blurb: i < 4 })));
    }
  }

  function renderMarkets(sec) {
    const snap = $("[data-gt-snapshot]");
    if (snap && sec.snapshot) {
      const drawSnap = (view) => {
        snap.innerHTML = "";
        sec.snapshot.forEach((q) => {
          const box = el("div", "stat-box gt-quote-card");
          box.appendChild(el("span", "stat-value", q.price.toLocaleString()));
          const delta = el("span", `stat-delta ${q.chg >= 0 ? "up" : "down"}`,
            `${q.chg >= 0 ? "+" : ""}${q.chg.toLocaleString()} (${q.chg >= 0 ? "+" : ""}${q.chgPct.toFixed(2)}%)`);
          box.appendChild(delta);
          box.appendChild(el("span", "stat-label", q.label));
          const series = view === "3M" ? q.spark
            : view === "1M" ? (q.spark || []).slice(-22)
            : (q.intraday && q.intraday.length > 2 ? q.intraday : (q.spark || []).slice(-22));
          if (series && series.length > 2) {
            box.appendChild(sparkline(series, series[series.length - 1] >= series[0]));
          }
          snap.appendChild(box);
        });
      };
      drawSnap(localStorage.getItem("gtSparkView") || "1D");
      document.querySelectorAll("[data-gt-spark-view]").forEach((btn) => {
        const sync = () => document.querySelectorAll("[data-gt-spark-view]").forEach((b) =>
          b.classList.toggle("active", b.dataset.gtSparkView === (localStorage.getItem("gtSparkView") || "1D")));
        sync();
        btn.addEventListener("click", () => {
          localStorage.setItem("gtSparkView", btn.dataset.gtSparkView);
          sync();
          drawSnap(btn.dataset.gtSparkView);
        });
      });
    }
    const macroBox = $("[data-gt-macro]");
    if (macroBox && (sec.macro || []).length) {
      sec.macro.forEach((m) => {
        const lineEl = el("div", "gt-quote-line");
        lineEl.appendChild(el("span", "lbl", `${m.label} (${m.note})`));
        lineEl.appendChild(el("span", "val", m.value));
        macroBox.appendChild(lineEl);
      });
    }
    const news = $("[data-gt-mkt-news]");
    if (news) {
      sec.items.forEach((it, i) => {
        const art = entry(it, { blurb: i < 3 && it.bucket !== "quant", big: i === 0 });
        if (it.bucket === "quant") {
          const chip = el("span", "tag quant", "Quant");
          const meta = art.querySelector(".meta");
          meta.insertBefore(document.createTextNode(" "), meta.firstChild);
          meta.insertBefore(chip, meta.firstChild);
        }
        news.appendChild(art);
      });
    }
    const reading = $("[data-gt-reading]");
    if (reading && sec.reading) {
      const picks = Array.isArray(sec.reading) ? sec.reading : [sec.reading];
      picks.forEach((r) => {
        const div = el("div", "gt-entry");
        const h3 = el("h3");
        h3.appendChild(link(r.url, r.title));
        div.appendChild(h3);
        div.appendChild(el("div", "meta", r.source || r.who || ""));
        if (r.note) div.appendChild(el("p", "blurb", r.note));
        reading.appendChild(div);
      });
    }
  }

  /* ---------- the election hex map (Polymarket odds) ---------- */
  const TILE_GRID = { /* state → [col, row] anchors, roughly geographic */
    AK: [0, 0], ME: [11, 0],
    VT: [10, 1], NH: [11, 1],
    WA: [1, 2], ID: [2, 2], MT: [3, 2], ND: [4, 2], MN: [5, 2], IL: [6, 2], WI: [7, 2], MI: [8, 2], NY: [9, 2], RI: [10, 2], MA: [11, 2],
    OR: [1, 3], NV: [2, 3], WY: [3, 3], SD: [4, 3], IA: [5, 3], IN: [6, 3], OH: [7, 3], PA: [8, 3], NJ: [9, 3], CT: [10, 3],
    CA: [1, 4], UT: [2, 4], CO: [3, 4], NE: [4, 4], MO: [5, 4], KY: [6, 4], WV: [7, 4], VA: [8, 4], MD: [9, 4], DE: [10, 4],
    AZ: [2, 5], NM: [3, 5], KS: [4, 5], AR: [5, 5], TN: [6, 5], NC: [7, 5], SC: [8, 5], DC: [9, 5],
    OK: [4, 6], LA: [5, 6], MS: [6, 6], AL: [7, 6], GA: [8, 6],
    HI: [0, 7], TX: [4, 7], FL: [9, 7],
  };
  const STATE_NAMES = {
    AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
    CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
    IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
    ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
    MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
    NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina",
    ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania",
    RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas",
    UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
    WI: "Wisconsin", WY: "Wyoming", DC: "D.C.",
  };

  /* Wikipedia WikiProject Elections & Referendums USA legend, by odds bucket */
  const PALETTES = {
    atlas: {
      D: ["#B9D7FF", "#86B6F2", "#4389E3", "#1666CB", "#0645B4", "#002B84"],
      R: ["#F2B3BE", "#E27F90", "#CC2F4A", "#D40000", "#AA0000", "#800000"],
      I: ["#C8E4C0", "#9FD09A", "#6FBA6C", "#3FA03F", "#1F7A1F", "#0B520B"],
    },
    cb: { /* color-blind-safe: blues vs oranges; independents teal-green */
      D: ["#CFE5F2", "#9DC7E4", "#67A3CE", "#3D7FB5", "#20609B", "#0B3D73"],
      R: ["#FBE3C5", "#F5C389", "#EC9F50", "#DD7B1B", "#B35F10", "#7E430B"],
      I: ["#CDEAE2", "#9ED4C5", "#6CBCA6", "#3FA088", "#1F7E6A", "#0B584A"],
    },
  };
  let paletteKey = localStorage.getItem("gtPalette") === "cb" ? "cb" : "atlas";
  const oddsBucket = (price) => Math.min(5, Math.max(0, Math.floor((price * 100 - 40) / 10)));
  const partyColor = (party, price) => (PALETTES[paletteKey][party] || PALETTES[paletteKey].I)[oddsBucket(price)];
  const lightFill = (party, price) => oddsBucket(price) < 2;

  const svgEl = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    return n;
  };
  function hexPoints(cx, cy, s) {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 180) * (60 * i - 30);
      pts.push(`${(cx + s * Math.cos(a)).toFixed(1)},${(cy + s * Math.sin(a)).toFixed(1)}`);
    }
    return pts.join(" ");
  }
  /* hex-spiral offsets, enough rings for the biggest delegations (CA ≈ 50) */
  const SPIRAL = (() => {
    const dirs = [[0.5, 0.87], [-0.5, 0.87], [-1, 0], [-0.5, -0.87], [0.5, -0.87], [1, 0]];
    const out = [[0, 0]];
    for (let r = 1; r <= 4; r++) {
      let x = r, y = 0;
      for (const [dx, dy] of dirs) {
        for (let s = 0; s < r; s++) {
          out.push([x, y]);
          x += dx; y += dy;
        }
      }
    }
    return out;
  })();

  let usMapPromise = null;
  const loadUsMap = () => (usMapPromise = usMapPromise ||
    fetch(`../assets/us-states.svg?v=${BUST}`).then((r) => (r.ok ? r.text() : Promise.reject())));
  let districtMapPromise = null;   // 3.5 MB asset — fetched only when the House tab opens
  const loadDistrictMap = () => (districtMapPromise = districtMapPromise ||
    fetch(`../assets/us-districts.svg?v=${BUST}`).then((r) => (r.ok ? r.text() : Promise.reject())));
  /* the YAPms base map subdivides every state — nothing left over */
  const UNSPLIT = new Set();

  const OFFICE_LABEL = { senate: "Senate", governor: "Governor", house: "House" };

  let labelsOn = localStorage.getItem("gtLabels") === "1";

  function renderMap(sec) {
    const wrap = $("[data-gt-map-wrap]");
    const host = $("[data-gt-map]");
    const districtsBox = $("[data-gt-districts]");
    const note = $("[data-gt-map-note]");
    const drill = $("[data-gt-drill]");
    if (!host || !sec.map) return;
    let currentOffice = "senate";
    let drawSeq = 0;

    let tooltip = null;
    const killTip = () => { if (tooltip) { tooltip.remove(); tooltip = null; } };

    function showTip(target, title, entry) {
      killTip();
      tooltip = el("div", "gt-map-tooltip");
      tooltip.appendChild(el("h4", null, title));
      const rowEl = (label, valEl) => {
        const row = el("div", "row");
        row.appendChild(el("span", null, label));
        row.appendChild(valEl);
        tooltip.appendChild(row);
      };
      const fav = entry.fav;
      const cls = fav.party === "D" ? "d" : fav.party === "R" ? "r" : "";
      rowEl("Favorite", el("b", cls, `${fav.label} ${cents(fav.price)}`));
      if (entry.dem != null && !/\(D\)|Democrat/i.test(fav.label)) {
        rowEl("Democrat", el("b", "d", cents(entry.dem)));
      }
      if (entry.chg != null) {
        const up = entry.chg > 0;
        rowEl("Since yesterday", el("b", up ? "d" : "r", `${up ? "▲" : "▼"} ${Math.abs(Math.round(entry.chg * 100))}¢ D`));
      }
      if (entry.volume) rowEl("Volume", el("b", null, `$${(entry.volume / 1e3).toFixed(0)}k`));
      tooltip.appendChild(el("p", "hint", "Click for all of this state's markets ↗"));
      wrap.appendChild(tooltip);
      const tr = target.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
      let x = tr.left - wr.left + tr.width / 2 + 14;
      let y = tr.top - wr.top - 8;
      if (x + 240 > wr.width) x = Math.max(tr.left - wr.left - 248, 4);
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${Math.max(y, 0)}px`;
    }

    function openDrill(st) {
      if (!drill) return;
      drill.innerHTML = "";
      drill.hidden = false;
      const head = el("div", "drill-head");
      head.appendChild(el("h3", null, `${STATE_NAMES[st] || st} — 2026 markets`));
      const close = el("button", "gt-map-tab", "Close ✕");
      close.type = "button";
      close.addEventListener("click", () => { drill.hidden = true; });
      head.appendChild(close);
      drill.appendChild(head);
      const rows = [];
      for (const office of ["senate", "governor"]) {
        const e = sec.map[office] && sec.map[office][st];
        if (e) rows.push([`${OFFICE_LABEL[office]}`, e]);
      }
      for (const [dist, e] of Object.entries(sec.map.house || {}).sort()) {
        if (dist.startsWith(st)) rows.push([`House ${parseInt(dist.slice(3), 10)}`, e]);
      }
      if (!rows.length) drill.appendChild(el("p", "small-copy muted", "No listed markets for this state."));
      for (const [label, e] of rows) {
        const a = el("a", "drill-row");
        a.href = e.url; a.target = "_blank"; a.rel = "noopener";
        a.appendChild(el("span", "race", label));
        const cls = e.fav.party === "D" ? "d" : e.fav.party === "R" ? "r" : "";
        a.appendChild(el("span", `pq ${cls}`, `${e.fav.label} ${cents(e.fav.price)}`));
        a.appendChild(el("span", "vol", e.volume ? `$${(e.volume / 1e3).toFixed(0)}k` : ""));
        drill.appendChild(a);
      }
      drill.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function drawGeo(office, seq) {
      loadUsMap().then((text) => {
        if (seq !== drawSeq) return;       // user already switched tabs
        host.innerHTML = text;
        const svg = host.querySelector("svg");
        if (!svg) return;
        svg.removeAttribute("width");
        svg.removeAttribute("height");
        svg.setAttribute("viewBox", "0 0 959 593");
        svg.setAttribute("class", "gt-geomap");
        const inner = svg.querySelector("style");
        if (inner) inner.remove();          // kill the asset's own palette
        /* the asset layers border/separator paths over the states — keep them lines only */
        svg.querySelectorAll("path").forEach((path) => {
          const cls = (path.getAttribute("class") || "").trim().toLowerCase();
          if (!/^[a-z]{2}$/.test(cls)) {
            path.style.fill = "none";
            path.style.stroke = "var(--bg)";
            path.style.pointerEvents = "none";
          }
        });
        const data = sec.map[office] || {};
        for (const [st, entry] of Object.entries(data)) {
          const paths = svg.querySelectorAll(`.${st.toLowerCase()}`);
          paths.forEach((path) => {
            path.style.fill = partyColor(entry.fav.party, entry.fav.price);
            path.classList.add("live");
            path.addEventListener("mouseenter", () => showTip(path, `${STATE_NAMES[st]} · ${OFFICE_LABEL[office]}`, entry));
            path.addEventListener("mouseleave", killTip);
            path.addEventListener("click", () => openDrill(st));
          });
          if (labelsOn && paths.length) {
            const main = [...paths].sort((a, b) => {
              const ba = a.getBBox(), bb = b.getBBox();
              return bb.width * bb.height - ba.width * ba.height;
            })[0];
            const bb = main.getBBox();
            const txt = svgEl("text", { x: bb.x + bb.width / 2, y: bb.y + bb.height / 2 + 4, class: "geolbl" });
            txt.textContent = st;
            svg.appendChild(txt);
          }
        }
      }).catch(() => drawHexStates(office));  // asset missing → hex fallback
    }

    function drawHexStates(office) {
      const data = sec.map[office] || {};
      const S = 26, W = Math.sqrt(3) * S;
      const px = (col, row) => [(col + (row % 2 ? 0.5 : 0)) * (W + 3) + W, row * 1.5 * (S + 2) + S + 6];
      const svg = svgEl("svg", { viewBox: "0 0 645 350", class: "gt-hexmap" });
      for (const [st, [col, row]] of Object.entries(TILE_GRID)) {
        if (st === "DC") continue;
        const [cx, cy] = px(col, row);
        const entry = data[st];
        const poly = svgEl("polygon", { points: hexPoints(cx, cy, S - 1) });
        if (entry) {
          poly.setAttribute("fill", partyColor(entry.fav.party, entry.fav.price));
          poly.classList.add("live");
          poly.addEventListener("mouseenter", () => showTip(poly, `${STATE_NAMES[st]} · ${OFFICE_LABEL[office]}`, entry));
          poly.addEventListener("mouseleave", killTip);
          poly.addEventListener("click", () => openDrill(st));
        } else poly.setAttribute("class", "norace");
        svg.appendChild(poly);
        const t = svgEl("text", { x: cx, y: cy + 4, class: "hexlbl on-dark" });
        t.textContent = st;
        svg.appendChild(t);
      }
      host.appendChild(svg);
    }

    function houseChips(data) {
      if (!districtsBox) return;
      districtsBox.innerHTML = "";
      Object.entries(data)
        .filter(([, e]) => e.dem != null)
        .sort((a, b) => Math.abs(a[1].dem - 0.5) - Math.abs(b[1].dem - 0.5))
        .slice(0, 15)
        .forEach(([dist, e]) => {
          const a = el("a", "gt-district");
          a.href = e.url; a.target = "_blank"; a.rel = "noopener";
          a.appendChild(el("span", null, dist));
          const d = e.dem >= 0.5;
          a.appendChild(el("span", `pq ${d ? "d" : "r"}`, d ? `D ${cents(e.dem)}` : `R ${cents(1 - e.dem)}`));
          districtsBox.appendChild(a);
        });
    }

    function drawHouseDistricts(seq) {
      const data = sec.map.house || {};
      if (note) note.textContent = "Loading district boundaries… (cached after the first visit)";
      loadDistrictMap().then((text) => {
        if (seq !== drawSeq) return;
        host.innerHTML = text;
        const svg = host.querySelector("svg");
        if (!svg) throw new Error("bad svg");
        svg.removeAttribute("width");
        svg.removeAttribute("height");
        svg.setAttribute("class", "gt-distmap");
        let painted = 0;

        const paint = (node, entry, title, onClick) => {
          node.style.fill = partyColor(entry.fav.party, entry.fav.price);
          node.classList.add("live");
          node.addEventListener("mouseenter", () => showTip(node, title, entry));
          node.addEventListener("mouseleave", killTip);
          node.addEventListener("click", onClick);
        };

        for (const [dist, entry] of Object.entries(data)) {
          const st = dist.slice(0, 2);
          if (UNSPLIT.has(st)) continue;
          const n = parseInt(dist.slice(3), 10);
          const node = svg.querySelector(`[id="${st}-${n}"]`) || svg.querySelector(`[id="${st}"]`);
          if (!node) continue;
          paint(node, entry, `${STATE_NAMES[st]} ${n} · House`,
            () => window.open(entry.url, "_blank", "noopener"));
          painted++;
        }

        /* states the base map doesn't subdivide: shade by mean lean, click → drill */
        for (const st of UNSPLIT) {
          const dists = Object.entries(data).filter(([k]) => k.startsWith(st));
          if (!dists.length) continue;
          const mean = dists.reduce((s, [, e]) => s + (e.dem ?? 0.5), 0) / dists.length;
          const party = mean >= 0.5 ? "D" : "R";
          const pseudo = {
            fav: { label: `${dists.length} districts (avg lean)`, price: party === "D" ? mean : 1 - mean, party },
            dem: Math.round(mean * 1000) / 1000,
            volume: dists.reduce((s, [, e]) => s + (e.volume || 0), 0),
          };
          const node = svg.querySelector(`[id="${st}"]`);
          if (!node) continue;
          paint(node, pseudo, `${STATE_NAMES[st]} · House (not subdivided on this map)`,
            () => openDrill(st));
          painted += dists.length;
        }

        if (note) {
          note.textContent = `${Object.keys(data).length} of 435 House districts carry live winner markets, ` +
            "drawn on current 2026 boundaries (including this cycle's redistricting). Click a district to trade.";
        }
        if (!painted) throw new Error("nothing painted");
      }).catch(() => {
        if (seq !== drawSeq) return;
        host.innerHTML = "";
        drawHouseHex();
        if (note) note.textContent = `${Object.keys(data).length} House districts (cartogram fallback — boundary file unavailable).`;
      });
      houseChips(data);
    }

    function drawHouseHex() {
      const data = sec.map.house || {};
      const byState = {};
      for (const [dist, entry] of Object.entries(data)) {
        (byState[dist.slice(0, 2)] = byState[dist.slice(0, 2)] || []).push([dist, entry]);
      }
      const sHex = 7.5, sw = Math.sqrt(3) * sHex, SCALE = 2.6;
      const S = 26, W = Math.sqrt(3) * S;
      const px = (col, row) => [(col + (row % 2 ? 0.5 : 0)) * (W + 3) + W, row * 1.5 * (S + 2) + S + 6];
      const svg = svgEl("svg", { viewBox: "0 0 1640 950", class: "gt-hexmap house" });
      for (const [st, dists] of Object.entries(byState).sort()) {
        if (!TILE_GRID[st]) continue;
        const [col, row] = TILE_GRID[st];
        const [ax, ay] = px(col, row);
        const cx0 = ax * SCALE, cy0 = ay * SCALE;
        dists.sort((a, b) => a[0].localeCompare(b[0]));
        dists.slice(0, SPIRAL.length).forEach(([dist, entry], i) => {
          const cx = cx0 + SPIRAL[i][0] * (sw + 1.2);
          const cy = cy0 + SPIRAL[i][1] * (sw + 1.2);
          const poly = svgEl("polygon", {
            points: hexPoints(cx, cy, sHex - 0.4),
            fill: partyColor(entry.fav.party, entry.fav.price),
            class: "live",
          });
          poly.addEventListener("mouseenter", () => showTip(poly, `${STATE_NAMES[st]} ${parseInt(dist.slice(3), 10)} · House`, entry));
          poly.addEventListener("mouseleave", killTip);
          poly.addEventListener("click", () => window.open(entry.url, "_blank", "noopener"));
          svg.appendChild(poly);
        });
        const ringR = Math.ceil((Math.sqrt(Math.min(dists.length, SPIRAL.length)) - 1) / 1.6);
        const lbl = svgEl("text", { x: cx0, y: cy0 + (ringR + 1.6) * sw + 8, class: "hexstate" });
        lbl.textContent = st;
        svg.appendChild(lbl);
      }
      host.appendChild(svg);
    }


    function draw(office) {
      currentOffice = office;
      drawSeq++;
      host.innerHTML = "";
      if (districtsBox) districtsBox.innerHTML = "";
      if (drill) drill.hidden = true;
      killTip();
      if (office === "house") drawHouseHex();
      else drawGeo(office, drawSeq);
      if (note) {
        const n = Object.keys(sec.map[office] || {}).length;
        note.textContent = office === "house"
          ? `${n} House districts with live winner markets, as a cartogram — one hex per district, clustered by state. Click a hex to trade.`
          : `${n} states with live markets, shaded by the favorite's odds. Click a state for all of its races.`;
      }
    }

    const lblBtn = $("[data-gt-labels]");
    if (lblBtn) {
      lblBtn.classList.toggle("active", labelsOn);
      lblBtn.addEventListener("click", () => {
        labelsOn = !labelsOn;
        localStorage.setItem("gtLabels", labelsOn ? "1" : "0");
        lblBtn.classList.toggle("active", labelsOn);
        draw(currentOffice);
      });
    }

    /* color-blind palette toggle */
    const cbBtn = $("[data-gt-cb]");
    if (cbBtn) {
      const sync = () => { cbBtn.classList.toggle("active", paletteKey === "cb"); };
      sync();
      cbBtn.addEventListener("click", () => {
        paletteKey = paletteKey === "cb" ? "atlas" : "cb";
        localStorage.setItem("gtPalette", paletteKey);
        sync();
        draw(currentOffice);
      });
    }

    document.querySelectorAll("[data-gt-map-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-gt-map-tab]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        draw(btn.dataset.gtMapTab);
      });
    });
    draw("senate");
  }


  const ELECTION_DAY = new Date("2026-11-03T12:00:00");
  const daysToMidterms = () => Math.max(0, Math.ceil((ELECTION_DAY - Date.now()) / 864e5));

  function renderElections(sec) {
    document.querySelectorAll("[data-gt-countdown]").forEach((n) =>
      (n.textContent = `${daysToMidterms()} days to the midterms`));

    /* movers since yesterday */
    const moversBox = $("[data-gt-movers]");
    if (moversBox) {
      if ((sec.movers || []).length) {
        sec.movers.forEach((m) => {
          const a = el("a", "drill-row");
          a.href = m.url; a.target = "_blank"; a.rel = "noopener";
          a.appendChild(el("span", "race",
            `${STATE_NAMES[m.key.slice(0, 2)] || m.key} ${m.office === "house" ? "House " + parseInt(m.key.slice(3), 10) : OFFICE_LABEL[m.office]}`));
          const up = m.chg > 0;
          a.appendChild(el("span", `pq ${up ? "d" : "r"}`, `${up ? "▲" : "▼"} ${Math.abs(Math.round(m.chg * 100))}¢ D`));
          a.appendChild(el("span", "vol", cents(m.dem)));
          moversBox.appendChild(a);
        });
      } else {
        moversBox.appendChild(el("p", "small-copy muted",
          "No meaningful moves yet — day-over-day deltas start with the second edition."));
      }
    }

    /* balance-of-power scenarios */
    const balBox = $("[data-gt-balance]");
    const bal = sec.control && sec.control.balance;
    if (balBox && bal && bal.outcomes && bal.outcomes.length) {
      bal.outcomes.forEach((o) => {
        const d = el("a", "gt-scenario");
        d.href = bal.url; d.target = "_blank"; d.rel = "noopener";
        d.appendChild(el("span", "pct", cents(o.price)));
        d.appendChild(el("span", "lbl", o.label));
        balBox.appendChild(d);
      });
    } else if (balBox) {
      balBox.parentElement.hidden = true;
    }

    const ctrlBox = $("[data-gt-control-big]");
    if (ctrlBox && sec.control) {
      for (const [key, label] of [["senate", "U.S. Senate"], ["house", "U.S. House"]]) {
        const c = sec.control[key];
        if (!c) continue;
        const card = el("section", "card");
        card.appendChild(el("h2", null, `${label} control`));
        const row = controlRow("after the midterms", c);
        if (row) card.appendChild(row);
        ctrlBox.appendChild(card);
      }
    }

    renderMap(sec);

    const hot = $("[data-gt-hot]");
    if (hot) {
      sec.hot.slice(0, 3).forEach((h) => {
        const art = el("article", "gt-entry gt-hot");
        const h3 = el("h3");
        h3.appendChild(link(h.url, h.title));
        art.appendChild(h3);
        const meta = el("div", "meta");
        meta.appendChild(el("span", "vol", `Polymarket · $${(h.volume / 1e6).toFixed(1)}M traded`));
        art.appendChild(meta);
        if (h.outcomes.length) {
          const out = el("p", "out");
          h.outcomes.slice(0, 2).forEach((o, i) => {
            if (i) out.appendChild(document.createTextNode("  ·  "));
            out.appendChild(document.createTextNode(`${o.label} `));
            out.appendChild(el("b", null, cents(o.price)));
          });
          art.appendChild(out);
        }
        hot.appendChild(art);
      });
    }

    const news = $("[data-gt-elec-news]");
    if (news) sec.items.forEach((it, i) => news.appendChild(entry(it, { blurb: i < 3, big: i === 0 })));
  }

  /* ================= v4 extras ================= */

  /* shelf (saved-for-later) — shares the gtShelf contract with ui.js */
  const readShelf = () => { try { return JSON.parse(localStorage.getItem("gtShelf") || "[]"); } catch { return []; } };
  function shelfButton(it) {
    const btn = el("button", "shelfbtn");
    const saved = () => readShelf().some((s) => s.url === it.url);
    const sync = () => { btn.textContent = saved() ? "★" : "☆"; btn.title = saved() ? "Remove from saved" : "Save for later"; };
    sync();
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      let shelf = readShelf();
      if (saved()) shelf = shelf.filter((s) => s.url !== it.url);
      else shelf.push({ title: it.title, url: it.url, source: it.source, added: new Date().toISOString() });
      localStorage.setItem("gtShelf", JSON.stringify(shelf.slice(-200)));
      sync();
    });
    return btn;
  }

  /* new-since-yesterday dots on the front page */
  function frontNewDots(data, index) {
    if (wanted || index.length < 2) return;
    const prev = index[index.length - 2];
    grab(`../data/daily/${prev}.json`).then((y) => {
      const old = new Set();
      if (y.lead) old.add(y.lead.id);
      for (const sec of Object.values(y.sections || {})) {
        for (const it of (sec.items || [])) old.add(it.id);
        for (const it of (sec.papers || [])) old.add(it.id);
      }
      document.querySelectorAll('[id^="s-"]').forEach((art) => {
        if (!old.has(art.id.slice(2))) {
          const h3 = art.querySelector("h3");
          if (h3) {
            const dot = el("span", "newdot");
            dot.title = "New since yesterday's edition";
            h3.insertBefore(dot, h3.firstChild);
          }
        }
      });
    }).catch(() => {});
  }

  /* offline indicator */
  function setupOfflineChip() {
    const bar = document.querySelector(".gt-dateline");
    if (!bar) return;
    let chip = null;
    const syncNet = () => {
      if (!navigator.onLine && !chip) {
        chip = el("span", "tag", "offline · cached edition");
        bar.appendChild(chip);
      } else if (navigator.onLine && chip) {
        chip.remove(); chip = null;
      }
    };
    window.addEventListener("online", syncNet);
    window.addEventListener("offline", syncNet);
    syncNet();
  }

  /* j/k story navigation */
  function setupStoryKeys() {
    let idx = -1;
    const stories = () => [...document.querySelectorAll(".gt-entry")].filter((n) => n.offsetParent !== null);
    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
      const list = stories();
      if (!list.length) return;
      if (e.key === "j" || e.key === "k") {
        document.querySelectorAll(".gt-entry.knav").forEach((n) => n.classList.remove("knav"));
        idx = e.key === "j" ? Math.min(idx + 1, list.length - 1) : Math.max(idx - 1, 0);
        list[idx].classList.add("knav");
        list[idx].scrollIntoView({ block: "center", behavior: "smooth" });
      }
      if ((e.key === "o" || e.key === "Enter") && idx >= 0 && list[idx]) {
        const a = list[idx].querySelector("h3 a");
        if (a && e.target.tagName !== "A") window.open(a.href, "_blank", "noopener");
      }
    });
  }

  /* elections: history chart, seat histogram, tipping point, next-vote chip */
  const SENATE_BASELINE = { notUpD: 34, notUpR: 31, dNeeds: 51 };  // VP tiebreak is R; edit if reality shifts

  function renderExtrasElections(sec) {
    const tip = $("[data-gt-tipping]");
    if (tip) {
      const races = Object.entries(sec.map.senate || {})
        .filter(([, e]) => e.dem != null)
        .sort((a, b) => b[1].dem - a[1].dem);
      const need = SENATE_BASELINE.dNeeds - SENATE_BASELINE.notUpD;
      if (races.length >= need && need > 0) {
        const [st, e] = races[need - 1];
        tip.innerHTML = "";
        tip.append("Tipping point: the majority runs through ",
          link(e.url, `${STATE_NAMES[st]} (D ${cents(e.dem)})`),
          ` — seat #${SENATE_BASELINE.dNeeds} for Democrats, counting ${SENATE_BASELINE.notUpD} held seats not on the ballot.`);
      }
    }

    const nextVote = $("[data-gt-nextvote]");
    if (nextVote) {
      grab("../data/daily/primaries.json").then((cal) => {
        const today = new Date().toISOString().slice(0, 10);
        const next = (cal.events || []).filter((e) => e.date >= today)
          .sort((a, b) => a.date.localeCompare(b.date))[0];
        if (next) {
          const days = Math.ceil((new Date(next.date + "T12:00:00") - Date.now()) / 864e5);
          nextVote.textContent = `Next on the calendar: ${next.label} · ${longDate(next.date)} · ${days}d`;
        }
      }).catch(() => {});
    }
  }

  /* markets: watchlist P&L line */
  function renderWatchlist(sec) {
    const box = $("[data-gt-pnl]");
    if (!box || !sec.snapshot) return;
    grab("../data/holdings.json").then((h) => {
      const bySym = {};
      sec.snapshot.forEach((q) => (bySym[q.sym] = q));
      let pnl = 0, used = 0;
      for (const pos of h.positions || []) {
        const q = bySym[pos.sym];
        if (q) { pnl += pos.weight * q.chgPct; used += pos.weight; }
      }
      if (!used) return;
      box.hidden = false;
      const v = pnl / used;
      const b = el("b", v >= 0 ? "up" : "down", `${v >= 0 ? "+" : ""}${v.toFixed(2)}% today`);
      box.append("Watchlist sleeve: ", b,
        el("span", "muted", ` · weighted across ${Math.round(used * 100)}% of holdings.json`));
    }).catch(() => {});
  }

  /* sports: form strips, rivalry tracker, Jupiter corner */
  function renderExtrasSports(sports) {
    document.querySelectorAll(".gt-team-desk").forEach((card) => {
      const label = card.querySelector("h3");
      const team = sports && sports.teams.find((t) => t.label === (label && label.textContent));
      if (!team || !(team.form || []).length) return;
      const strip = el("span", "form-strip");
      team.form.slice(-5).forEach((g) => {
        const i = el("i", g.res === "W" ? "w" : g.res === "L" ? "l" : "d");
        i.title = `${g.res} ${g.score} ${g.home ? "vs" : "at"} ${g.opp}`;
        strip.appendChild(i);
      });
      const head = card.querySelector(".desk-head .who");
      if (head) head.appendChild(strip);
    });

    const riv = $("[data-gt-rivalry]");
    if (riv) {
      const isUNC = (g) => /north carolina|unc|tar heels/i.test(`${g.opp} ${g.oppAbbr || ""}`) && (g.oppAbbr || "") !== "UNCW";
      Promise.allSettled([grab("../data/history/2025.json"), grab("../data/history/2026.json")]).then((res) => {
        const games = res.flatMap((r) => (r.status === "fulfilled" ? r.value.games : []))
          .filter((g) => g.team === "duke-mbb" && isUNC(g))
          .sort((a, b) => a.date.localeCompare(b.date));
        const w = games.filter((g) => g.res === "W").length;
        if (games.length) {
          riv.appendChild(el("p", "blurb",
            `Duke leads the ledger ${w}–${games.length - w} since 2025. Last meeting: ` +
            `${games[games.length - 1].res === "W" ? "W" : "L"} ${games[games.length - 1].score}.`));
        }
        const next = sports && sports.teams.find((t) => t.key === "duke-mbb");
        const upcoming = next && (next.next || []).find(isUNC);
        if (upcoming) {
          const days = Math.ceil((new Date(upcoming.date) - Date.now()) / 864e5);
          riv.appendChild(el("p", "blurb", `Next chapter: ${upcoming.home ? "vs" : "at"} UNC in ${days} days.`));
        } else if (!games.length) {
          riv.appendChild(el("p", "small-copy muted", "The rivalry sleeps until the schedule drops."));
        }
      });
    }

    const jup = $("[data-gt-jupiter]");
    if (jup) {
      grab("../data/jupiter.json").then((j) => {
        const d = j.duke || {};
        const facts = [["Rating", d.rating], ["Proj. seed", d.projSeed], ["Title odds", d.titleOdds]]
          .filter(([, v]) => v != null);
        if (facts.length) {
          const row = el("div", "gt-mini-quotes");
          facts.forEach(([k, v]) => {
            const lineEl = el("div", "gt-quote-line");
            lineEl.appendChild(el("span", "lbl", k));
            lineEl.appendChild(el("span", "val", String(v)));
            row.appendChild(lineEl);
          });
          jup.appendChild(row);
        }
        if (j.line) jup.appendChild(el("p", "small-copy muted", j.line));
      }).catch(() => { jup.parentElement.hidden = true; });
    }
  }

  /* ai: benchmark watch */
  function renderBenchmarks() {
    const box = $("[data-gt-benchmarks]");
    if (!box) return;
    grab("../data/daily/benchmarks.json").then((b) => {
      (b.rows || []).forEach((r) => {
        const row = el("div", "gt-quote-line");
        row.appendChild(el("span", "lbl", `${r.model} · ${r.bench}`));
        row.appendChild(el("span", "val", r.score));
        box.appendChild(row);
      });
    }).catch(() => { box.parentElement.hidden = true; });
  }

  /* ---------- keyboard: 1–5 pages, ←/→ archive ---------- */
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= PAGES.length) location.href = PAGES[n - 1] + location.search;
    if (e.key === "ArrowLeft") { const a = $("[data-gt-prev]"); if (a && a.href && !a.classList.contains("disabled")) location.href = a.href; }
    if (e.key === "ArrowRight") { const a = $("[data-gt-next]"); if (a && a.href && !a.classList.contains("disabled")) location.href = a.href; }
  });
})();
