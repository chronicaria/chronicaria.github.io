(function () {
  // ---------- team pages (W2): standalone module, appended after the core bundle ----------

  // 0-GP roster rows show (dimmed) by default; unchecking "show inactive" hides them
  document.querySelectorAll('[data-toggle-inactive]').forEach((input) => {
    const card = input.closest('[data-roster-card]');
    if (!card) return;
    const apply = () => card.classList.toggle('hide-inactive', !input.checked);
    input.addEventListener('change', apply);
    apply();
  });

  // scoring-share metric toggle (PTS / FGA / AST)
  document.querySelectorAll('[data-share-card]').forEach((card) => {
    const buttons = Array.from(card.querySelectorAll('button[data-share-metric]'));
    const panels = Array.from(card.querySelectorAll('[data-share-panel]'));
    if (!buttons.length) return;
    function activate(button) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      panels.forEach((p) => { p.hidden = p.dataset.sharePanel !== button.dataset.shareMetric; });
    }
    buttons.forEach((button) => button.addEventListener('click', () => activate(button)));
  });

  // rotation map: hover crosshair — highlight the hovered row and game column
  document.querySelectorAll('table.rotation-map').forEach((table) => {
    function clear() {
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      table.querySelectorAll('.row-hl').forEach((r) => r.classList.remove('row-hl'));
    }
    table.addEventListener('mouseover', (evt) => {
      const cell = evt.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      clear();
      const idx = cell.cellIndex;
      if (idx > 0) {
        table.querySelectorAll('tr').forEach((tr) => {
          const c = tr.cells[idx];
          if (c) c.classList.add('col-hl');
        });
      }
      const row = cell.closest('tbody tr');
      if (row) row.classList.add('row-hl');
    });
    table.addEventListener('mouseleave', clear);
  });
})();
