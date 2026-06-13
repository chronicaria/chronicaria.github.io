(() => {
  const burger = document.querySelector("[data-nav-burger]");
  const nav = document.querySelector(".primary-nav");
  if (burger && nav) {
    burger.addEventListener("click", () => nav.classList.toggle("open"));
  }

  /* dropdown menus: click-to-toggle (touch), hover handled in CSS */
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

  const year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();

  /* theme toggle — the <head> snippet sets the initial theme pre-paint */
  const toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    const apply = () => {
      toggle.textContent = document.documentElement.dataset.theme === "light" ? "◑ dark mode" : "◐ light mode";
    };
    apply();
    toggle.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
      apply();
    });
  }

  /* keyboard page switching: 1–6, in nav order */
  const PAGES = ["index.html", "daily/index.html", "sports.html", "music.html", "literature.html"];
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= PAGES.length) location.href = PAGES[n - 1];
  });

  /* hover anchor links on identified sections */
  document.querySelectorAll("section[id] > h2, section[id] > .section-title-row > h2").forEach((h2) => {
    const id = h2.closest("section[id]").id;
    const a = document.createElement("a");
    a.className = "hash-link";
    a.href = `#${id}`;
    a.textContent = "#";
    a.setAttribute("aria-label", `Link to ${id} section`);
    h2.appendChild(a);
  });

  /* game-day dot on the Sports nav link */
  const sportsLink = document.querySelector('.primary-nav a[href="sports.html"]');
  if (sportsLink) {
    fetch("data/sports.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        const today = new Date().toDateString();
        const gameToday = data.teams.some(
          (t) =>
            t.next.some((g) => new Date(g.date).toDateString() === today) ||
            t.form.some((g) => new Date(g.date).toDateString() === today)
        );
        if (gameToday) {
          sportsLink.classList.add("game-day");
          sportsLink.title = "A team plays today";
        }
      })
      .catch(() => {});
  }
})();

/* Fetch a JSON data file relative to the site root. */
async function loadData(name) {
  const res = await fetch(`data/${name}.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load data/${name}.json`);
  return res.json();
}
