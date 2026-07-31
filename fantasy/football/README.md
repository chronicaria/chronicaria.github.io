# The Fantasy Football Encyclopedia — wiki

A static HTML wiki rendering the **2026 Fantasy Football Encyclopedia** vault
(`~/Desktop/Rome/Sports/NFL/Fantasy Football`) into ~110 linked pages: a reading-order
hub, the literacy layer, the draft kit, the in-season operating manual, the concept
atomics, 61 player pages, and an interactive draft board.

Built for a reader who does not watch NFL football. That constraint shows up everywhere:
every player reference resolves to one of twelve archetypes, every jargon term links to a
glossary, and there is no LaTeX anywhere in the build.

## Use

```bash
python3 build.py    # regenerate every page from the vault (idempotent, ~2s)
python3 serve.py    # dev server at http://localhost:8902
```

Rebuild whenever the vault changes. Output is committed in place and published at
`/fantasy/football/`, so the folder is deployable to GitHub Pages as-is.

Two notes since the merge into `fantasy/`:

- `serve.py` serves *this folder* as the web root, so `/assets/hub.js` 404s and the
  site-wide hub band is invisible in local dev, and `/fantasy/` (the sport picker) is
  not reachable. To see the real thing, serve the repo root instead:
  `python3 -m http.server 8900` and open `http://127.0.0.1:8900/fantasy/`.
- `build.py` does not emit the hub-band script tag; `scripts/inject_hub.py` adds it
  after the fact. Every rebuild strips it from regenerated pages, so re-run
  `python3 scripts/inject_hub.py` from the repo root afterwards.

## Architecture

Same contract as `andrewjparkus.github.io`, `chronicaria.github.io` and the fantasy
basketball wiki: fully pre-generated pages, no framework, no bundler, no
`package.json`. Token-based CSS with a persisted theme toggle (paper / lamplight) set by
a pre-paint script so there is no flash, a sticky nav with a client-side search index,
and `<details>` dropdown navigation. Visual register is antique serif — EB Garamond
display, Source Serif 4 text, warm paper, hairlines rather than shadows, small-caps
labels, tabular numerals — shifted from the basketball build's oxblood to **pine and
brass** so the two encyclopedias are never confusable.

- `build.py` — the entire generator: vault scan → wikilink and Obsidian-callout
  preprocessing → python-markdown (tables, toc, attr_list) → page shells. Player pages
  get a fact card joined from `players.csv` and `player_context.csv`.
- `assets/style.css` — all styling, both themes, plus a print stylesheet.
- `assets/site.js` — theme, diacritic-insensitive search with `/` to focus, nav
  dropdowns, and the draft board's filter and sort.
- `data/` — the two CSVs, copied from the vault for download.

Fonts come from Google Fonts. Everything else is self-contained; there is no other
external request.

## The Draft Room

`draft-room.html` is the one page that is not a rendering of a note. It is built
straight from the CSVs by the same arithmetic as `Data/build_board.py` in the vault, so
the interactive table and the vault's markdown board cannot drift apart. Sortable on
every column, filterable by text and by position, with availability rendered as a bar.

Column semantics, because two of them are models:

| Column | What it is |
|---|---|
| `VOR` | projected points minus the freely-available baseline at that position — **observed input, arithmetic output** |
| `Avail` | three-year games-played rate, shrunk toward the position mean — **a model** |
| `Adj VOR` | value after scaling each projection by availability relative to position — **a model** |
| `ADP` | Fantasy Football Calculator PPR proxy — **not ESPN's own**, which could not be extracted |
| `Δ` | board rank minus market pick, shown only at 15 slots or more |
| `Risk` | how contested the role looks. **Not a durability rating** |

Sorting puts blanks last in both directions, so a missing value never masquerades as a
zero — the same fail-loud rule the data pipeline uses.

## What is perishable

Every page carries its own `as_of` and, where it decays, an `expires`. Pages built on
July projections are flagged in the page itself. The board, the tiers, the ADP deltas,
the 1.01 recommendation and every player page are dead the moment the draft ends; the
literacy layer, the concepts and the in-season manual are not.
