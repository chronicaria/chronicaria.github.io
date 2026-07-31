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

Rebuild whenever the vault changes; output is committed in place and published at
`/fantasy/basketball/`, so the folder is deployable to GitHub Pages as-is.

Two notes since the merge into `fantasy/`:

- `serve.py` serves *this folder* as the web root, so `/assets/hub.js` 404s and the
  site-wide hub band is invisible in local dev, and `/fantasy/` (the sport picker) is
  not reachable. To see the real thing, serve the repo root instead:
  `python3 -m http.server 8900` and open `http://127.0.0.1:8900/fantasy/`.
- `build.py` does not emit the hub-band script tag; `scripts/inject_hub.py` adds it
  after the fact. Every rebuild strips it from regenerated pages, so re-run
  `python3 scripts/inject_hub.py` from the repo root afterwards.

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
