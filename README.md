# andrewparkus.github.io

Personal website for Andrew Park — plain HTML/CSS/JS, no build step, deployable on GitHub Pages.

Design language adapted from the SMP Basketball League site: dark panels, Helvetica Neue,
compact information-dense cards.

## Structure

```
index.html          Home — condensed resume + live preview cards
daily/              The Gothic Times — auto-printed morning newspaper (front page + 4 desks)
league/             SMP Basketball League — generated mock-league site (680 pages)
league-data/        Basketball-GM JSON exports that feed the league generator
sports.html         Team trackers (data pipeline lands in Phase 3)
music.html          Classical repertoire (content lands in Phase 2)
literature.html     Reading log (content lands in Phase 2)
research.html       Math research + analytics writeups (content lands in Phase 2)
assets/styles.css   The whole design system (incl. nav dropdowns)
assets/daily.css    Newspaper components (masthead, fold, election tile map…)
assets/site.js      Nav burger/dropdowns + JSON data loader
assets/daily.js     Newspaper renderer (edition JSON → DOM, incl. the election map)
scripts/            update_sports.py · update_daily.py · league_generator.py · league_postprocess.py
data/               JSON data files (hand-edited + auto-generated)
```

Nav: Home · Research · Daily · Interests ▾ (Sports, Music, Literature) · Other ▾ (SMP league).

Extras: light/dark theme toggle (persisted), live in-browser scores on game days,
a Gray–Scott reaction–diffusion canvas on the research page, season history archiving under
`data/history/`, keyboard nav, themed 404, JSON validation CI, print stylesheet, and
OG/social cards. See `data/README.md` for how to edit content.

## Roadmap

- **Phase 1 (done):** scaffold, design system, homepage with resume content, styled stub pages
- **Phase 2 (in progress):** music page done (`data/music.json`); literature + research content next
- **Phase 3 (done):** sports page fed by `scripts/update_sports.py` via a scheduled GitHub Actions
  workflow (`.github/workflows/update-sports.yml`, every 6h) writing `data/sports.json`
- **Phase 4 (done):** brief hero + GPA chip, semester-by-semester coursework, DataBallR first,
  upcoming-games schedule table with team filter, future-repertoire table, live "next up" line
  on the homepage sports card
- **Phase 5 (done):** The Gothic Times (`/daily`) — a personal morning newspaper printed at
  6:10 AM ET by `scripts/update_daily.py` via `.github/workflows/print-daily.yml`. Four desks
  (Sports, AI & Models, Markets, Elections), ~25 sources, live Polymarket/Kalshi midterm odds,
  market snapshot, Durham weather ear, daily Romantic-era stanza, and a browsable archive in
  `data/daily/` (one JSON per edition, forever)
- **Phase 6 (done):** the SMP Basketball League site folded in at `/league` (generator +
  exports live in this repo; `.github/workflows/build-league.yml` regenerates on new
  `league-data/day*.json`), nav rebuilt with Interests/Other dropdowns, and the elections
  desk upgraded to an interactive hex map — Senate/Governors/House (district clusters),
  Polymarket odds shaded with the Wikipedia election-atlas palette, ~140 markets every morning

Note: GitHub disables scheduled workflows after ~60 days without repo activity — a push (or the
workflow's own data commits) keeps it alive; re-enable from the Actions tab if it ever pauses.

## Deploying

Push to a repo named `andrewparkus.github.io` (or enable Pages on any repo, serving from the
root of `main`). No build step needed.
