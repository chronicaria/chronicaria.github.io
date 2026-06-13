(async () => {
  const el = (sel) => document.querySelector(sel);
  const fmtDate = (iso) =>
    new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

  /* music */
  loadData("music")
    .then((m) => {
      el("[data-now-music]").innerHTML = m.working
        .map(
          (w) => `<p class="small-copy" style="margin:0 0 .3rem;"><strong>${w.composer}</strong> — ${w.work}${w.phase ? ` <span class="muted">· ${w.phase}</span>` : ""}</p>`
        )
        .join("");
    })
    .catch(() => { el("[data-now-music]").innerHTML = `<p class="muted small-copy">unavailable</p>`; });

  /* book */
  loadData("books")
    .then((b) => {
      const c = b.current;
      const pct = Math.round((c.chapter / c.chapters) * 100);
      el("[data-now-book]").innerHTML = `
        <p class="small-copy" style="margin:0 0 .35rem;"><strong>${c.title}</strong> — ${c.author}</p>
        <div class="progress"><span style="width:${pct}%;"></span></div>
        <p class="muted small-copy" style="margin:.3rem 0 0;">chapter ${c.chapter} of ${c.chapters} · ${pct}%</p>`;
    })
    .catch(() => { el("[data-now-book]").innerHTML = `<p class="muted small-copy">unavailable</p>`; });

  /* sports */
  loadData("sports")
    .then((s) => {
      const games = s.teams
        .flatMap((t) => t.next.map((g) => ({ ...g, label: t.label })))
        .filter((g) => new Date(g.date).getTime() > Date.now() - 6 * 36e5)
        .sort((a, b) => a.date.localeCompare(b.date))
        .slice(0, 3);
      el("[data-now-sports]").innerHTML = games.length
        ? games
            .map(
              (g) => `<p class="small-copy" style="margin:0 0 .3rem;"><strong>${g.label}</strong> ${g.home ? "vs" : "at"} ${g.opp} <span class="muted">· ${fmtDate(g.date)}</span></p>`
            )
            .join("")
        : `<p class="muted small-copy">Everyone is off-season. Suspiciously peaceful.</p>`;
    })
    .catch(() => { el("[data-now-sports]").innerHTML = `<p class="muted small-copy">unavailable</p>`; });
})();
