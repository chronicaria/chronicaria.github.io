  // ---------- player page: sticky section rail + scroll-spy ----------
  const playerRail = document.querySelector('[data-player-rail]');
  if (playerRail) {
    const siteHeader = document.querySelector('.site-header');
    const railLinks = Array.from(playerRail.querySelectorAll('a[href^="#"]'));
    const railSections = railLinks
      .map((link) => document.getElementById(link.getAttribute('href').slice(1)))
      .filter(Boolean);

    // The header wraps at narrow widths, so measure it instead of hardcoding:
    // --rail-offset pins the rail below the sticky header; --anchor-offset keeps
    // anchor jumps from landing underneath header + rail.
    function setRailOffsets() {
      const headerH = siteHeader ? siteHeader.offsetHeight : 0;
      const root = document.documentElement;
      root.style.setProperty('--rail-offset', headerH + 'px');
      root.style.setProperty('--anchor-offset', headerH + playerRail.offsetHeight + 10 + 'px');
    }
    setRailOffsets();
    window.addEventListener('resize', setRailOffsets);

    let activeRailId = null;
    function setRailActive(id) {
      if (id === activeRailId) return;
      activeRailId = id;
      railLinks.forEach((link) => {
        const on = link.getAttribute('href').slice(1) === id;
        link.classList.toggle('active', on);
        if (on) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      });
    }

    // Scroll-spy: the active section is the last one whose top has passed the
    // rail's bottom edge. Runs directly on (already frame-throttled) scroll
    // events — a handful of rect reads, cheap enough without rAF deferral.
    function runSpy() {
      if (!railSections.length) return;
      const line = (siteHeader ? siteHeader.offsetHeight : 0) + playerRail.offsetHeight + 14;
      let active = railSections[0];
      railSections.forEach((section) => {
        if (section.getBoundingClientRect().top <= line) active = section;
      });
      // At the very bottom of the page the last section wins even if short.
      if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 2) {
        active = railSections[railSections.length - 1];
      }
      setRailActive(active.id);
    }
    window.addEventListener('scroll', runSpy, { passive: true });
    window.addEventListener('resize', runSpy);
    runSpy();
  }

