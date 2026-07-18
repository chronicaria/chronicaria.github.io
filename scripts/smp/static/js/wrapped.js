// ---------- SMP Wrapped deck (wrapped.html only) ----------
// Progressive enhancement over a plain scrolling page: opts <html> into
// scroll-snap, builds a dots rail, and adds keyboard slide navigation.
// Honors prefers-reduced-motion (instant jumps instead of smooth scrolling).
(function () {
  const deck = document.querySelector('[data-wrapped-deck]');
  if (!deck) return;
  const slides = Array.from(deck.querySelectorAll('.wr-slide'));
  if (!slides.length) return;

  document.documentElement.classList.add('wr-snap');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const behavior = () => (reduceMotion.matches ? 'auto' : 'smooth');

  // dots rail
  const rail = document.createElement('nav');
  rail.className = 'wr-dots';
  rail.setAttribute('aria-label', 'Wrapped slides');
  const dots = slides.map((slide, index) => {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'wr-dot';
    const title = slide.dataset.wrTitle || `Slide ${index + 1}`;
    dot.setAttribute('aria-label', title);
    dot.title = title;
    dot.addEventListener('click', () => goTo(index));
    rail.appendChild(dot);
    return dot;
  });
  document.body.appendChild(rail);

  let current = 0;
  function setActive(index) {
    current = index;
    dots.forEach((dot, i) => {
      if (i === index) dot.setAttribute('aria-current', 'true');
      else dot.removeAttribute('aria-current');
    });
  }
  function goTo(index) {
    const target = slides[Math.max(0, Math.min(slides.length - 1, index))];
    if (target) target.scrollIntoView({ behavior: behavior(), block: 'start' });
  }
  setActive(0);

  if ('IntersectionObserver' in window) {
    const visible = new Map();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => visible.set(entry.target, entry.intersectionRatio));
      let bestIndex = current;
      let bestRatio = 0;
      slides.forEach((slide, i) => {
        const ratio = visible.get(slide) || 0;
        if (ratio > bestRatio) { bestRatio = ratio; bestIndex = i; }
      });
      if (bestRatio > 0) setActive(bestIndex);
    }, { threshold: [0.25, 0.5, 0.75] });
    slides.forEach((slide) => observer.observe(slide));
  }

  // keyboard: arrows / PageUp / PageDown step one slide at a time
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' || target.isContentEditable)) return;
    if (event.key === 'ArrowDown' || event.key === 'PageDown') {
      event.preventDefault();
      goTo(current + 1);
    } else if (event.key === 'ArrowUp' || event.key === 'PageUp') {
      event.preventDefault();
      goTo(current - 1);
    }
  });
})();
