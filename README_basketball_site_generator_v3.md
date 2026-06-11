# Basketball League Site Generator v3

This script generates a static HTML hub from a Basketball GM-style JSON export.

## Basic usage

```bash
python basketball_site_generator_v3.py preseason.json --out site --clean --schedule-days 46
python3 basketball_site_generator_v3.py day16.json --out docs --clean
```

Then open:

```bash
site/index.html
```

## Useful options

```bash
# Force the Schedule/Scores hub to a specific season
python basketball_site_generator_v3.py preseason.json --out site --clean --schedule-season 2028

# Generate the upcoming schedule over a specific number of calendar days
python basketball_site_generator_v3.py preseason.json --out site --clean --schedule-days 46

# Change the first season shown on player stat pages
python basketball_site_generator_v3.py preseason.json --out site --clean --start-season 2026
```

## What it generates

- `index.html`: home dashboard with standings (playoff cutoff line below 4th place), heat-mapped team stats (red→green; reversed for TOV/PF/PA), and awards sentiment.
- `scores.html`: daily scoreboard defaulting to the most recent played day, with compact `STO 96 @ DUR 110` score cards. Every card opens its game page.
- `schedule.html`: season grid — one column per team, one row per day. Home games show as `vs. ABC`; away games as `@ ABC`, with W/L results filled in for completed games.
- `games/*.html`: one game page for every score/schedule row. Completed games show a full box score; scheduled games show a projected 5-starter/5-bench preview that populates once results exist in the JSON.
- `teams/*.html`: roster pages with starters, bench, reserves, reachable from the Teams dropdown in the nav.
- `players/index.html`: rostered players only (free agents live on the Free Agency page), with a Per Game / Advanced (TS%, USG%, ORtg, DRtg, OBPM, DBPM, BPM, VORP, WS) toggle.
- `players/*.html`: player profiles with all ratings and stats from the configured start season onward.
- `free-agency.html`: free agents with their 15 detailed ratings (Physical / Shooting / Skill) and asking price.

## Schedule and score behavior

The generator first looks for an explicit `schedule` or `scheduledGames` array in the JSON. If one is not present and the league is in an offseason/free-agency phase, it generates the upcoming regular-season round-robin schedule from the teams and `numGames` setting. If completed `games` exist for the selected schedule season, the score tables and game pages automatically switch from previews to final box scores.
