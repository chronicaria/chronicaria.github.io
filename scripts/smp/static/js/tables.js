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

