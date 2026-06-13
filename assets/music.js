(async () => {
  let data;
  try {
    data = await loadData("music");
  } catch (err) {
    document.querySelector("[data-music-error]").hidden = false;
    return;
  }

  const el = (sel) => document.querySelector(sel);

  /* now practicing — cards with a phase badge */
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

  /* repertoire — cards split into Concertos / Solo works per instrument */
  const isConcerto = (w) => /concerto/i.test(`${w.work} ${w.detail || ""}`);
  const repCard = (w) => `
    <article class="rep-card">
      <span class="rc-composer">${w.composer}</span>
      <span class="rc-work">${w.work}</span>
      ${w.detail ? `<span class="rc-detail">${w.detail}</span>` : ""}
      <div class="rc-foot"><span>comp. ${w.composed}</span><span class="rc-year">${w.learned}</span></div>
    </article>`;
  const repGroup = (label, works) =>
    works.length
      ? `
      <div class="rep-group">
        <p class="eyebrow">${label} <span class="count">${works.length}</span></p>
        <div class="rep-grid">${works.map(repCard).join("")}</div>
      </div>`
      : "";
  const renderRepertoire = (sel, works) => {
    el(sel).innerHTML =
      repGroup("Concertos", works.filter(isConcerto)) +
      repGroup("Solo works", works.filter((w) => !isConcerto(w)));
  };
  renderRepertoire("[data-piano-tables]", data.piano);
  renderRepertoire("[data-violin-tables]", data.violin);

  /* future repertoire — wishlist cards */
  el("[data-planned]").innerHTML =
    `<div class="wish-grid">${data.planned
      .map(
        (p) => `
        <article class="wish-card">
          <div class="wc-top">
            <span class="wc-composer">${p.composer}</span>
            <span class="tag neutral">${p.category}</span>
          </div>
          <span class="wc-work">${p.work}${p.detail ? ` · ${p.detail}` : ""}${p.composed ? ` (${p.composed})` : ""}</span>
        </article>`
      )
      .join("")}</div>`;

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
