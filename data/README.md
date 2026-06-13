# Editing the data files

Everything on the site renders from these files. Edit, push, done — no HTML required.
A GitHub Action validates every JSON file on push, so a stray comma fails loudly instead
of silently blanking a page.

## music.json (hand-edited)

- **Add a finished piece**: copy a row in `piano` or `violin`:
  `{ "composer": "...", "work": "...", "detail": "", "composed": 1234, "learned": "2026" }`
  (`detail` is for movement info or nicknames; keep `""` if none.)
- **Change what you're practicing**: edit `working` — `phase` is free text ("learning notes",
  "tempo work", "polishing").
- **Promote a planned piece**: delete it from `planned`, add it to `working` or the repertoire.
- Update the `updated` field so the page badge stays honest.

## books.json (hand-edited)

- **Reading progress**: bump `current.chapter`.
- **Finished a book**: move it into `years.2026` as
  `{ "title": "...", "author": "...", "pages": 350, "finished": "Jul 2026", "rating": 8, "take": "One sharp sentence." }`
  then set `current` to the next book (or `null`).
- **New year**: add a `"2027": []` key — the year dropdown appears automatically.

## sports.json + history/ (auto-generated — do not hand-edit)

Written by `scripts/update_sports.py` every 6 hours via GitHub Actions
(`.github/workflows/update-sports.yml`). To add or retier a team, edit the `TEAMS`
list at the top of the script. `history/<year>.json` accumulates every completed
game for future year-in-review pages.

## daily/ — The Gothic Times (auto-generated, except poems.json)

`scripts/update_daily.py` prints one edition per morning via
`.github/workflows/print-daily.yml`: `daily/<date>.json` (permanent archive),
`daily/latest.json` (what the page loads), and `daily/index.json` (date list).
Tune sources, weights, keyword boosts, or the battleground-race roster at the
top of the script. `daily/poems.json` is hand-edited — add stanzas freely; the
front page rotates one per edition. `daily/reading.json` is a 3,200-entry
archive of quant papers mined from the newsletter doc — the markets desk
rotates three picks per edition; append entries anytime.
