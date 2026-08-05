# MWPA — four players, one act

A static site over **impact per match**: how much of a match win a player's credited actions are
worth, per match played. Four focal players, one act (e11a4), 78 matches, 1,617 rounds, every one
of them scored.

Open `index.html`. That is the whole install — no framework, no build step, no server, no network,
and no web font. Each page inlines its own data as `window.QUAD` and loads the corpus-wide half
from `quad-shared.js`, so the site works opened straight off disk.

This directory used to hold two sites: an RWPA dashboard at the top and this one under `quad/`.
The dashboard was retired on 2026-08-05 and this moved up into its place. `contrast.py` still
carries that dashboard's palette tables, unread, because surviving comments quote their numbers.

## The metric

`impact = MWPA / matches played`, shown as a percentage. `+1.6%` reads as *worth about one and a
half extra wins per hundred matches*. It is the per-100-rounds rate rescaled by the player's own
rounds per match — a positive constant — so the BCa endpoints carry across unchanged and so does
`covers_zero`. The per-100-rounds rate survives on `methods.html` as the estimator's own unit.

**The result is a null.** All four intervals cover zero, and the widest is many times the entire
spread of the order they are ranked in. The rank is a sort order; the interval is the finding.

## Build

```bash
python3.12 payload_site.py     # payload/site.json + payload/player/*.json  (needs numpy/pandas)
python3.12 payload_match.py    # payload/match/<match_id>.json, one per match
python3 build.py               # 84 pages: index, methods, 78 match, 4 player
python3 contrast.py            # the colour and artwork gate; must print PASS
```

`build.py` reads only `payload/` and is deterministic: rebuilding without new data changes no byte
of any file. The assertions in `main()` are the contract — if one fires, the code that fired it is
wrong, and relaxing it to make a build pass is never the fix.

`--rescale` re-pins the magnitude-bar axes in `payload/scale.json`. They are pinned rather than
recomputed so that adding a match does not move every bar on every page; only `impact` widens on
its own, and only outward, because a clipped interval on the figure that exists to say the
intervals are wide is the one bar this site cannot draw.

## Adding matches

The corpus, the model and the box scores live in the lab rather than here — `CONTRACT.md` carries
the paths, and `meta.cav.two_scoring_provenances` carries why matches collected after the model
release are priced by a refit rather than by a cross-fitted fold.

Surrendered **rounds** are awarded rather than played and stay outside every number. The rounds
played before a concession stay in: they ran under a real race to 13, against a score nobody yet
knew would be conceded.

## What is not here

No opponent is named. Every player other than the four is a match-scoped pseudonym, so one person
appearing in two matches carries two unrelated names and nothing links them. No career total
appears anywhere and nothing is pooled across acts. Every page ships
`<meta name="robots" content="noindex, nofollow">`, and `/valorant/` is deliberately absent from
`sitemap.xml` — which is not the same as being private, and `methods.html` says so.
