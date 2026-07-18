  // ---------- copy table as TSV ----------
  document.querySelectorAll('.table-wrap').forEach((wrap) => {
    const table = wrap.querySelector('table');
    if (!table || !navigator.clipboard) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-table';
    btn.title = 'Copy table for spreadsheets';
    btn.setAttribute('aria-label', 'Copy table for spreadsheets');
    btn.textContent = '⧉';
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      const lines = Array.from(table.querySelectorAll('tr')).map((tr) =>
        Array.from(tr.cells).map((cell) => cell.textContent.trim().replace(/\s+/g, ' ')).join('\t'));
      navigator.clipboard.writeText(lines.join('\n')).then(() => {
        btn.textContent = '✓';
        btn.setAttribute('aria-label', 'Copied table');
        setTimeout(() => {
          btn.textContent = '⧉';
          btn.setAttribute('aria-label', 'Copy table for spreadsheets');
        }, 1200);
      });
    });
    wrap.appendChild(btn);
  });

  // ---------- sticky second column (Year alongside Name) ----------
  const stickyTables = Array.from(document.querySelectorAll('table.sticky-col2'));
  function smpMeasureSticky() {
    stickyTables.forEach((table) => {
      const first = table.tHead && table.tHead.rows[0] && table.tHead.rows[0].cells[0];
      if (first) table.style.setProperty('--c1w', first.offsetWidth + 'px');
    });
  }
  if (stickyTables.length) {
    smpMeasureSticky();
    let stickyTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(stickyTimer);
      stickyTimer = setTimeout(smpMeasureSticky, 150);
    });
  }

  // ---------- column-group toggles (table_html colgroups=) ----------
  document.querySelectorAll('[data-colgroup-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.colgroupToggle);
    if (!table) return;
    const cgStoreKey = 'colgroup:' + wrap.dataset.colgroupToggle;
    const buttons = Array.from(wrap.querySelectorAll('button[data-colgroup]'));
    function applyColgroup(token, persist) {
      buttons.forEach((b) => {
        const on = b.dataset.colgroup === token;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      table.querySelectorAll('th[data-colgroup], td[data-colgroup]').forEach((cell) => {
        cell.classList.toggle('cg-hidden', token !== 'all' && cell.dataset.colgroup.split(' ').indexOf(token) === -1);
      });
      if (persist) smpStore.set(cgStoreKey, token);
      smpMeasureSticky();
    }
    buttons.forEach((b) => b.addEventListener('click', () => applyColgroup(b.dataset.colgroup, true)));
    const storedGroup = smpStore.get(cgStoreKey);
    const storedValid = storedGroup && buttons.some((b) => b.dataset.colgroup === storedGroup);
    applyColgroup(storedValid ? storedGroup : (wrap.dataset.colgroupDefault || 'all'), false);
  });

  // ---------- glossary bottom sheet ----------
  // On hover-less (touch) devices, tapping a stat header opens a sheet with the
  // GLOSSARY definition plus a "sort" action (since the tap no longer sorts).
  // Everywhere, tapping a mini-skill chip opens the sheet on the skill legend.
  let glossarySheet = null;
  let glossaryReturnFocus = null;
  let glossarySortTh = null;
  let glossaryBypass = false;
  const coarsePointer = matchMedia('(hover: none)');

  function glossaryLegendHtml() {
    const skills = (siteConfig && siteConfig.skills) || {};
    const entries = Object.keys(skills).map((code) =>
      '<div class="gs-skill"><span class="mini-skill">' + escapeHtml(code) + '</span> ' + escapeHtml(skills[code]) + '</div>').join('');
    if (!entries) return '';
    return '<div class="gs-legend"><h4>Skill badges</h4>' + entries + '</div>';
  }

  function closeGlossarySheet() {
    if (!glossarySheet) return;
    glossarySheet.hidden = true;
    if (glossaryReturnFocus && glossaryReturnFocus.focus) glossaryReturnFocus.focus();
    glossaryReturnFocus = null;
    glossarySortTh = null;
  }

  function buildGlossarySheet() {
    if (glossarySheet) return glossarySheet;
    const overlay = document.createElement('div');
    overlay.className = 'gs-overlay';
    overlay.hidden = true;
    const sheet = document.createElement('div');
    sheet.className = 'glossary-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-labelledby', 'gs-term');
    sheet.innerHTML = '<div class="gs-grip" aria-hidden="true"></div>'
      + '<h3 id="gs-term"></h3><p class="gs-def"></p>'
      + '<div class="gs-actions">'
      + '<button type="button" class="gs-sort">Sort by this column</button>'
      + '<button type="button" class="gs-close">Close</button></div>'
      + glossaryLegendHtml();
    overlay.appendChild(sheet);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (event) => { if (event.target === overlay) closeGlossarySheet(); });
    sheet.querySelector('.gs-close').addEventListener('click', closeGlossarySheet);
    sheet.querySelector('.gs-sort').addEventListener('click', () => {
      const th = glossarySortTh;
      closeGlossarySheet();
      if (th) { glossaryBypass = true; th.click(); glossaryBypass = false; }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !overlay.hidden) closeGlossarySheet();
    });
    glossarySheet = overlay;
    return overlay;
  }

  function openGlossarySheet(term, definition, sortTh) {
    const overlay = buildGlossarySheet();
    overlay.querySelector('#gs-term').textContent = term;
    const def = overlay.querySelector('.gs-def');
    def.textContent = definition || '';
    def.hidden = !definition;
    glossarySortTh = sortTh || null;
    overlay.querySelector('.gs-sort').hidden = !sortTh;
    overlay.hidden = false;
    glossaryReturnFocus = document.activeElement;
    overlay.querySelector('.gs-close').focus();
  }

  document.addEventListener('click', (event) => {
    if (glossaryBypass) return;
    const target = event.target;
    if (!target || !target.closest) return;
    const chip = target.closest('.mini-skill');
    if (chip) {
      const code = chip.textContent.trim();
      const skills = (siteConfig && siteConfig.skills) || {};
      openGlossarySheet('Skill: ' + code, skills[code] || chip.getAttribute('title') || '', null);
      return;
    }
    if (!coarsePointer.matches) return;
    const th = target.closest('table[data-sortable] thead th[title]');
    if (!th) return;
    event.preventDefault();
    event.stopPropagation();
    openGlossarySheet(th.textContent.trim(), th.getAttribute('title'), th);
  }, true); // capture: runs (and stops) before the sort handler bound on the th

  // ---------- generic card-list (mobile card view for opted-in tables) ----------
  // Any table[data-card-list] is mirrored as a .card-list of stacked cards on
  // narrow viewports: first cell becomes the card title, remaining cells become
  // labeled stats (columns with empty values are skipped per card).
  const cardListMq = matchMedia('(max-width: 700px)');
  document.querySelectorAll('table[data-card-list]').forEach((table) => {
    const wrap = table.closest('.table-wrap');
    if (!wrap || !table.tHead || !table.tBodies[0]) return;
    let list = null;
    function buildCards() {
      if (list) return list;
      const headers = Array.from(table.tHead.rows[0].cells).map((cell) => cell.textContent.trim());
      list = document.createElement('div');
      list.className = 'card-list';
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const item = document.createElement('article');
        item.className = 'card-list-item';
        if (row.dataset.tid) item.dataset.tid = row.dataset.tid;
        const cells = Array.from(row.cells);
        const title = document.createElement('div');
        title.className = 'cl-title';
        title.innerHTML = cells.length ? cells[0].innerHTML : '';
        item.appendChild(title);
        const stats = document.createElement('div');
        stats.className = 'cl-stats';
        cells.slice(1).forEach((cell, i) => {
          const label = headers[i + 1] || '';
          const value = cell.textContent.trim();
          if (!label || value === '' || value === '—') return;
          const stat = document.createElement('span');
          stat.className = 'cl-stat';
          stat.innerHTML = '<b>' + escapeHtml(label) + '</b>' + escapeHtml(value);
          stats.appendChild(stat);
        });
        item.appendChild(stats);
        list.appendChild(item);
      });
      wrap.after(list);
      return list;
    }
    function syncCards() {
      const on = cardListMq.matches;
      if (on) buildCards();
      if (list) list.hidden = !on;
      wrap.classList.toggle('as-cards', on);
    }
    syncCards();
    if (cardListMq.addEventListener) cardListMq.addEventListener('change', syncCards);
    else if (cardListMq.addListener) cardListMq.addListener(syncCards);
  });

