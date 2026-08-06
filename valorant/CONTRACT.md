# Payload contract — the four-player impact dashboard

Every builder codes against this file. It is frozen: if a field is missing, add it here in the same
change that emits it. The view hardcodes no definition, no format and no rule — `meta.dict`,
`meta.gate` and `meta.cav` come from the payload, exactly as the existing dashboard does.

## Paths

| Path | What |
|---|---|
| `valorant/payload/site.json` | front page, tracker, match index |
| `valorant/payload/player/<short>.json` | one per focal player (4) |
| `valorant/payload/match/<match_id>.json` | one per match |
| `valorant/build.py` | reads payload, emits static HTML with the JSON inlined |

Working data (already generated, read-only inputs):

```
$LAB  = ~/Desktop/Rome/Sports/Esports/Valorant/valorant-impact-lab
$WORK = $LAB/data/quad_work_2026-08-04
  $WORK/ids.txt                              one match id per line
  $WORK/rwpa_crossfit_ledger.csv             the act slice of the v15 ledger, one row per round-player
  $WORK/rwpa_crossfit_rounds.csv             one row per round
  $WORK/rwpa_crossfit_event_values.csv       13,621 events, action-by-action probabilities
  $WORK/out/mwpa_round_players.csv           THE core artifact: one row per (match, round, player)
  $WORK/out/mwpa_player_summary.csv          648 players, MWPA rate with BCa interval
$DB   = $LAB/data/valorant_matches_v16.sqlite3
$FIT  = $LAB/data/model_v15_scoring/rwpa_model.joblib

`$WORK` lived in a /private/tmp session scratchdir until 2026-08-04, which the operating system
is entitled to delete — the site's own build depended on temp space belonging to a session that
had ended. `$FIT` is the core model the v15 release never persisted: cross-fitting keeps its
held-out predictions and discards the fold models, so a match collected after the release was cut
has nothing in it to be scored by. See `meta.cav.two_scoring_provenances`.
```

`mwpa_round_players.csv` columns: `match_id, round_id, puuid, player, team, agent, is_focal,
rwpa, raw_kill_credit, raw_death_debit, raw_plant, raw_defuse, raw_alive_clock, lobby_mean_others,
rwpa_centered, round_player_count, map, started_at, round_number, score_diff, attack_team,
attack_won, terminal_type, winning_team, attack_loadout_k, defense_loadout_k, active_player_count,
attack_score_before, defense_score_before, side, own_score_before, other_score_before, leverage,
mwpa, mwpa_kill_credit, mwpa_death_debit, mwpa_plant, mwpa_defuse, mwpa_alive_clock, team_loadout,
buy_class, round_won, weapon, armor, player_loadout, remaining_credits, round_kills, round_damage`

## The four focal players

| puuid | name | short |
|---|---|---|
| `ab8bf38e-c2c4-5408-9a96-90ee3eb01af9` | MartinLutherKing#racis | `martin` |
| `7b17dc93-bba8-50f3-ba4f-7e753d901a65` | SN0RLAX#143 | `snorlax` |
| `82d91329-7a9d-5d30-ac3f-5cd2e4764d15` | TheMarias#Bunny | `themarias` |
| `bafecb36-4e90-5f84-adc7-04d6acb22dfa` | Trzzcko#SFang | `trzzcko` |

Everyone else is `Anonymous#<6 hex>` and stays that way. Pseudonyms are match-scoped: **never link a
non-focal player across matches**, and never build a page for one.

## Units and naming

- `mwpa` is **match win probability points**, and it prints as a percentage: `+62.00%` is six
  tenths of a match win. A total keeps `+.3f` and reads as "matches added".
- **The headline is `impact`, per MATCH PLAYED**, not per 100 rounds: `impact = total / matches`,
  `impact_lo = lo * (rounds / matches) / 100`, `impact_hi` the same. It is a per-player positive
  constant rescale of the bootstrapped rate — rounds per match runs 19.5 to 21.2 across the four —
  and BCa is transformation-respecting, so the endpoints carry across exactly and `covers_zero` is
  unchanged. No second bootstrap. `+6.4%` reads as six extra wins per hundred matches.
- `rate`, per 100 rounds, is the estimator's own unit. It survives on the
  **breakdown and synergy tables**, whose cells cannot be divided by a match count — see the rule
  under `player/<short>.json`. It appears nowhere else: no headline, no tracker, no index, no
  component waterfall. `rwpa` and `rwpa_centered` stay in the working data and out of every view.
- `leverage` is the raw swing `L` in [0, 0.5]. `li` is `L / mean_leverage` — the display index only,
  never multiplied into anything. `mean_leverage = 0.16427272872711246`.
- An interval is 95% BCa, clustered on match, 100,000 resamples, seed 20260726.

## `site.json`

```jsonc
{
  "meta": {
    "act": "e11a4",
    "release": "model_suite_release_2026-08-02_v15",
    "matches": 68, "rounds": 1438, "round_players": 14290, "players": 576,
    "bootstrap": 100000, "seed": 20260726, "confidence": 0.95,
    "mean_leverage": 0.16427272872711246,
    "generated_at": "<ISO date>",
    "gate": {
      "rank_players": true,          // flipped from the release default; see cav
      "rate_floor_rounds": 0,        // suppression is OFF
      "rate_floor_marker_rounds": 20,// below this, mark the cell as thin
      "exposure_threshold_rounds": 726,
      "side_split_rounds": 14000,
      "null_rate": 0.0, "null_probability": 0.5,
      // THE LADDER. Riot's own enum, read off `raw_matches.payload_json` across the whole
      // corpus and sorted by id, WITH ID 0 REMOVED. Id 0 is the unranked state and it sits
      // below Iron 1 on the same integer scale, so plotting the enum drops "no rank issued
      // yet" a division under the bottom of the ladder. Position on this array, one-based,
      // is `ordinal` and is the only number allowed to be a y value for a division.
      "tier_order": [ {"id":3,"name":"Iron 1"}, /* … */ {"id":25,"name":"Immortal 2"} ],
      "tier_axis_min_span": 3,       // divisions; a flat path must not fill its own panel
      "tier_placement_matches": 5,   // measured on the act, not assumed
      // THE CARD'S TWO LISTS. The name of the gun that does not count and the length of a list
      // are both decisions, so neither is typed in the view. `free_pistol` is excluded from
      // `card.weapons` because every player starts every pistol round holding it — its count
      // measures the act's round structure, not the player. `cav.classic_is_the_free_pistol`.
      "free_pistol": "Classic",
      "card_top_n": 3,
      // The two credit types the component waterfall draws as ONE signed row. The view reads
      // the names from here, for the sum assertion `build_player` refuses to ship without.
      "duel_parts": ["kill_credit", "death_debit"],
      "duel_key": "duel_credit"
    },
    // The ladder measured against the rating, so the view quotes a number rather than
    // retyping one. See cav.tier_is_not_mwpa for what it means.
    "ladder": {
      "n": 101, "minimum_ranked": 5,
      "r_mwpa": 0.074, "r_lobby_adjustment": 0.118, "r_lobby_adjustment_rate": 0.065,
      "lobby_spread_median": 4.0, "lobby_spread_max": 7
    },
    // EVERY IMAGE FAMILY THAT SHIPS, and it is the complete list: build.py reads the folder name
    // off each path here and refuses to run against a folder on disk that no family claims, or a
    // family here whose folder is gone. Three families, declared identically, from one slug rule
    // (`[^a-z0-9]+` -> `-`, stripped). Each is an explicit name -> path map, so the view resolves
    // a picture by LOOKUP and never by string surgery: a name absent from `files` renders the
    // word alone and there is no way to emit a broken image. `px` is the same keys against each
    // file's real intrinsic [w, h], read from its IHDR, so a view can contain-fit a non-square
    // family — weapon art is 96 wide at 17 to 73 tall — without guessing a shape or reflowing a
    // row. `intrinsic_px` is the family's nominal edge (its widest file). The name set per family
    // is what the ACT contains, never the platform's catalogue, so `missing` and `unused` are an
    // audit somebody could act on. The builder fails on `unused`; `missing` only prints, because
    // rendering the word alone is the designed behaviour and not a defect.
    //
    // `Unrated` is in no family and never can be: it is not a division, it is the absence of one,
    // and it is 21.8% of act player-matches. See `cav.unrated_is_not_a_division`.
    "assets": {
      "agent":  { "dir": "assets/agent/",  "intrinsic_px": 40,
                  "files": { "Sova": "assets/agent/sova.png" /* … 29 */ },
                  "px": { "Sova": [40, 40] },
                  "missing": [], "unused": [], "source": "", "job": "" },
      "weapon": { "dir": "assets/weapon/", "intrinsic_px": 96,
                  "files": { "Vandal": "assets/weapon/vandal.png" /* … 19 */ },
                  "px": { "Vandal": [96, 29] },
                  "missing": [], "unused": [], "source": "", "job": "" },
      "rank":   { "dir": "assets/rank/",   "intrinsic_px": 48,
                  "files": { "Silver 1": "assets/rank/silver-1.png" /* … 11 */ },
                  "px": { "Silver 1": [48, 48] },
                  "missing": [], "unused": [], "source": "", "job": "" }
    },
    "dict": { "<field>": {"label":"", "definition":"", "unit":"", "format":"", "tier":""} },
    "cav": [ {"id":"", "text":""} ]
  },
  "players": [ {
    "puuid":"", "name":"", "short":"", "rank": 1,
    "impact": 0.06371, "impact_lo": -0.039079, "impact_hi": 0.23311,
    "rate": 0.1063, "lo": -0.1257, "hi": 0.3175, "covers_zero": true,
    "total": 0.646143, "rounds": 608, "matches": 29,
    "ladder": {"first":"Bronze 1","last":"Silver 1","low":"Bronze 1","high":"Silver 1",
               "placement": 5, "ranked": 27, "steps_up": 4, "steps_down": 1}
  } ],
  "tracker": { "<short>": [ {
    "i": 0, "match_id":"", "started_at":"", "map":"", "mwpa": 0.031, "cumulative": 0.031,
    "rounds": 21, "won": true
  } ] },
  "matches": [ {
    "match_id":"", "started_at":"", "map":"", "rounds": 21,
    "score": [13, 8], "won": true, "focal": ["martin","snorlax"]
  } ]
}
```

`players` is sorted by **`impact`** descending and carries `rank` derived from that order. The
generator asserts the order is the one `rate` gave, so a ranking argument made on the old headline
still holds. Ranking is ON by decision; every card must still render its interval, and
`covers_zero` drives the wording.

## `player/<short>.json`

```jsonc
{
  "puuid":"", "name":"", "short":"",
  "headline": {"impact":0,"impact_lo":0,"impact_hi":0,
               "rate":0,"lo":0,"hi":0,"covers_zero":true,"total":0,"rounds":0,"matches":0},
  // THE CARD. The only block on this site that is COUNTS rather than estimates: nothing in it
  // carries an interval and no null rule is drawn through it. `agents` is ordered by MATCHES
  // (an agent is a per-match choice), ties broken on rounds then name; `weapons` by ROUNDS (a
  // gun is a per-round choice), with `gate.free_pistol` removed and its own count kept so the
  // caveat can quote it. Both lists are cut to `gate.card_top_n` and NEITHER IS PADDED: a
  // player with two agents emits two. `agents_played` is the full count behind the top three.
  "card": { "matches": 38, "rounds": 782, "rounds_per_match": 20.58,
            "kills_per_match": 14.82, "deaths_per_match": 14.89, "assists_per_match": 4.95,
            "agents": [ {"name":"Sova","matches":29,"rounds":606} ], "agents_played": 3,
            "weapons": [ {"name":"Phantom","rounds":268,"share":0.3912} ],
            "weapon_rounds": 685, "weapon_excluded": {"name":"Classic","rounds":97} },
  // FIVE ROWS, and the first is the duel. `duel_credit` is `kill_credit + death_debit` summed
  // per round-player and RESAMPLED AS ITS OWN COLUMN — the two are strongly negatively
  // correlated within a round, so its interval is not the two intervals added.
  // `cav.the_duel_is_one_row`. `share` is over these five, so the five shares sum to one.
  "components": { "duel_credit": {"rate":0,"lo":0,"hi":0,"total":0,"share":0.41},
                  "plant": {}, "defuse": {}, "alive_clock": {}, "lobby_adjustment": {} },
  // The two halves of that row, kept because combining them is a DISPLAY decision and a reader
  // may not be asked to take a ledger on trust. No `share`: the shares belong to what is drawn.
  "duel_parts": { "kill_credit": {"rate":0,"lo":0,"hi":0,"total":0}, "death_debit": {} },
  "rank_track": [ {"i":0,"match_id":"","started_at":"",
                   "tier": null, "ordinal": null, "state": "placement"},
                  {"i":5,"match_id":"","started_at":"",
                   "tier":"Bronze 1", "ordinal":4, "state":"ranked"} ],
  "ladder": {"first":"","last":"","low":"","high":"","placement":5,"ranked":27,
             "steps_up":4,"steps_down":1},
  "matches": [ {"match_id":"","started_at":"","map":"","agent":"","tier": "Bronze 2" | null,
                "mwpa":0,"rounds":0,"won":true,
                "attack_mwpa":0,"defense_mwpa":0} ],
  "breakdowns": {
    "agent":     [ {"key":"Sova","rounds":0,"matches":0,"rate":0,"lo":0,"hi":0,"total":0,
                    "covers_zero":true,"thin":false} ],
    "map":       [ ... ], "side": [ ... ], "buy_class": [ ... ], "weapon": [ ... ]
  },
  "synergy": [ {"partner_short":"snorlax","partner_name":"SN0RLAX#143","shared_matches":27,
                "shared_rounds":560,"rate":0,"lo":0,"hi":0,"covers_zero":true,"thin":false} ]
}
```

Rules that are not optional:

- `impact` is on the **headline block only**. A **breakdown or synergy** cell keeps `rate` with its
  interval and gets no `impact`: those cells are a slice of a match rather than a match, so their
  match count is a count of matches the cell appeared in and not an exposure to divide by. `Other`
  weapons are 1.2 rounds of martin's 21.2-round match; a per-match number over 1.2 rounds would sit
  on the same axis as `+6.4%` while meaning something else.
- **A component is the exception, and the view converts it.** A component's rounds *are* the
  headline's rounds — trzzcko's kill credit is `+3.092` over the same 163 rounds that give the
  `+1.8968` rate — so `total / matches` sums to `impact` to 1e-9 on all four players and the BCa
  endpoints take the same positive constant `impact_lo` takes. The component waterfall is per
  match. The payload still carries `rate`; the conversion is the view's and is reversible.
- `meta.dict` carries the format for every field and nothing else may decide one. Every field whose
  unit is **match win probability points** is a percentage: `mwpa` and the six component keys —
  `kill_credit`, `death_debit`, `plant`, `defuse`, `alive_clock`, `lobby_adjustment` — the four
  grains `grain_action`, `grain_round`, `grain_match`, `grain_act`, and the two side splits
  `attack_mwpa` and `defense_mwpa` are `+.2%`. `dp` and `impact` are `+.2%` too, overridden in
  build.py's `DECIMALS` on 2026-08-06: the payload writes both at `+.1%`, and one decimal cannot
  resolve two of these four players from each other. `rate` and `total` keep `+.3f` —
  they are the only two in other units, per 100 rounds and matches added. The six that were `+.4f`
  were the same quantity as `mwpa` written as a raw decimal, and methods.html contradicted them
  out loud: it named the shared grain ruler as 70.66% while the rail under it drew 0.7066.
  `lobby_adjustment` was the one payload field with no dictionary entry; it has one now.
- `thin` is `rounds < meta.gate.rate_floor_marker_rounds`. The cell still renders a number — the
  decision was to show everything with its interval — but the view marks it.
- A cell with **no** rounds is omitted from the array entirely. It must never render as `0.00`.
- `side` has exactly two keys, `attack` and `defense`. Both will have very wide intervals: the side
  contrast needs roughly 14,000 rounds against the 1,438 in this act. Say so in `cav`, once.
- `weapon` is the round-start primary from `round_players.weapon`. Group anything under 10 rounds
  into `Other` rather than emitting a tail of one-round rows.
- `synergy` carries all six ordered pairs the player is part of (three per player). Only
  martin×snorlax has real exposure; the rest will be near-empty and that is the finding.
- `components` carries `lobby_adjustment`. The five credit types decompose the raw
  ledger, which is what the ledger has; the headline is the ledger *after* leave-one-out lobby
  centering, and that centering belongs to no credit type. Without that row the rest would not
  sum to the headline. `cav.components_include_the_lobby_adjustment` carries the reason.
- **`card` is the one block with no interval on it, and the view must not give it one.** A kill
  happened; an impact per match is an estimate. The two registers sit in the same object at the
  top of a player page and are drawn apart — the headline keeps its span and its null verdict,
  the counts get neither. `cav.the_card_is_counts_not_estimates`.
- **`tier` is `null` for a match played before the platform issued a rank, and never anything
  else.** Not `0`, which is a number it does not have. Not an em dash, which on this site means
  *not measured* — this is measured, and the measurement is that no division existed yet. Not the
  platform's own string for the state, which is the name of a **queue** on every reference site in
  this space and reads as "that was a casual match" beside 68 Competitive ones. `rank_track[].state`
  carries the word the view prints. Verified rather than assumed: every act player who has such a
  match has it as a strict prefix of their act, with zero counterexamples, and
  `cav.tier_placement_window` publishes the count.
- `rank_track` is one row per match in the player's own order, the same order as `matches`, and the
  builder asserts the two lengths agree. `ordinal` is a one-based position on
  `meta.gate.tier_order`; it is the ONLY number a figure may use as a y value for a division.
- `ladder.steps_up` / `steps_down` count changes between **consecutive ranked matches**, so the
  placement prefix contributes none.

## `match/<match_id>.json`

```jsonc
{
  "match_id":"", "started_at":"", "map":"",
  "teams": [ {"team_id":"Red","rounds_won":13,"won":true,"focal":true} ],
  "lobby_tiers": {"low":"Iron 3","high":"Bronze 3","ranked":7,"placement":3},
  "players": [ {"puuid":"","name":"","short":null,"team":"","agent":"","is_focal":false,
                "mwpa":0,"rwpa":0,"rounds":21,"kills":0,"deaths":0,"assists":0,"damage":0} ],
  "match_wp": [ {"round_number":1,"own":0,"other":0,"wp_before":0.5,"wp_after":0.548,
                 "won":true,"leverage":0.1612,"li":0.98} ],
  "rounds": [ {
    "round_id":0, "round_number":1, "terminal_type":"elimination", "winning_team":"Red",
    "own":0, "other":0, "leverage":0.1612, "li":0.98,
    "buy": [ {"team_id":"Red","side":"attack","loadout":4300,"class":"eco"} ],
    "events": [ {"i":0,"t":13820,"type":"kill","actor":"<puuid>","victim":"<puuid>",
                 "p_before":0.512,"p_after":0.606,"delta":0.094} ],
    "players": [ {"puuid":"","team":"","agent":"","side":"attack",
                  "rwpa":0,"rwpa_centered":0,"mwpa":0,
                  "kill_credit":0,"death_debit":0,"plant":0,"defuse":0,"alive_clock":0,
                  "duel":["opening_kill"],"weapon":"Vandal","loadout":3900,"credits":800,
                  "kills":1,"damage":142} ]
  } ],
  "top_plays": [ {"round_number":19,"puuid":"","name":"","type":"kill_credit","mwpa":0.081,
                  "leverage":0.5,"p_before":0.31,"p_after":0.72,"round_own":12,"round_other":12} ]
}
```

Rules:

- `rounds` is the array. An earlier draft of this file also listed a scalar `"rounds": 21` under the
  same key; the count is `len(rounds)` and no scalar is emitted. `site.matches[].rounds` is the
  scalar, and the two agree — the builder asserts it.
- `match_wp` is from the **focal side's** perspective. `wp_before` is
  `match_leverage.match_win_probability(own, other)` entering the round; `wp_after` is the same
  after the round resolves. This is a reconciliation, not an identity — do not assert that the last
  value equals the outcome. Over the cohort the last state's probability differs from the outcome by
  mean 0.052, and 5.9% of rounds by more than 0.20.
- `events` come from `rwpa_crossfit_event_values.csv`: `probability_before_action` →`p_before`,
  `probability_after_action` → `p_after`, both attack-perspective. Convert to focal-side perspective
  in the payload, not in the view.
- **`duel` tags** come from `valorant_impact/duel_roles.py` (being written alongside this):
  `opening_kill`, `opening_death`, `trade`, `traded`, `clutch_won`, `clutch_lost`, `multi_kill`.
- **`top_plays` ranks by `abs(mwpa)` of a single ledger row**, not by round total, and is signed.
  Deaths will appear — the death debit is 46% of a typical player's absolute ledger. Label the type
  honestly; do not filter to positives.
- Abilities do not exist at any grain. Do not emit an `abilities` key, do not render a zero for one.
  `cav` carries the reason.
- **`lobby_tiers` is a range and a count, and the per-player division is deliberately not here.**
  Ten divisions across 68 pages is 680 cells putting a rank beside an MWPA, which is exactly the
  misreading `cav.tier_is_not_mwpa` exists to prevent. The range answers the question the page does
  ask — who was this against — and its answer is that a lobby is not division-homogeneous. There is
  no `spread` field either: the two names are the spread, and a number nothing renders is an
  invitation to a later contributor to find it a column.

## House rules the view must not break

1. Nothing unmeasured renders as `0.00`. An em dash and a reason.
2. Green is up, red is down, zero is neither. Sign is carried three ways — glyph, position, colour —
   because red/green is the one pair the common dichromacies cannot separate.
3. No cell's rendering is a function of another player's value. Every mark scales to a fixed
   axis carried in the payload, never to `max(row)`.
4. **No table draws a magnitude bar.** The number is the number: a bar beside a signed number
   restated a fact the cell already printed, at a coarser precision than the cell has. What a
   table may still draw is an **interval**, which is not a magnitude — its width is a quantity
   that appears nowhere else in the row, and the round ledger's stacked bar, which draws a shape
   no cell holds. The solid-bar-from-the-null mark survives in the component waterfall, in SVG.
5. **No `Rounds` column and no `Rounds` stat row, anywhere.** The count stays only where it is
   load-bearing prose: inside the covers-zero sentence, which is the sentence that tells a reader
   why an interval is as wide as it is and is the reason the Exposure section could be deleted;
   in the `Exposure` cell's `title`, where it is said against the threshold; in the card's
   `rounds_per_match`, which is what a match *means*; and in the footer, which prints the act's
   size on every page. The count of pages is not stated here: `main()` asserts it.
6. Nothing hardcodes a count. Every number comes from the payload.
7. Every page opens off disk. No `fetch`, no CDN, no web font that blocks render.
8. **An image identifies; it never measures.** Three families ship, and these are their homes:

   | Family | Files | Home | Rendered |
   |---|---|---|---|
   | `assets/agent/` | 29 at 40×40 | Agent column, match page's ten-player table | 18 px in a 1 px `--rule-strong` box |
   | `assets/agent/` | " | **player card, most-played agents** | **40 px — the file's own `intrinsic_px`** |
   | `assets/rank/` | 11 at 48×48 | trajectory y axis; match masthead's lobby range | 18 px in the same box |
   | `assets/weapon/` | 19 at 96×17…73 | `by weapon` breakdown rows | contain-fitted into 42×18 on an `--art-plate` |
   | `assets/weapon/` | " | **player card, most-used guns** | **contain-fitted into 96×36 on the same plate** |

   The card is the one place art is not 18 px, and the reason is structural rather than
   aesthetic: everywhere else the picture rides inside a table row and the row's line box is the
   constraint. A card is not a row. Contrast is a property of the composited pixels and not of
   the size, so `../contrast.py`'s measurements for both families carry across unchanged — and
   the weapon plate comes with them, because the plate is what fixed 1.53 in the light theme.
   Both slots still emit the word, so the identity control still takes every picture away
   without losing a fact.

   **Every picture sits beside a word that is always rendered, and the word is what encodes.**
   `alt=""` and `aria-hidden` are correct for all three for that reason: the word is in the same
   object, so `alt="Sova"` makes a screen reader say Sova twice. Every element carries an explicit
   `width`/`height` from the payload's own `px`, so nothing reflows and nothing is distorted.
   The identity control in the header removes all 59 files at once and **no fact leaves the page**
   — verified per page type, not asserted — which is the test any future family must pass.

   Two rules follow from where they are allowed rather than from what they are, and both exist to
   answer objections that were correct:
   - **A rank badge never travels without its division word, and never shares a cell with a mark in
     a player hue.** Riot's tier art is hue-coded and its gold lands within OKLab ΔE 3.5 of
     `--martin`; on a site whose rule is *hue is a person* that collides only if the badge is the
     sole carrier of which rank, so it never is. `rank_cell()` is the only path to a badge and it
     always emits the word. It ships where the badge is the *subject* — three to five axis rows,
     two lobby ends — and takes `badge=False` where the column would repeat, which is measured, not
     felt: the per-match table is 45 of 60 rows one division.
   - **A weapon icon ships only where every row is a distinct weapon.** In the `by weapon`
     breakdown that is guaranteed by construction — n shapes for n rows. In the round ledger the
     modal weapon takes 50.0% of a ten-seat column and the top two 70.0%, so it stays words.
     `cav.where_imagery_is_allowed` carries both measurements. Every percentage on this site
     carries one decimal, including the ones inside an argument.

   `cav.imagery_is_not_a_mark` fixes the measurement in the record, `cav.riot_assets` the
   provenance, `cav.unrated_is_not_a_division` the one value with no picture.
   `../contrast.py` gates each family separately: it decodes every PNG, composites every pixel with
   alpha ≥ 0.4 onto every surface *that family* lands on, requires the slot to clear the 3:1 mark
   floor, and fails the run when the family's median file falls under the legibility floor — which
   is derived from `--rule`, this design's own structural hairline, rather than chosen. **A family
   that fails is a slot that is wrong**: the weapon silhouettes measured 1.53 against `--field` in
   the light theme and were fixed by giving them a theme-invariant plate (6.99 in both themes), not
   by lowering the floor. The rank badges take no plate because measurement said they do not need
   one and a plate would cost them 1.25 in the light theme.
