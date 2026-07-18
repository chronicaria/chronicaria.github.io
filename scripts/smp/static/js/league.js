// league.js — records all-time-leaders totals/per-game toggle + history
// transaction-log type/team filters. Self-contained IIFE (site.js is deferred,
// so the DOM is ready when this runs).
(function () {
  // ---------- all-time leaders: totals vs per-game ----------
  document.querySelectorAll('[data-leaders-toggle]').forEach((wrap) => {
    const section = wrap.closest('section');
    if (!section) return;
    const panels = Array.from(section.querySelectorAll('[data-leaders-panel]'));
    const buttons = Array.from(wrap.querySelectorAll('button[data-leaders-view]'));
    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        buttons.forEach((b) => {
          const on = b === button;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        panels.forEach((panel) => {
          panel.hidden = panel.dataset.leadersPanel !== button.dataset.leadersView;
        });
      });
    });
  });

  // ---------- transaction log: type + team filters ----------
  document.querySelectorAll('[data-txlog]').forEach((card) => {
    const typeButtons = Array.from(card.querySelectorAll('[data-tx-type-filter] button[data-tx-type]'));
    const teamSelect = card.querySelector('[data-tx-team-filter]');
    const seasons = Array.from(card.querySelectorAll('details.tx-season'));
    const initiallyOpen = seasons.map((details) => details.open);
    if (!typeButtons.length && !teamSelect) return;

    function apply() {
      const activeButton = typeButtons.find((b) => b.classList.contains('active'));
      const type = activeButton ? activeButton.dataset.txType : 'all';
      const team = teamSelect ? teamSelect.value : 'all';
      const filtering = type !== 'all' || team !== 'all';
      seasons.forEach((details, index) => {
        let shown = 0;
        details.querySelectorAll('li[data-tx-type]').forEach((item) => {
          const typeOk = type === 'all' || item.dataset.txType === type;
          const teamOk = team === 'all' || (item.dataset.txTids || '').indexOf(',' + team + ',') !== -1;
          const ok = typeOk && teamOk;
          item.classList.toggle('tx-hidden', !ok);
          if (ok) shown += 1;
        });
        const pill = details.querySelector('[data-tx-count]');
        if (pill) {
          const total = Number(pill.dataset.txCount);
          pill.textContent = filtering ? shown + ' of ' + total + ' moves' : total + ' moves';
        }
        details.classList.toggle('tx-season-empty', filtering && shown === 0);
        details.open = filtering ? shown > 0 : initiallyOpen[index];
      });
    }

    typeButtons.forEach((button) => {
      button.addEventListener('click', () => {
        typeButtons.forEach((b) => {
          const on = b === button;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        apply();
      });
    });
    if (teamSelect) teamSelect.addEventListener('change', apply);
  });
})();
