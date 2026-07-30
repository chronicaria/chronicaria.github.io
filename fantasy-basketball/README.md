# The Fantasy Basketball Encyclopedia — wiki

A static HTML wiki rendering the **2026-27 Fantasy Basketball Encyclopedia** vault
(`~/Desktop/Rome/Basketball/Fantasy Basketball/2026-27 Fantasy Basketball Encyclopedia`)
into ~644 linked pages: a main hub, 30 team desks, 555 player dossiers, draft boards,
projections, strategy notes, and the source library.

## Use

```bash
python3 build.py    # regenerate every page from the vault (idempotent, ~5s)
python3 serve.py    # dev server at http://localhost:8901
```

Rebuild whenever the vault changes; output is committed at the repo root, so the folder
is deployable to GitHub Pages as-is.

## Architecture

Same contract as `andrewjparkus.github.io` / `chronicaria.github.io`: fully pre-generated
pages, no framework, token-based CSS with a persisted theme toggle (paper / lamplight),
sticky nav with a client-side search index (`assets/search-index.json`), `<details>`
dropdown navigation. Visual register is antique-serif: EB Garamond display, Source Serif 4
text, ivory paper, oxblood accents, double-rule ornaments, small-caps labels.

- `build.py` — the entire generator: vault scan → wikilink/math/callout preprocessing →
  python-markdown (tables + toc) → page shells. Player pages get a fact card joined from
  `Data/player-projections-corrected.csv` and `Data/espn-points-board.csv` (9-cat and
  ESPN-points ranks side by side).
- `assets/style.css` — all styling, both themes.
- `assets/site.js` — theme, search (diacritic-insensitive), dropdowns, sortable/filterable
  player index, KaTeX auto-render.
- `data/` — the projection CSV exports, copied from the vault for download links.

Math uses KaTeX from CDN; fonts from Google Fonts. Everything else is self-contained.
