# Basketball League Site Generator v3

This script generates a static HTML hub from a Basketball GM-style JSON export.

## Basic usage

```bash
python basketball_site_generator_v3.py preseason.json --out site --clean --schedule-days 46
python3 basketball_site_generator_v3.py day11.json --out docs --clean
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

- `index.html`: home dashboard with standings, power rankings, team stats, and awards sentiment.
- `scores.html`: daily scoreboard with a Day dropdown. Every game row opens its game page.
- `schedule.html`: team schedule table with a team dropdown. Home games show as `vs. ABC`; away games show as `@ ABC`.
- `games/*.html`: one game page for every score/schedule row. Completed games show a full box score; scheduled games show a projected 5-starter/5-bench preview that populates once results exist in the JSON.
- `teams/*.html`: roster pages with starters, bench, reserves, all in alphabetical team navigation.
- `players/*.html`: player profiles with all ratings and stats from the configured start season onward.
- `free-agency.html`: free-agent table.

## Schedule and score behavior

The generator first looks for an explicit `schedule` or `scheduledGames` array in the JSON. If one is not present and the league is in an offseason/free-agency phase, it generates the upcoming regular-season round-robin schedule from the teams and `numGames` setting. If completed `games` exist for the selected schedule season, the score tables and game pages automatically switch from previews to final box scores.
