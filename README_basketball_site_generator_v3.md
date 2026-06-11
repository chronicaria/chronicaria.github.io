# Basketball League Site Generator v3

This script generates a static HTML hub from a Basketball GM-style JSON export.

## Basic usage

```bash
# Easiest: auto-picks the newest day*.json in the current directory
python3 basketball_site_generator_v3.py --out docs --clean

# Or name the export explicitly
python3 basketball_site_generator_v3.py day17.json --out docs --clean
```

Then open `docs/index.html`.

## Useful options

```bash
# Force the Schedule hub to a specific season
python3 basketball_site_generator_v3.py preseason.json --out site --clean --schedule-season 2028

# Generate the upcoming schedule over a specific number of calendar days
python3 basketball_site_generator_v3.py preseason.json --out site --clean --schedule-days 46

# Change the first season shown on player stat pages
python3 basketball_site_generator_v3.py preseason.json --out site --clean --start-season 2026
```

## What it generates

- `index.html`: home dashboard — latest results strip, standings (playoff cutoff, SOS, last-10 dots, day-over-day movement arrows), playoff odds (5,000 Monte-Carlo season sims with magic/elimination numbers), league news feed, injury report, league leaders, rookie watch, heat-mapped team stats, Four Factors, and award voting sentiment.
- `schedule.html`: season grid — one column per team (color-coded), one row per day; the next game day is highlighted. Home games show as `vs. ABC`; away as `@ ABC`, with W/L results (incl. OT tags). Below it, a head-to-head matrix of every season series.
- `games/*.html`: box scores for completed games (with season-series footer); scheduled games get a full preview — side-by-side team comparison, both injury reports, and projected rotations.
- `teams/*.html`: front-office vitals (hype, attendance, cash, owner mood), last 5 / next 5 form strip, Roster tables (health, trade value, how acquired), depth chart by position, Finances (per-season salaries vs the cap with floor marker) and owned/traded draft picks.
- `players/index.html`: rostered players with Per Game / Advanced toggle and an interactive scatter chart (any two stats, position & minutes filters, outlier labels, shareable URL state).
- `players/*.html`: profile with ratings, development chart, season/career highs, current-season game log, full stat history, salary history, injury history, and family ties.
- `draft.html`: the upcoming draft class with heat-mapped prospect ratings (each prospect gets a page) plus the projected draft order with pick ownership.
- `trade.html`: Trade Center — an interactive trade machine (salary matching vs the hard cap + BBGM value verdict), the saved trading block with every AI offer, and a contract-efficiency board.
- `compare.html`: side-by-side comparison of any 2-3 players with rating bars; shareable URL.
- `free-agency.html`: free agents with their 15 detailed ratings (Physical / Shooting / Skill), heat-mapped, and asking price.
- `history.html`: champions, playoff brackets, award winners, All-League/All-Defensive/All-Rookie teams, stat leaders, and a full transaction log per season.
- `records.html`: all-time career leaderboards (including retired players) and every notable single-game feat.
- Team pages additionally show quarter-by-quarter scoring profiles, close-game/OT records, and dead money from waived contracts.
- Game pages show the player of the game and any recorded clutch plays.
- Global extras on every page: search box (press `/` to focus), stat-glossary tooltips on column headers, favorite-team star, and an "updated through Day X" footer.
- Standings movement arrows come from comparing against the previous `day*.json` (auto-detected, or pass `--prev day16.json`).
- A GitHub Action (`.github/workflows/build-site.yml`) regenerates and commits `docs/` whenever a new `day*.json` is pushed.

## Schedule and score behavior

The generator first looks for an explicit `schedule` or `scheduledGames` array in the JSON. If one is not present and the league is in an offseason/free-agency phase, it generates the upcoming regular-season round-robin schedule from the teams and `numGames` setting. If completed `games` exist for the selected schedule season, the schedule grid and game pages automatically switch from previews to final box scores.
