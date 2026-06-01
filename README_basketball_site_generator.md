# Basketball JSON Site Generator

This generator builds a static HTML league site from a Basketball GM-style JSON export.

## Run

```bash
python basketball_site_generator.py updated.json --out site --clean
```

Then open `site/index.html` in a browser.

## Generated pages

- `index.html`: league home dashboard with current-season standings, power rankings, team stats, and award voting sentiment.
- `teams/*.html`: one page per team, with Starters, Bench, and Reserve roster tables.
- `free-agency.html`: all available free agents with ratings, contract ask, and current stats.
- `players/index.html`: searchable player index.
- `players/*.html`: player pages with profile, summary, per-game stats, shot locations, advanced stats, playoffs, and full 15-rating history.

## Notes

- Team navigation is alphabetical.
- Team headers show total current-season salary against the JSON salary cap.
- Home dashboard charts include teams with current-season records/stats; team pages are still generated for every non-disabled team.
- Player names link to player pages everywhere they appear.
- The site is dependency-free: plain Python standard library, HTML, CSS, and JavaScript.
