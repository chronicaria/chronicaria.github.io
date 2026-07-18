(function () {
  function cellValue(row, index) {
    const cell = row.children[index];
    if (!cell) return "";
    return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
  }

  function compareValues(a, b) {
    const na = Number(a);
    const nb = Number(b);
    const aNumeric = a !== "" && Number.isFinite(na);
    const bNumeric = b !== "" && Number.isFinite(nb);
    if (aNumeric && bNumeric) return na - nb;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const caption = table.querySelector('caption');
    if (caption) table.setAttribute('aria-label', caption.textContent.trim());
    function activateSort(header, index) {
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const rows = Array.from(tbody.rows);
      const descending = header.classList.contains("sort-asc");
      headers.forEach((h) => {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      header.classList.add(descending ? "sort-desc" : "sort-asc");
      header.setAttribute("aria-sort", descending ? "descending" : "ascending");
      rows.sort((ra, rb) => {
        const result = compareValues(cellValue(ra, index), cellValue(rb, index));
        return descending ? -result : result;
      });
      rows.forEach((row) => tbody.appendChild(row));
    }
    headers.forEach((header, index) => {
      header.tabIndex = 0;
      header.setAttribute("aria-sort", "none");
      header.addEventListener("click", () => activateSort(header, index));
      header.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        activateSort(header, index);
      });
    });
  });

  document.querySelectorAll("[data-table-filter]").forEach((input) => {
    const table = document.getElementById(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", () => {
      const needle = input.value.trim().toLowerCase();
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
      });
    });
  });

  document.querySelectorAll('[data-pos-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.posFilter);
    if (!table || table.dataset.posCol === undefined) return;
    const col = Number(table.dataset.posCol);
    const apply = () => {
      const f = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const cell = row.cells[col];
        const pos = cell ? cell.textContent.trim() : '';
        // single-letter groups (G/F/C) match by substring; two-letter picks match exactly
        const match = f === 'all' || (f.length === 1 ? pos.indexOf(f) !== -1 : pos === f);
        row.classList.toggle('pos-hidden', !match);
      });
    };
    select.addEventListener('change', apply);
    apply();
  });
  document.querySelectorAll('[data-schedule-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.scheduleFilter);
    if (!table) return;
    const apply = () => {
      const value = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = value !== 'all' && row.dataset.scheduleTeam !== value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('[data-day-select]').forEach((select) => {
    const panels = Array.from(document.querySelectorAll('[data-day-panel]'));
    const apply = () => {
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.dayPanel !== select.value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('.click-row[data-href]').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.closest && target.closest('a')) return;
      window.location.href = row.dataset.href;
    });
  });

  document.querySelectorAll('[data-view-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.viewToggle);
    if (!table) return;
    const viewStoreKey = 'viewtoggle:' + wrap.dataset.viewToggle;
    function activateView(button, persist) {
      wrap.querySelectorAll('button').forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-pressed', 'false');
      });
      button.classList.add('active');
      button.setAttribute('aria-pressed', 'true');
      table.classList.remove('show-adv', 'show-p36', 'show-rate');
      if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      if (persist) { try { localStorage.setItem(viewStoreKey, button.dataset.view); } catch (e) {} }
    }
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => activateView(button, true));
    });
    let storedView = null;
    try { storedView = localStorage.getItem(viewStoreKey); } catch (e) {}
    const savedButton = storedView && wrap.querySelector('button[data-view="' + storedView + '"]');
    if (savedButton && !savedButton.classList.contains('active')) activateView(savedButton, false);
  });

  document.querySelectorAll('[data-group-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.groupToggle);
    if (!table) return;
    const apply = () => {
      const active = new Set(
        Array.from(wrap.querySelectorAll('button.active')).map((b) => b.dataset.group)
      );
      Array.from(table.tBodies[0].rows).forEach((row) => {
        if (!row.dataset.group) return;
        row.classList.toggle('group-hidden', !active.has(row.dataset.group));
      });
    };
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        button.classList.toggle('active');
        button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
        apply();
      });
    });
    apply();
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('details.team-dropdown[open], details.nav-dropdown[open]').forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute('open');
    });
  });

