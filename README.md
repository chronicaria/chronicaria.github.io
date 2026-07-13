# chronicaria.github.io

Static site for the SMP Basketball League.

The site is generated from Basketball GM-style JSON exports in `league-data/`.
The generated league pages live at the repository root so GitHub Pages serves
the league homepage at `/`.

## Structure

```
index.html          League homepage
schedule.html       Schedule and scores
players/            Player index and player pages
teams/              Team pages
games/              Box score pages
assets/             League CSS, JS, and search index
league-data/        Source JSON exports
scripts/            League site generator
```

## Regenerate

```sh
python3 scripts/league_generator.py league-data/2030_day44.json --out .
```

The `Build SMP league site` GitHub Action regenerates the root site from the
newest `league-data/day*.json` export on pushes to `main`.
