(async () => {
  let data;
  try {
    data = await loadData("sports");
  } catch (err) {
    document.querySelector("[data-sports-error]").hidden = false;
    return;
  }

  const el = (sel) => document.querySelector(sel);
  const RESULT_WORD = { W: "Won", L: "Lost", D: "Drew" };
  /* how many teams the standing rank is out of (division / table size) */
  const STANDING_OF = { "duke-mbb": 18, "duke-fb": 17, mavs: 5, mets: 5, spurs: 20, colts: 4, canes: 8, lafc: 30 };

  const fmtDate = (iso) =>
    new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const fmtTime = (iso) =>
    new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const isToday = (iso) => new Date(iso).toDateString() === new Date().toDateString();
  const vsAt = (g) => (g.home ? "vs" : "at");
  const daysUntil = (iso) => {
    const d = new Date(iso);
    const days = Math.round((new Date(d.toDateString()) - new Date(new Date().toDateString())) / 864e5);
    return days <= 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
  };

  /* updated stamp + freshness guard */
  const updatedEl = el("[data-updated]");
  const hoursAgo = Math.round((Date.now() - new Date(data.updated).getTime()) / 36e5);
  updatedEl.textContent =
    hoursAgo < 1 ? "updated just now" :
    hoursAgo < 48 ? `updated ${hoursAgo}h ago` :
    `updated ${fmtDate(data.updated)}`;
  if (hoursAgo > 24) {
    updatedEl.textContent += " — may be stale";
    updatedEl.style.color = "var(--bad)";
  }

  /* month record across all teams */
  const now = new Date();
  let mw = 0, ml = 0, md = 0;
  for (const t of data.teams) {
    for (const g of t.form) {
      const d = new Date(g.date);
      if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) {
        if (g.res === "W") mw++;
        else if (g.res === "L") ml++;
        else md++;
      }
    }
  }
  if (mw + ml + md) {
    const month = now.toLocaleDateString(undefined, { month: "long" });
    el("[data-month-record]").textContent =
      `${month} so far, all teams: ${mw}–${ml}${md ? `–${md}` : ""}`;
  }

  /* today ticker */
  const todayItems = [];
  for (const t of data.teams) {
    const last = t.form[t.form.length - 1];
    if (last && isToday(last.date)) {
      todayItems.push(
        `<div class="score-line"><span class="score-match"><strong>${t.label}</strong> ${last.score} ${vsAt(last)} ${last.opp}</span><span class="score-status ${last.res === "W" ? "win" : last.res === "L" ? "loss" : ""}">${RESULT_WORD[last.res]}</span></div>`
      );
    }
    for (const g of t.next) {
      if (isToday(g.date)) {
        todayItems.push(
          `<div class="score-line" data-live="${t.key}"><span class="score-match"><strong>${t.label}</strong> ${vsAt(g)} ${g.opp}</span><span class="score-status">${g.tbd ? "TBD" : fmtTime(g.date)}</span></div>`
        );
      }
    }
  }
  if (todayItems.length) {
    el("[data-today-card]").hidden = false;
    el("[data-today]").innerHTML = todayItems.join("");
  }

  /* team cards by tier */
  const formStrip = (form) =>
    `<span class="form-strip">${form
      .map(
        (g) =>
          `<i class="${g.res.toLowerCase()}" title="${RESULT_WORD[g.res]} ${g.score} ${vsAt(g)} ${g.opp} · ${fmtDate(g.date)}"></i>`
      )
      .join("")}</span>`;

  const recentList = (form) =>
    `<details class="recent-results"><summary>Recent results</summary><ul>${form
      .slice()
      .reverse()
      .map(
        (g) =>
          `<li><span><strong class="${g.res === "W" ? "delta-up" : g.res === "L" ? "delta-down" : ""}">${g.res} ${g.score}</strong> ${vsAt(g)} ${g.opp}</span><span>${fmtDate(g.date)}</span></li>`
      )
      .join("")}</ul></details>`;

  const rankBar = (t) => {
    const rank = parseInt(t.standing, 10);
    const of = STANDING_OF[t.key];
    if (!rank || !of) return "";
    const pct = ((rank - 0.5) / of) * 100;
    return `<span class="rank-bar" title="${rank} of ${of}"><i style="left:${pct.toFixed(1)}%"></i></span>`;
  };

  const card = (t) => {
    const last = t.form[t.form.length - 1];
    const next = t.next[0];
    const standing = t.standing.replace("English Premier League", "the Premier League");
    const context = standing.toLowerCase().includes(t.league.toLowerCase())
      ? standing
      : `${t.league}${standing ? ` · ${standing}` : ""}`;
    const color = /^[0-9a-f]{6}$/i.test(t.color || "") ? `style="--team:#${t.color}"` : "";
    return `
    <article class="team-card" ${color}>
      <div class="team-head">
        ${t.logo ? `<img src="${t.logo}" alt="" loading="lazy">` : ""}
        <div class="team-id">
          <h3>${t.name}</h3>
          <span class="muted small-copy">${context}</span>
        </div>
        ${rankBar(t)}
        ${t.record ? `<span class="team-record">${t.record}</span>` : ""}
      </div>
      <div class="team-form">
        ${t.form.length ? formStrip(t.form) : `<span class="small-copy muted">No recent games</span>`}
      </div>
      ${t.form.length ? recentList(t.form) : ""}
      <div class="team-lines">
        ${last ? `<div class="team-line"><span>Last</span><strong class="${last.res === "W" ? "delta-up" : last.res === "L" ? "delta-down" : ""}">${RESULT_WORD[last.res]} ${last.score}</strong><span class="muted">${vsAt(last)} ${last.opp} · ${fmtDate(last.date)}</span></div>` : ""}
        ${next
          ? `<div class="team-line"><span>Next</span><strong>${vsAt(next)} ${next.opp}</strong><span class="muted">${fmtDate(next.date)}${next.tbd ? "" : ` · ${fmtTime(next.date)}`} · ${daysUntil(next.date)}</span></div>`
          : `<div class="team-line"><span>Next</span><span class="muted">Off-season${t.record ? ` · finished ${t.record}` : ""}</span></div>`}
      </div>
    </article>`;
  };

  for (const tier of [1, 2, 3]) {
    const teams = data.teams.filter((t) => t.tier === tier);
    el(`[data-tier="${tier}"]`).innerHTML = teams.map(card).join("");
  }

  /* upcoming schedule table */
  const fixtures = data.teams
    .flatMap((t) => t.next.map((g) => ({ ...g, team: t })))
    .sort((a, b) => a.date.localeCompare(b.date));

  const select = el("[data-upcoming-filter]");
  const withGames = data.teams.filter((t) => t.next.length);
  select.innerHTML =
    `<option value="">All teams</option>` +
    withGames.map((t) => `<option value="${t.key}">${t.label}</option>`).join("");

  const renderUpcoming = () => {
    const key = select.value;
    const rows = fixtures.filter((f) => !key || f.team.key === key);
    el("[data-upcoming-rows]").innerHTML = rows.length
      ? rows
          .map(
            (f) => `
          <tr>
            <td>${fmtDate(f.date)}</td>
            <td style="text-align:left;"><strong>${f.team.label}</strong> <span class="muted">${vsAt(f)}</span> ${f.opp}</td>
            <td>${f.team.league}</td>
            <td>${f.tbd ? "TBD" : fmtTime(f.date)}</td>
          </tr>`
          )
          .join("")
      : `<tr><td colspan="4" class="muted">No scheduled games yet.</td></tr>`;
    el("[data-upcoming-note]").textContent = key
      ? `${rows.length} scheduled game${rows.length === 1 ? "" : "s"}`
      : `next ${rows.length} games across all teams — off-season schedules appear as leagues publish them`;
  };
  select.addEventListener("change", renderUpcoming);
  renderUpcoming();

  /* live scores — on game days, poll ESPN's scoreboard from the browser */
  const liveTeams = data.teams.filter((t) => t.next.some((g) => isToday(g.date)));
  if (liveTeams.length) {
    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      for (const path of [...new Set(liveTeams.map((t) => t.path))]) {
        try {
          const res = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${path}/scoreboard`);
          if (!res.ok) continue;
          const board = await res.json();
          for (const t of liveTeams.filter((x) => x.path === path)) {
            const ev = (board.events || []).find((e) =>
              e.competitions?.[0]?.competitors?.some((c) => c.team.id === t.id)
            );
            const comp = ev?.competitions?.[0];
            const status = ev?.status?.type;
            if (!comp || !status || !status.state || status.state === "pre") continue;
            const us = comp.competitors.find((c) => c.team.id === t.id);
            const them = comp.competitors.find((c) => c.team.id !== t.id);
            const line = document.querySelector(`[data-live="${t.key}"]`);
            if (!line || !us || !them) continue;
            line.querySelector(".score-match").innerHTML =
              `<strong>${t.label}</strong> ${us.score}-${them.score} ${us.homeAway === "home" ? "vs" : "at"} ${t.next.find((g) => isToday(g.date))?.opp ?? them.team.shortDisplayName}`;
            const st = line.querySelector(".score-status");
            st.textContent = status.state === "in" ? `LIVE · ${status.shortDetail}` : status.shortDetail;
            st.classList.toggle("win", status.completed && us.winner === true);
            st.style.color = status.state === "in" ? "var(--good)" : "";
          }
        } catch (e) { /* scoreboard hiccups are fine — committed data remains */ }
      }
    };
    poll();
    setInterval(poll, 120000);
  }
})();
