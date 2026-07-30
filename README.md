# chronicaria.github.io

Andrew Park's personal site, and the eight projects that used to live in their own
repositories. Plain HTML/CSS/JS at the top level, no build step, served from the root of
`main` by GitHub Pages.

## Structure

```
index.html            Home — résumé, coursework, and the Published work shelf
daily/                The Gothic Times — the live morning paper (front page + 5 desks)
sports.html           Team trackers
music.html            Classical repertoire
literature.html       Reading log
weather.html          County temperature map
404.html              Themed not-found

rome-wiki/            980-article linked knowledge base (Next.js static export)
fantasy-basketball/   2026-27 Fantasy Basketball Encyclopedia — 646 pages
fantasy-football/     2026 Fantasy Football Encyclopedia — 118 pages
valorant/             RWPA dashboard — 19 matches, 410 rounds
concerto/             Piano concerto pairwise ranker
nyc-weather/          Hourly forecasts with ensemble uncertainty bands
winter-trip/          Italy, winter 2026-27 — itinerary and logistics
paper/                The Gothic Times v2 — nine desks, ~120 feeds

assets/home.css       Landing page — the broadsheet design system
assets/styles.css     Every other top-level page
assets/daily.css      Newspaper components
assets/hub.js         The prussian band that ties the sub-projects back here
assets/site.js        Nav burger + dropdowns + JSON loader
scripts/              update_daily · update_sports · update_weather · make_og · make_district_map
data/                 JSON for the top-level pages (see data/README.md)
tools/county-temp-map RTMA → county choropleth generator (its work/ cache is gitignored)
```

## How the sub-projects are wired in

Each project keeps its own markup, stylesheet, and build script — nothing was restyled.
What they share is one line before `</head>`:

```html
<script defer src="/assets/hub.js"></script>
```

`hub.js` renders a prussian band across the top of the page inside a **shadow root**, so
none of the eight stylesheets underneath can reach into it and none of its rules leak out.
The band links home, names the section you are in, and carries a menu of everything else.

The top-level pages don't load it — they already have the real navigation, which now
carries a Projects dropdown alongside Interests.

All navigation is root-absolute (`/sports.html`, `/rome-wiki/`), so the same nav block
works at any depth. That means **the site must be served from a domain root**, not a
subpath. Locally:

```sh
python3 -m http.server 8845 --directory .
```

## Regenerating a sub-project

The projects were copied in as built output. To update one, rebuild it in its own folder
under `~/Desktop/Code/` and copy the result back:

| Path | Source folder | Build |
|---|---|---|
| `fantasy-basketball/` | `fantasy-encyclopedia/` | `python3 build.py` |
| `fantasy-football/` | `fantasy-football-encyclopedia/` | `python3 build.py` |
| `paper/` | `PersonalNewspaper/` | `python3 build.py` → `public/` |
| `rome-wiki/` | `rome-wiki/` | `PAGES_BASE_PATH=/rome-wiki npm run build:pages` → `out/` |
| `winter-trip/`, `valorant/`, `concerto/`, `nyc-weather/` | same-named folders | static, copy as-is |

Re-run the hub injection after any rebuild — it adds the `hub.js` tag to pages that lack
it and skips the rest.

## Two newspapers

`daily/` is the live paper, printed by `scripts/update_daily.py` and current through
July 2026. `paper/` is a fuller rewrite — nine desks instead of five, ~120 feeds, its own
`build.py` in `PersonalNewspaper/` — but its last edition is from June. Pick one before
either goes stale; they are both called The Gothic Times.

## Automation

`scripts/` still holds the updaters for the daily paper, sports, and weather, but the
GitHub Actions workflows that ran them stayed behind on the old `andrewjparkus.github.io`
repository (now the RAPM dashboard). Nothing here is on a schedule yet — the updaters run
by hand until workflows are added back.

## Deploying

Push to `main`. GitHub Pages serves the root. No build step.

Project repositories that used to publish `chronicaria.github.io/<name>/` — `valorant`,
`winter-trip`, `rome-wiki` — would shadow the folders here, because a project site wins
over the org site at the same path. Their Pages deployments were disabled on 2026-07-30;
the repositories themselves are untouched. If you ever re-enable Pages on one of them, it
will silently take that path back.
