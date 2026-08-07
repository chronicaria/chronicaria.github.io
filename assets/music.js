(async () => {
  let data;
  try {
    data = await loadData("music");
  } catch (err) {
    document.querySelector("[data-music-error]").hidden = false;
    return;
  }

  const el = (sel) => document.querySelector(sel);

  /* now practicing */
  el("[data-working]").innerHTML =
    `<div class="practice-grid">${data.working
      .map(
        (w) => `
        <article class="practice-card">
          <span class="pc-composer">${w.composer}</span>
          <span class="pc-work">${w.work}</span>
          <span class="pc-detail">${w.detail ? `${w.detail} · ` : ""}comp. ${w.composed}</span>
        </article>`
      )
      .join("")}</div>`;

  /* repertoire — one aligned table per instrument; each tbody is a group,
     hairline rules fall between groups, not around every work */
  const yr = (v) => (v == null ? "—" : String(v).replace("<", "&lt;"));
  const repRow = (w, learned) => `
    <tr>
      <td class="rep-comp">${w.composer}</td>
      <td class="rep-work">${w.work}${w.detail ? ` <span class="rep-detail">${w.detail}</span>` : ""}</td>
      <td class="rep-num">${yr(w.composed)}</td>
      ${learned ? `<td class="rep-num">${yr(w.learned)}</td>` : ""}
    </tr>`;
  const repTable = (groups, learned) => `
    <table class="rep-table">
      <thead><tr>
        <th>Composer</th><th>Work</th><th class="rep-num">Comp.</th>${learned ? '<th class="rep-num">Learned</th>' : ""}
      </tr></thead>
      ${groups.map((g) => `<tbody>${g.map((w) => repRow(w, learned)).join("")}</tbody>`).join("")}
    </table>`;
  /* consecutive works sharing a learned year form one group */
  const byLearned = (works) =>
    works.reduce((gs, w) => {
      const g = gs[gs.length - 1];
      if (g && g[0].learned === w.learned) g.push(w);
      else gs.push([w]);
      return gs;
    }, []);
  el("[data-piano-tables]").innerHTML = repTable(byLearned(data.piano), true);
  el("[data-violin-tables]").innerHTML = repTable(byLearned(data.violin), true);

  /* future repertoire — same table, subsectioned by type (one row per group
     so the hairlines land between every work) */
  const plannedGroup = (label, works) =>
    works.length
      ? `
      <div class="rep-group">
        <p class="eyebrow">${label} <span class="count">${works.length}</span></p>
        ${repTable(works.map((w) => [w]), false)}
      </div>`
      : "";
  el("[data-planned]").innerHTML =
    plannedGroup("Concertos", data.planned.filter((p) => p.category === "Concerto")) +
    plannedGroup("Solo works", data.planned.filter((p) => p.category !== "Concerto"));

  /* the repertoire diagonal — composed year (x) vs year learned (y), with an
     OLS fit drawn only across the observed composed-year range. Works whose
     learned year is logged as "<2020" have no usable y and are excluded. */
  {
    const pts = [];
    for (const [inst, works] of [["piano", data.piano], ["violin", data.violin]])
      for (const w of works)
        if (w.composed && /^\d{4}$/.test(w.learned || "")) pts.push({ x: w.composed, y: +w.learned, inst });
    const dropped = [...data.piano, ...data.violin].filter((w) => !/^\d{4}$/.test(w.learned || "")).length;
    const n = pts.length;
    const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
    const mx = mean(pts.map((p) => p.x));
    const my = mean(pts.map((p) => p.y));
    let sxx = 0, sxy = 0, syy = 0;
    for (const p of pts) {
      sxx += (p.x - mx) ** 2;
      sxy += (p.x - mx) * (p.y - my);
      syy += (p.y - my) ** 2;
    }
    const fit = n >= 5 && sxx > 0 && syy > 0;
    const slope = fit ? sxy / sxx : 0;
    const icept = my - slope * mx;
    const r2 = fit ? (sxy * sxy) / (sxx * syy) : 0;

    const W = 640, H = 300, ML = 50, MR = 14, MT = 26, MB = 34;
    const dx0 = Math.min(...pts.map((p) => p.x)), dx1 = Math.max(...pts.map((p) => p.x));
    const x0 = dx0 - 6, x1 = dx1 + 6;
    const y0 = Math.min(...pts.map((p) => p.y)) - 0.4, y1 = Math.max(...pts.map((p) => p.y)) + 0.4;
    const X = (v) => ML + ((v - x0) / (x1 - x0)) * (W - ML - MR);
    const Y = (v) => H - MB - ((v - y0) / (y1 - y0)) * (H - MT - MB);
    const xticks = [], yticks = [];
    for (let t = Math.ceil(x0 / 20) * 20; t <= x1; t += 20) xticks.push(t);
    for (let t = Math.ceil(y0); t <= y1; t++) yticks.push(t);

    el("[data-rep-diagonal]").innerHTML = `
      <svg class="music-diag" viewBox="0 0 ${W} ${H}" role="img"
        aria-label="Scatter plot of composed year against year learned, piano and violin">
        ${yticks.map((t) => `<line x1="${ML}" y1="${Y(t)}" x2="${W - MR}" y2="${Y(t)}" stroke="var(--rule)" stroke-width="1"/>
          <text x="${ML - 7}" y="${Y(t) + 3}" text-anchor="end">${t}</text>`).join("")}
        ${xticks.map((t) => `<line x1="${X(t)}" y1="${H - MB}" x2="${X(t)}" y2="${H - MB + 5}" stroke="var(--rule-strong)" stroke-width="1"/>
          <text x="${X(t)}" y="${H - MB + 16}" text-anchor="middle">${t}</text>`).join("")}
        <line x1="${ML}" y1="${H - MB}" x2="${W - MR}" y2="${H - MB}" stroke="var(--rule-strong)" stroke-width="1"/>
        <text x="${(ML + W - MR) / 2}" y="${H - 4}" text-anchor="middle">composed</text>
        <text x="${ML - 7}" y="12" text-anchor="end">learned</text>
        ${fit ? `<line x1="${X(dx0)}" y1="${Y(icept + slope * dx0)}" x2="${X(dx1)}" y2="${Y(icept + slope * dx1)}" stroke="var(--royal)" stroke-width="1.5"/>` : ""}
        ${pts.map((p) => p.inst === "piano"
          ? `<rect x="${X(p.x) - 3.5}" y="${Y(p.y) - 3.5}" width="7" height="7" fill="var(--prussian)"/>`
          : `<rect x="${X(p.x) - 3.5}" y="${Y(p.y) - 3.5}" width="7" height="7" fill="none" stroke="var(--prussian)" stroke-width="1.4"/>`).join("")}
      </svg>
      <p class="music-diag-note">■ piano · □ violin · n = ${n}${
        fit ? ` — OLS fit: ${slope >= 0 ? "+" : "−"}${Math.abs(slope * 100).toFixed(1)} yr learned per century composed, R² = ${r2.toFixed(2)}` : " — too few dated points for a fit"
      }.${dropped ? ` ${dropped} works learned before 2020 are excluded — no year on record.` : ""}</p>`;
  }

  /* ensembles */
  el("[data-ensembles]").innerHTML = data.ensembles
    .map(
      (e) => `
      <article class="entry">
        <div class="entry-head">
          <h3>${e.name} — ${e.role}</h3>
          <span class="when">${e.when}</span>
        </div>
        ${e.highlight ? `<p style="margin:.3rem 0 0;"><span class="tag">${e.highlight}</span></p>` : ""}
        <ul>${e.details.map((d) => `<li>${d}</li>`).join("")}</ul>
      </article>`
    )
    .join("");
})();
