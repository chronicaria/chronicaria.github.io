# RWPA — MartinLutherKing & SN0RLAX

A static dashboard over round win probability added (RWPA) for one shared competitive Valorant
cohort: 19 matches, 410 rounds, every one of them scored.

Open `index.html`. That is the whole install — no framework, no build step, no server, no network
beyond a Google Fonts stylesheet. The data ships as `window.VAL_DATA` in `data.js` rather than
something to `fetch`, so it works opened straight off disk.

## What it shows

**Cohort.** A cumulative walk of RWPA over every round in play order, scaled to the data's own
range so the variation reads. Then a round-disposition bar, per-player totals with their 95%
intervals, a credit-type waterfall showing that each total is the residue of about forty units of
churn either way, and a forest plot of every estimand under all three eligibility scenarios — which
is where the intervals live, in the per-100 units everything else on the page is quoted in. The
single most important fact about this dataset is visible there: every interval that matters
includes zero except the two players taken together.

**Match.** Per-player summary, a per-round bar panel for each player against their own zero line,
and a round ledger.

**Round.** Selecting a round opens a sheet comparing the two players across probability, combat,
economy and events — one row set, shared by both, so line *n* on the left is line *n* on the right.

## Reading rules the page enforces

These come from the research release, not from taste. They are stated at the top of `style.css`
and `app.js` so a later edit cannot quietly break them.

- **The two players are never ranked.** `meta.gate.rank_players` is `false`. No arrow, no
  highlight, no leader column, no difference column, no sort that orders one above the other. Their
  intervals overlap, the paired difference is +0.239 per 100 rounds with an interval of
  [−2.68, +4.37], and its sign reverses across eligibility scenarios. They are also teammates in
  every match, so a versus frame is structurally wrong.
- **No cell's rendering is ever a function of the other player's value.** Magnitude bars scale to a
  cached corpus 95th percentile, never to `max(martin, snorlax)`.
- **Nothing that was not measured is rendered as `0.00`.** That applies twice over now. A round
  with no well-defined ending shows an em dash and a reason. So does a player in a round they were
  not in: a 4v5 round is fully scored for everyone who played it, and the absent player has no
  ledger rows at all, so their cells are em dashes rather than zeros. A zero would say they were
  present and did nothing.
- **A per-100 rate is suppressed below the exposure floor** of 20 eligible rounds.
- **Green is up, red is down, and a zero is neither.** Sign colour means the direction a
  probability moved; it never touches a name, a neutral count, or a win/loss chip. Sign is carried
  three times over — a `+`/`−` glyph, direction from a zero rule, and colour — because red/green is
  the one pair the common dichromacies cannot separate. `contrast.py` prints the evidence.
- **Nothing hardcodes a count.** Every number comes out of `VAL_DATA`.

## A note on the round table

The header is deliberately not sticky. `.table-wrap` sets `overflow-x: auto`, which makes it the
containing block for sticky positioning — so `top: 54px` did not hold the header below the site
header, it pushed the header *down* onto the first row and hid round 1 of every match. The bug
survived several rounds of measurement because the offset lands on the `<th>` cells while
`getBoundingClientRect()` on the `<tr>` still reports the unmoved row box: the rows never
overlapped, the cells did. `document.elementFromPoint` over row 1 returned the header cell, which
is what finally showed it. These tables run to 30 rows; a sticky header was never worth a bug that
deletes a row.

## Checking the palette

```bash
python3 contrast.py
```

Every token carrying text clears 4.5:1 against the row-hover surface in both themes; information
marks clear 3:1 including at partial opacity. The script also simulates both dichromacies and
fails loudly if the sign pair stops separating.

## Where the numbers come from

The payload is generated, not hand-written. It is built by `valorant_impact.dashboard_data` in the
research lab (kept separately, outside this repo) from the immutable release
`model_suite_release_2026-07-30_v4`, manifest SHA-256
`bab0ed0c8d177d9ca5cb1dca86cebd1bc610bb9acb0f4b9d8209793152637e17`:

```bash
python3 -m valorant_impact.dashboard_data --output dashboard/data.js
```

That build is fail-closed: a missing column, an unexpected row drop or a failed reconciliation
target raises rather than emitting a partial payload, and 92 tests assert the reconciliation
targets against the real release, and the payload rebuilds byte-identically.

### Short-handed rounds count

A round where somebody was inactive used to be discarded entirely. It is now scored: the active
roster already omits the absent player, so the alive counts describe a genuine 4v5 and the
win-probability model conditions on exactly those counts. All 37 such rounds in this cohort are
kept and marked `4v5` in the ledger; only the absent player is left uncredited. That took the
cohort from 341 of 376 rounds to 410 of 410.

It moved the numbers, and not cosmetically: the two players' point ordering reverses. Which is
precisely why the page does not rank them.

`data.js` also carries its own metadata, which is why nothing in `app.js` hardcodes what a metric
means: `dict` (119 entries with label, definition, unit, source file and column, format, and a
headline/diagnostic/exploratory/rejected tier), `meta.cav` (28 interpretation caveats), `meta.code`
(enum legends — `"d"` means *defense* in one field and *disadvantage* in another, which is exactly
the kind of thing a lookup copied into JS gets wrong silently), and `meta.gate` (the release's own
rules). A wrong number is a bug in the extractor, never in the view.

## Refreshing with newer matches

Collection needs a HenrikDev API key, which is not in this repo:

```bash
export HENRIK_API_KEY='...'
python3 -m valorant_impact.collect --all --page-size 10 --rate-floor 12 --output data/updates/refresh.json
```

Then merge, rebuild the SQLite box scores, run the model suite into a fresh release directory, and
regenerate `data.js`. The suite re-derives the cross-fitted ledger and the bootstrap intervals, so
the numbers on the page move with it.
