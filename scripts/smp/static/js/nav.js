  // ---------- mobile nav toggle ----------
  const burger = document.querySelector('[data-nav-burger]');
  if (burger) {
    const nav = document.getElementById(burger.getAttribute('aria-controls')) || document.querySelector('.primary-nav');
    burger.addEventListener('click', () => {
      if (!nav) return;
      const open = !nav.classList.contains('open');
      nav.classList.toggle('open', open);
      burger.classList.toggle('open');
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || !nav || !nav.classList.contains('open')) return;
      nav.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    });
  }

  // ---------- nav dropdowns: one open at a time + Escape to close ----------
  const navDropdowns = Array.from(document.querySelectorAll('.primary-nav details.nav-dropdown'));
  navDropdowns.forEach((details) => {
    details.addEventListener('toggle', () => {
      if (details.open) {
        navDropdowns.forEach((other) => { if (other !== details) other.removeAttribute('open'); });
      }
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    navDropdowns.forEach((details) => details.removeAttribute('open'));
  });

