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

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = table.querySelectorAll("thead th");
    headers.forEach((header, index) => {
      header.addEventListener("click", () => {
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.rows);
        const descending = header.classList.contains("sort-asc");
        headers.forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
        header.classList.add(descending ? "sort-desc" : "sort-asc");
        rows.sort((ra, rb) => {
          const result = compareValues(cellValue(ra, index), cellValue(rb, index));
          return descending ? -result : result;
        });
        rows.forEach((row) => tbody.appendChild(row));
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
})();
