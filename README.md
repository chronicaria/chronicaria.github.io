# chronicaria.github.io

Andrew Park's personal site, and the eight projects that used to live in their own
repositories. Plain HTML at the top level — one small shared stylesheet block, no build
step — served from the root of `main` by GitHub Pages.

## Structure

```
index.html            Home — résumé and coursework
daily/                The Gothic Times — the live morning paper (front page + 5 desks;
                      the morgue/archive page is gone, each edition overwrites the last)
music.html            Classical repertoire
literature.html       Reading log
notes/                Course notes (MATH 541, MATH 581) — LaTeX rendered with KaTeX,
                      .tex sources committed alongside
sports.html           Redirect stub → /daily/sports.html (trackers live at the sports desk)
weather.html          Simple weather page — county map + extremes from data/weather.json
404.html              Themed not-found

fantasy/              The Fantasy Encyclopedias — sport picker over two corpora,
                      repainted in the site's Prussian design
  index.html          Hand-written toggle shell; not generated, edit directly
  basketball/         2026-27 Fantasy Basketball Encyclopedia — 646 pages
  football/           2026 Fantasy Football Encyclopedia — 118 pages
valorant/             Valorant MWPA — impact per match, 78 matches, 1,617 rounds
nyc-weather/          Hourly forecasts with ensemble bands + the county temperature map
winter-trip/          Italy, winter 2026-27 — itinerary and logistics
quant-internships/    Summer 2027 quant internship board — 59 roles, 38 firms
concerto/             Piano concerto pairwise ranker — archived: kept at its URL, noindexed, out of all nav
equipotential/        Live paper — archived: kept at its URL, noindexed, out of all nav

assets/daily.css      Newspaper components (the paper keeps its own design)
assets/hub.js         The prussian band that ties the sub-projects back here
sw.js                 Self-destroying service worker (see Design)
scripts/              update_daily · update_sports · update_weather · make_og · make_district_map
data/                 JSON for the top-level pages (see data/README.md)
tools/county-temp-map RTMA → county choropleth generator (its work/ cache is gitignored)
```

## Design

The top level is deliberately simple: one shared `<style>` block per page (Archivo from
Google Fonts, black-on-white, bordered tables, a 60em column) and no JavaScript — except
KaTeX on the `notes/` pages, which need it for the math, and a small fetch on
`weather.html` that fills the current numbers from `data/weather.json`. `sw.js` is a
self-destroying service worker: earlier versions of the site
installed an offline cache, and returning visitors would keep seeing it otherwise. On
activate it deletes every cache, unregisters itself, and reloads its clients. The
sub-projects keep their own designs.

## How the sub-projects are wired in

Each project keeps its own markup, stylesheet, and build script — nothing was restyled.
What they share is one line before `</head>`:

```html
<script defer src="/assets/hub.js"></script>
```

`hub.js` renders a prussian band across the top of the page inside a **shadow root**, so
none of the eight stylesheets underneath can reach into it and none of its rules leak out.
The band links home, names the section you are in, and carries a menu of everything else.

The top-level pages don't load it — they link everything with plain HTML.

All navigation is root-absolute (`/music.html`, `/fantasy/`), so the same nav block
works at any depth. That means **the site must be served from a domain root**, not a
subpath. Locally:

```sh
python3 -m http.server 8845 --directory .
```

## Regenerating a sub-project

The projects were copied in as built output and their standalone folders under
`~/Desktop/Code/` were deleted on 2026-07-30, so **this repository is now the source**
for most of them.

| Path | How to rebuild |
|---|---|
| `concerto/`, `valorant/`, `nyc-weather/`, `winter-trip/`, `quant-internships/` | Nothing to build — edit the files in place. |
| `fantasy/basketball/` | `cd fantasy/basketball && python3 build.py` — reads the vault at `~/Desktop/Rome/Basketball/Fantasy Basketball/2026-27 Fantasy Basketball Encyclopedia`. |
| `fantasy/football/` | `cd fantasy/football && python3 build.py` — reads `~/Desktop/Rome/Sports/NFL/Fantasy Football`. |
| `fantasy/index.html` | Nothing to build — the sport picker is hand-written and self-contained. Keep its two panels in step with the corpora's own section links. |

After any rebuild:

```sh
python3 scripts/inject_hub.py    # re-adds the hub tag to new pages, skips the rest
```

To add or remove a project, edit `PROJECTS` in `scripts/site_nav.py` and run it — it
regenerates the nav, the `SECTIONS` array in `hub.js`, and the sitemap from that one list.
`inject_hub.py` reads the same list.

## The newspaper

`daily/` is the paper, printed by `scripts/update_daily.py` on a schedule. A second,
fuller rewrite once lived at `/paper/` (nine desks, ~120 feeds, built by a separate
`PersonalNewspaper` project); it was retired in favour of this one, which is the version
that actually stays current.

## Automation

Three scheduled workflows in `.github/workflows/`:

| Workflow | Cadence | Runs | Writes |
|---|---|---|---|
| `print-daily.yml` | 10:10 UTC daily | `update_daily.py` | `data/daily/`, `daily.xml` |
| `update-sports.yml` | every 6h | `update_sports.py` | `data/sports.json`, `data/history/` |
| `update-weather.yml` | every 3h | `update_weather.py` | `assets/weather/county-temp.svg`, `data/weather.json` |

The first two are stdlib-only. The weather one installs `tools/county-temp-map` (geopandas,
rasterio, exactextract, cairosvg + libcairo from apt) and caches the ~80 MB Census shapefile
between runs.

All three commit through `scripts/publish.sh`, which rebases and retries on a rejected push
— the schedules can drift into each other, and without that the second one to finish just
fails. They commit with `[skip ci]` and no-op when nothing changed.

A workflow succeeding does not mean every source was healthy: a dead feed or a failed team
fetch is swallowed so one bad source can't kill the run. Check the `errors` key in
`data/daily/latest.json` or `data/sports.json` if a section looks thin.

**GitHub disables scheduled workflows after ~60 days without repo activity.** The updaters'
own commits normally keep them alive; re-enable from the Actions tab if they ever pause.

## Deploying

Push to `main`. GitHub Pages serves the root. No build step.

Project repositories that used to publish `chronicaria.github.io/<name>/` — `valorant`,
`winter-trip`, `rome-wiki` — would shadow the folders here, because a project site wins
over the org site at the same path. Their Pages deployments were disabled on 2026-07-30;
the repositories themselves are untouched. If you ever re-enable Pages on one of them, it
will silently take that path back.

The Rome wiki was removed from this repo on 2026-07-31 and no longer deploys. Its export
was moved to `~/Desktop/Code/rome-wiki-archive/` and its Next.js source remains at
[chronicaria/rome-wiki](https://github.com/chronicaria/rome-wiki). Do not copy it back
here, and leave that repo's Pages deployment disabled — re-enabling it would republish the
wiki at `chronicaria.github.io/rome-wiki/`.
