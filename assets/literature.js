(async () => {
  let data;
  try {
    data = await loadData("books");
  } catch (err) {
    document.querySelector("[data-books-error]").hidden = false;
    return;
  }

  const el = (sel) => document.querySelector(sel);

  /* currently reading — cover + progress ring */
  const cur = data.current;
  if (cur) {
    const pct = Math.round((cur.chapter / cur.chapters) * 100);
    const r = 22, C = 2 * Math.PI * r, off = C * (1 - pct / 100);
    el("[data-current]").innerHTML = `
      <article class="now-reading">
        <div class="nr-cover">
          <span class="nr-c-title">${cur.title}</span>
          <span class="nr-c-author">${cur.author}</span>
        </div>
        <div class="nr-body">
          <h3>${cur.title}</h3>
          <p class="nr-meta">${cur.author} · ${cur.published} · ${cur.pages.toLocaleString()} pages</p>
          ${cur.note ? `<p class="nr-note">${cur.note}</p>` : ""}
          <div class="nr-progress">
            <svg class="nr-ring" width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
              <circle class="track" cx="28" cy="28" r="${r}" stroke-width="5"></circle>
              <circle class="bar" cx="28" cy="28" r="${r}" stroke-width="5"
                stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"></circle>
            </svg>
            <div class="nr-prog-text">
              <b>${pct}% through</b>
              <span>Chapter ${cur.chapter} of ${cur.chapters}</span>
            </div>
          </div>
        </div>
      </article>`;
  }

  /* planned reads — cards */
  const plannedWrap = el("[data-planned-wrap]");
  if (plannedWrap && (data.planned || []).length) {
    plannedWrap.hidden = false;
    el("[data-planned]").innerHTML =
      `<div class="wish-grid">${data.planned
        .map(
          (b) => `
        <article class="wish-card">
          <div class="wc-top">
            <span class="wc-composer">${b.title}</span>
            <span class="tag neutral">${b.published}</span>
          </div>
          <span class="wc-work">${b.author}${b.pages ? ` · ${b.pages.toLocaleString()} pages` : ""}</span>
        </article>`
        )
        .join("")}</div>`;
  }

  /* year selector + shelf + log */
  const years = Object.keys(data.years).sort().reverse();
  const select = el("[data-year-filter]");
  select.innerHTML = years.map((y) => `<option value="${y}">${y}</option>`).join("");
  const onlyOneYear = years.length < 2;
  select.hidden = onlyOneYear;
  const yearLabel = select.closest(".select-label");
  if (yearLabel) yearLabel.hidden = onlyOneYear;   // don't show a lone "Year" label

  const renderYear = () => {
    const year = select.value || years[0];
    const books = data.years[year] || [];
    const isCurrentYear = year === String(new Date().getFullYear());

    /* shelf: one spine per finished book (height/width scale with page count) */
    const spine = (b) =>
      `<span class="spine" title="${b.title} — ${b.author}${b.rating ? ` · ${b.rating}/10` : ""}"
        style="height:${(2 + Math.min((b.pages || 300) / 400, 2.2)).toFixed(2)}rem;
               width:${(0.8 + Math.min((b.pages || 300) / 1000, 0.9)).toFixed(2)}rem;"></span>`;
    const currentSpine =
      isCurrentYear && cur
        ? `<span class="spine now" title="${cur.title} — in progress"
            style="height:${(2 + Math.min(cur.pages / 400, 2.2)).toFixed(2)}rem;
                   width:${(0.8 + Math.min(cur.pages / 1000, 0.9)).toFixed(2)}rem;"></span>`
        : "";
    const shelfEl = el("[data-shelf]");
    const spines = books.map(spine).join("") + currentSpine;
    shelfEl.classList.toggle("is-empty", !spines);
    shelfEl.innerHTML = spines || "The shelf fills as books get logged this year.";

    /* stats */
    const finished = books.length;
    const pages = books.reduce((s, b) => s + (b.pages || 0), 0);
    el("[data-shelf-note]").textContent = finished
      ? `${finished} book${finished === 1 ? "" : "s"} finished · ${pages.toLocaleString()} pages` +
        (isCurrentYear && cur ? ` · 1 in progress` : "")
      : isCurrentYear && cur
        ? `Nothing finished yet this year — the highlighted spine is in progress, and it's ${cur.pages.toLocaleString()} pages, so have some patience.`
        : "Nothing logged this year.";

    /* log table */
    const wrap = el("[data-log-wrap]");
    wrap.hidden = !finished;
    if (finished) {
      el("[data-log-rows]").innerHTML = books
        .map(
          (b) => `
        <tr>
          <td style="text-align:left;"><strong>${b.title}</strong></td>
          <td style="text-align:left;">${b.author}</td>
          <td>${b.pages ?? "—"}</td>
          <td>${b.finished ?? "—"}</td>
          <td>${b.rating != null ? `${b.rating}/10` : "—"}</td>
          <td style="text-align:left; white-space:normal;" class="muted">${b.take ?? ""}</td>
        </tr>`
        )
        .join("");
    }
  };
  select.addEventListener("change", renderYear);
  renderYear();
})();
