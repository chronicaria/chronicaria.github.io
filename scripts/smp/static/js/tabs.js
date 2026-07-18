  // ---------- generic tabs ----------
  document.querySelectorAll('[data-tabs]').forEach((tablist) => {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"][data-tab-target]'));
    if (!tabs.length) return;
    function activate(tab, focus) {
      tabs.forEach((btn) => {
        const on = btn === tab;
        const panel = document.getElementById(btn.dataset.tabTarget || '');
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', () => activate(tab, false));
      tab.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
        if (event.key === 'Home') next = tabs[0];
        if (event.key === 'End') next = tabs[tabs.length - 1];
        if (!next) return;
        event.preventDefault();
        activate(next, true);
      });
    });
    activate(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0], false);
  });

  // ---------- draft year tabs ----------
  const draftTabs = document.querySelector('[data-draft-tabs]');
  if (draftTabs) {
    const buttons = Array.from(draftTabs.querySelectorAll('button[data-draft-tab]'));
    function activateDraft(button, focus) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      });
      document.querySelectorAll('[data-draft-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.draftPanel !== button.dataset.draftTab;
      });
      if (focus) button.focus();
    }
    buttons.forEach((button, index) => {
      button.tabIndex = button.classList.contains('active') ? 0 : -1;
      button.addEventListener('click', () => {
        activateDraft(button, false);
      });
      button.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = buttons[(index + 1) % buttons.length];
        if (event.key === 'ArrowLeft') next = buttons[(index - 1 + buttons.length) % buttons.length];
        if (event.key === 'Home') next = buttons[0];
        if (event.key === 'End') next = buttons[buttons.length - 1];
        if (!next) return;
        event.preventDefault();
        activateDraft(next, true);
      });
    });
    if (buttons.length) activateDraft(buttons.find((b) => b.classList.contains('active')) || buttons[0], false);
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

