# PLAN — converting the Fantasy Football Encyclopedia from 12 teams to 10

Written 2026-07-31. Not a corpus page. This file sits at the corpus root next to
`README.md`; `build.py` reads only the Obsidian vault and never scans this directory, so
nothing here is published. Do not move it into the vault — `build.py` skips exactly one
filename (`_PLAN.md`, line 130) and any other `_PLAN-*.md` would render into
`meta/` on the next build.

---

## 0. Where the corpus actually lives, and what that means for every edit below

**The HTML in `/fantasy/football/` is output, not source.** `build.py` line 26:

```python
VAULT = Path("/Users/andrewpark/Desktop/Rome/Sports/NFL/Fantasy Football")
OUT   = Path(__file__).resolve().parent
```

109 markdown notes in that vault render to 118 HTML pages here. Editing the HTML is
wasted work — the next `python3 build.py` overwrites it. **Every prose edit in this plan
is an edit to the vault.** The only edits that belong in the repo are to `build.py`
itself.

The dependency chain, in build order:

```
Rome/…/Fantasy Football/Data/players.csv          ← the spreadsheet-is-truth input
Rome/…/Fantasy Football/Data/player_context.csv   ← observed nflverse/injury/contract data
        │
        ├── Data/build_board.py   → writes Draft/2026 draft board.md
        │                         → writes Draft/Tiers by position.md
        ├── Data/simulate_season.py → writes Draft/When to start drafting for upside.md
        │
        └── PersonalSite/fantasy/football/build.py
                 ├── re-implements the board arithmetic (build.py:220) for draft-room.html
                 ├── copies both CSVs to fantasy/football/data/
                 └── renders all 109 notes → 118 HTML pages
```

Three files independently hard-code the replacement baselines and the pick sequence.
**They must be changed together or the site will contradict itself**, which is the exact
failure `build_board.py`'s docstring says it exists to prevent ("so the interactive table
and the markdown note can never disagree").

Rebuild sequence after any edit, from the corpus root:

```bash
cd "/Users/andrewpark/Desktop/Rome/Sports/NFL/Fantasy Football/Data"
python3 build_board.py           # regenerates 2026 draft board.md + Tiers by position.md
python3 simulate_season.py       # regenerates When to start drafting for upside.md (slow)
cd /Users/andrewpark/Desktop/Code/PersonalSite/fantasy/football
python3 build.py                 # ~2s, regenerates all 118 pages
cd /Users/andrewpark/Desktop/Code/PersonalSite
python3 scripts/inject_hub.py    # build.py strips the hub tag; this puts it back (README)
```

---

## 1. What actually changes at 10 teams

### 1.1 The mechanism: demand falls, the supply curve does not move

Replacement level in this corpus is not a convention borrowed from a ranking site. It is
derived from this league's own roster, and the derivation is stated twice — `_PLAN.md`
§1.2 lines 85–87, and the comment above `BASELINE_RANK` in `Data/build_board.py:25`:

```python
# _PLAN.md §1.2 — effective starters, FLEX split 40% RB / 55% WR / 5% TE.
# These are the replacement baselines. They are NOT copied from a published
# source's assumed lineup; they are derived from this league's roster.
BASELINE_RANK = {"RB": 29, "WR": 31, "TE": 12, "QB": 12, "K": 3, "DST": 3}
```

The derivation at 12 teams (`_PLAN.md` line 85–86):

> - League-wide starting slots: QB 12 · RB 24 · WR 24 · TE 12 · FLEX 12 · D/ST 12 · K 12
> - FLEX in full PPR splits roughly 40% RB / 55% WR / 5% TE → **effective starters ≈ RB 29, WR 31, TE 12**

Run the identical arithmetic at 10 teams. Nothing about the FLEX split changes — it is a
property of full-PPR scoring, not of league size.

| Pos | Fixed slots (10 tm) | Share of the 10 FLEX slots | Effective starters | Was (12 tm) |
|---|---:|---:|---:|---:|
| RB | 20 | 0.40 × 10 = 4.0 | **24** | 29 |
| WR | 20 | 0.55 × 10 = 5.5 | **26** | 31 |
| TE | 10 | 0.05 × 10 = 0.5 | **10** | 12 |
| QB | 10 | — | **10** | 12 |
| K | 10 | — | *not team-derived — see §1.5* | 3 |
| D/ST | 10 | — | *not team-derived — see §1.5* | 3 |

`RB 24` is exact (20 + 4.0). `WR 25.5` rounds to **26** under the same round-half-up the
12-team numbers used (28.8→29, 30.6→31). TE takes the flat starter count, exactly as the
12-team build did — it discarded its own 0.6 FLEX share to land on 12, and the board note
then says in prose "only the 12th tight end and the 12th quarterback," so **TE 10 / QB
10** keeps that convention intact. WR 25 vs WR 26 is worth 1.6 projected points of
baseline (205.2 vs 203.6) and changes no board ordering; do not spend argument on it.

The new constant, for all three files:

```python
BASELINE_RANK = {"RB": 24, "WR": 26, "TE": 10, "QB": 10, "K": ?, "DST": ?}   # § 1.5
TENTH = 10   # replaces TWELFTH = 12
```

### 1.2 What that does to the numbers, computed from the real CSV

All figures below are computed from `Data/players.csv` (243 rows with a projection, 2026-07-25
FFToday stat lines scored under this league's rules) — not estimated.

| Pos | Baseline rank 12→10 | Baseline pts 12→10 | Baseline player 12→10 | Best player's VOR 12→10 | Per week 12→10 |
|---|---|---:|---|---:|---:|
| RB | 29 → 24 | 185.3 → **201.3** (+16.0) | Jadarian Price → **Jaylen Warren** | +182.1 → **+166.1** | 10.7 → **9.8** |
| WR | 31 → 26 | 194.7 → **203.6** (+8.9) | Terry McLaurin → **Tee Higgins** | +144.6 → **+135.7** | 8.5 → **8.0** |
| TE | 12 → 10 | 156.5 → **159.5** (+3.0) | Dallas Goedert → **Jake Ferguson** | +97.3 → **+94.3** | 5.7 → **5.5** |
| QB | 12 → 10 | 291.4 → **295.3** (+3.9) | Jared Goff → **Dak Prescott** | +74.8 → **+70.9** | 4.4 → **4.2** |

Read the +16.0 / +8.9 / +3.0 / +3.9 column. That is the whole argument and it is not
uniform: **the running back baseline rises nearly twice as fast as the receiver
baseline, and five times as fast as tight end's.** Because VOR is the *distance* to that
baseline, the position whose baseline moves most is the position that loses most value.

The RB-over-WR premium at the top of the board:

- 12 teams: 182.1 − 144.6 = **37.5 points**, 2.2 a week
- 10 teams: 166.1 − 135.7 = **30.4 points**, 1.8 a week

The corpus's central positional claim — "the backs sit above the receivers" (`Who to take
at 1.01`, §"Why the backs sit above the receivers at all") — **survives, but at 81% of
its former size.** That is the honest headline and it should replace the current framing
rather than be bolted onto it.

### 1.3 The board reorders — and the top does not

Recomputing the full board with `BASELINE_RANK = {RB 24, WR 26, TE 10, QB 10, K 3, DST 3}`
and re-sorting by VOR:

**The top seven are identical, in identical order.** Gibbs, Robinson, McCaffrey, Nacua,
Chase, St. Brown, Smith-Njigba. See §2.3 — this is the single most important negative
result in the whole conversion.

**Risers** (12-team rank → 10-team rank):

| Player | Pos | 12 tm | 10 tm | Move |
|---|---|---:|---:|---:|
| Josh Allen | QB | 18 | **12** | +6 |
| Justin Jefferson | WR | 22 | **17** | +5 |
| CeeDee Lamb | WR | 27 | **23** | +4 |
| Rashee Rice | WR | 28 | **25** | +3 |
| Brock Bowers | TE | 9 | **8** | +1 |
| Trey McBride | TE | 10 | **9** | +1 |

Bowers and McBride pass Jonathan Taylor. Nothing about them changed; the RBs beneath them
fell 16 points each while they fell 3.

**Fallers** — and this is where the shallow-league argument gets its teeth:

| Player | Pos | 12 tm | 10 tm | Move |
|---|---|---:|---:|---:|
| Chuba Hubbard | RB | 79 | **105** | −26 |
| Jadarian Price | RB | 86 | **111** | −25 |
| Tony Pollard | RB | 63 | **86** | −23 |
| TreVeyon Henderson | RB | 62 | **85** | −23 |
| Rhamondre Stevenson | RB | 97 | **119** | −22 |
| David Montgomery | RB | 58 | **78** | −20 |
| Jaylen Warren | RB | 57 | **73** | −16 |

Every faller in the top 100 is a running back, and they are precisely the RB2/RB3 depth
picks the 12-team corpus sends you to rounds 5–9 to collect. In a 10-team league they are
worth roughly nothing above the wire — Jaylen Warren *is* the new baseline, by
construction VOR 0. **That is the "richer waiver wire" claim made concrete**, and it
should be written that way rather than asserted: the 10-team wire opens holding the
players a 12-team league spends its middle rounds drafting.

### 1.4 The talent pool, counted

- Players drafted league-wide: **192 → 160** (16 rounds × 10). Rewrite in
  `_PLAN.md` §1.2, `Your league, in one page` line 75, and `Concepts/Draft capital dominance`
  line 25, which currently reads "Twelve teams, sixteen roster spots each. That is **192
  players drafted**, and the set of NFL players who will produce startable fantasy weeks
  is not much larger than 192." At 160 that sentence gets *stronger*, not weaker — the
  drafted set is now clearly smaller than the startable set, which is the point.
- `BOARD_DEPTH = 130` in `build_board.py` was set against a 192-player draft. At 160 it is
  still defensible (130 < 160), but the last ~30 rows are now printing players the wire
  will hold all season. **Judgement call, flagged in §3 as needing re-reasoning, not
  mechanics.** The basketball corpus's parallel instruction is "delete ranks 131–200 from
  your board entirely; print the top 130 only" — the football analogue is to keep 130 and
  say plainly that rows ~100–130 are in-season inventory, not draft targets.

### 1.5 K and D/ST: the one baseline that is *not* a mechanical divide, and the artifact it creates

`build_board.py:29-33` is explicit that K and D/ST are exempt from the team-count
derivation:

```python
# K and D/ST are the only two positions where the waiver wire reliably offers a
# startable option every single week, so their replacement is not "the 12th best
# season-long" — it is roughly the best thing you can stream. Baselining them at 12
# ranks Houston's defence around pick 28 of the board, which is nonsense.
```

Leaving them at 3 while every other baseline rises **silently promotes kickers and
defences up the board**, because the board is a single VOR sort and everyone else got
worse. Computed:

| | K/DST baseline 3 (unchanged) | K/DST baseline 2 | Was, at 12 teams |
|---|---:|---:|---:|
| Houston Texans D/ST | board **53** | 55 | 62 |
| Brandon Aubrey (K) | board **56** | 64 | 65 |
| Cameron Dicker (K) | board **57** | 74 | 70 |
| Denver Broncos D/ST | board **60** | 72 | 76 |

A kicker at board rank 56 is the same nonsense the comment above was written to prevent —
`The last two rounds — kicker and defence` tells the reader to take these at picks
140/141/160 and reads its arithmetic straight off the board's baseline table. Moving both
to **2** restores the intent: the streamable pool is *deeper* at 10 teams (10 rostered of
20 in the file, versus 12 of 20), so the weekly running maximum you can stream is higher,
so the baseline should be a *better* player, which is a lower rank number. Per-week edge
of the best K over baseline falls 0.69 → **0.18**; best D/ST 0.98 → **0.62**. That is the
right direction and the right magnitude.

**This is re-reasoning, not arithmetic.** Rank 2 is a judgement; document it in
`_Progress.md` the way the original rank-3 choice was documented (line 61), with the
numbers above, so a future reader can see it was decided rather than defaulted.

### 1.6 The consequences that follow, each with its mechanism

Written so each can be dropped into the note that owns it, rather than as a listicle.

**Positional scarcity compresses.** The FLEX is what pushes RB and WR baselines past the
fixed slot count, and the FLEX shrinks with the league: 12 flex slots became 10, so the
RB baseline moves 5 ranks and the WR baseline 5 ranks, but from a *smaller* base. The
per-week spread between the best RB and the best QB narrows from 6.3 (10.7 − 4.4) to 5.6
(9.8 − 4.2). Owner: `Concepts/Positional scarcity as a supply constraint`,
`Draft/Value over replacement in fantasy football`.

**The waiver wire is richer, and by a countable amount.** Ranks 161–192 of the 12-team
draft are now the opening-week free-agent pool, plus every player who slid because his
positional baseline moved. From §1.3, the wire opens holding Jaylen Warren, David
Montgomery, Tony Pollard, TreVeyon Henderson, Chuba Hubbard, Rhamondre Stevenson — six
named running backs with real projected roles. Owner: `Season/Waivers`,
`Concepts/Streaming a position`.

**Streaming is more viable at every position, and the corpus's own rule says so
mechanically.** `Concepts/Streaming a position`: "a position whose replacement level is
both high and flat should be streamed rather than drafted." Every replacement level in
this league just went up (§1.2). The rule does not need rewriting — it needs its inputs
updated and one added sentence saying the set of positions that clear the bar has grown
to include the back half of tight end and quarterback.

**Bye-week management gets easier, and this one needs care.** The 2026 calendar does not
change: week 11 still has six teams off. What changes is the cost of a hole — a 10-team
wire in week 11 holds a startable body at every position, where a 12-team wire does not.
`Season/Bye-week planning` line 34 ("If five of your starters share a bye… One loss out
of fourteen, in a league where six of twelve make the playoffs") needs both its denominator
and its severity re-argued. **Blocked on Q2** — if the playoff field stays six, six of ten
is a 60% qualification rate and the whole "consistency cannot be punted" spine of `How the
league is won` weakens materially.

**Injury tolerance rises.** The basketball corpus makes this argument precisely and the
football version is cleaner because the numbers are points, not z-scores: the marginal
cost of a roster slot lost to injury is the VOR of the player you must replace him with,
and that is now 0 by construction at RB24 / WR26. This is the first real support the
corpus can offer for the McCaffrey question in `Who to take at 1.01` — but see §2.3, it
does not change the answer.

### 1.7 Consistency with how this site already reasons about league size

`fantasy/basketball/strategy/10-team-versus-12-team-fantasy-basketball-strategy.html` is
the house model. Follow its method, and *only* its method — it is a category/z-score
argument and none of the machinery transfers, but four moves do:

1. **Compute the replacement gap and name the marginal player at each boundary.** It
   names Christian Braun and Jalen Green. The football equivalents are in §1.2 —
   Jaylen Warren and Jadarian Price at RB, Tee Higgins and Terry McLaurin at WR.
2. **Show a VOR-ratio table** proving the compression is concentrated in the late rounds,
   not the early ones ("A first-round pick is worth 6% more in a 12-teamer. A round-10
   pick is worth 272% more"). The football table is §1.3's faller list; render it as a
   ratio column in the new note.
3. **Name the players who change status between formats.** Basketball has a "26 players
   ranked 131–156 are the entire population that changes status" section. Football's is
   the seven-name faller table plus board ranks 131–192.
4. **Close with two explicit instruction lists** ("If 10 teams: …"). Football has no "if"
   — the league is 10 teams — so the football note is one list, which is a simplification.

Where the football note must **diverge**: basketball concludes "in a 10-teamer, punt
tactically and late" off category machinery `_PLAN.md` §4.1 explicitly excludes from this
build. Do not import it. The football conclusion is a different one and it is in §2.5.

---

## 2. The 1.01, confirmed

### 2.1 What is actually new here

The 1.01 was **already locked** before this change — `_PLAN.md` §1.4 ("Snake, 1.01
locked, order already decided"), `Your league, in one page` line 99, and `build.py:514`
renders "Full PPR · 12 teams · ESPN · **the 1.01 is locked**" as the site masthead. The
only new fact in this conversion is the team count. Every "the slot is locked" sentence
already in the corpus is still true and does not need touching.

**What is now dead weight:** the corpus was already single-slot by design —
`_PLAN.md` line 249 says the basketball build "gives slot 1 ~3% of its words and lavishes
its best writing on slot 12," and this one gives slot 1 a dedicated note instead. There is no by-slot hedging to delete, which is unusual and
worth confirming rather than assuming (§4). The residue is smaller and specific:
`Drafting from the 1.01` line 26 ("Slot 12 also picks back to back, but waits eleven picks
for his first turn") — that comparison becomes slot 10 waiting nine picks, and it is a
sentence that could simply be cut.

### 2.2 Turn structure from 1.01 in a 10-team snake — verified

A snake reverses every round. From slot 1 in a `T`-team league, round `r` gives pick
`(r−1)·T + 1` when `r` is odd, and `r·T` when `r` is even. At `T = 10`, 16 rounds:

| Round | Notation | Pick | | Round | Notation | Pick |
|---:|---|---:|---|---:|---|---:|
| 1 | 1.01 | **1** | | 9 | 9.01 | **81** |
| 2 | 2.10 | **20** | | 10 | 10.10 | **100** |
| 3 | 3.01 | **21** | | 11 | 11.01 | **101** |
| 4 | 4.10 | **40** | | 12 | 12.10 | **120** |
| 5 | 5.01 | **41** | | 13 | 13.01 | **121** |
| 6 | 6.10 | **60** | | 14 | 14.10 | **140** |
| 7 | 7.01 | **61** | | 15 | 15.01 | **141** |
| 8 | 8.10 | **80** | | 16 | 16.10 | **160** |

```python
PICKS = [1, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101, 120, 121, 140, 141, 160]
```

Check: 16 × 10 = 160 = the last pick. The structure the corpus leans on is preserved
exactly — **one pick at the top, then every remaining turn is two picks back to back.**

The blind window: after pick 1 the next is pick 20, so picks 2–19 pass, an **18-pick blind
window**, down from 22. Every "22-pick blind window" in the vault becomes 18 — it appears
in `_PLAN.md` (lines 120, 254), `Your league, in one page` (109), `Fantasy football
glossary` (76), and `Sources/ADP, rankings, and projections are three different things`
(58).

The three end-of-draft picks that `The last two rounds — kicker and defence` keys to
(168, 169, 192 — kicker, defence, IR stash) become **140, 141, 160**. Note this changes the
note's title logic: 140/141 is the round-14/15 turn and 160 is the final pick, exactly
parallel to before.

Round labels in `Drafting from the 1.01`'s round-by-round section: `2.12/3.01` → **2.10/3.01**,
`4.12/5.01` → **4.10/5.01**, `6.12/7.01` → **6.10/7.01**, `8.12/9.01` → **8.10/9.01**.

### 2.3 Who to take at 1.01 — the answer does not change, and that is the finding

Recomputing the board on 10-team baselines leaves the top seven in the same order (§1.3).
The corpus's tiebreaker chain in `Who to take at 1.01` runs on full-PPR receiving volume,
the two-stage payout, bye week, and observed availability — **none of which is a function
of league size**, except criterion 2, which is blocked on Q2/Q3.

So: **Bijan Robinson, on the same reasoning, with the same caveats, and the note's own
expiry warning still governs** ("If it is draft night and this has not been rewritten
since 2026-07-25, do not use it").

Two things inside the note do change and must not be missed:

- The per-week replacement figures quoted in "Why the backs sit above the receivers at
  all" — "RB 10.7 · WR 8.5 · TE 5.7 · QB 4.4" — become **RB 9.8 · WR 8.0 · TE 5.5 · QB
  4.2**, and "the 29th back and the 31st receiver but only the 12th tight end and 12th
  quarterback" becomes **the 24th back and the 26th receiver, and the 10th tight end and
  10th quarterback**.
- The second column of the board's baseline table, "per week vs the 12th-best at the
  position," is a *different* comparison that also moves — `TWELFTH = 12` → `TENTH = 10`,
  and the prose "For tight end and quarterback the two columns are the same number,
  because only twelve of each get started" becomes ten, and stays true.

One genuinely new argument is now available and should be added: §1.6's injury-tolerance
mechanism makes McCaffrey's 14-of-51 missed games *cheaper* than the 12-team note prices
them, because the roster slot he vacates now costs VOR ≈ 0 to fill. **It does not move
him back into the conversation** — criterion 1 (receiving volume) and criterion 4
(availability) both still point at Robinson, and Adj VOR still drops McCaffrey to 7th.
State the argument and state that it loses, rather than omitting it.

### 2.4 The gap from 1.01 to 2.10, and what it buys

Eighteen picks instead of twenty-two. The consequence the corpus draws from the gap is
unchanged in kind — "take the player whose value depends least on what happens next" —
but the second turn arrives **four players earlier in the draft**, and against a common
ADP ordering that is a strict superset of the board you would have seen at 24/25.

Four names that the 12-team script treats as gone-or-lucky at 24/25 are now the *expected*
board at 20/21:

| Player | Pos | ADP | 12-team status at pick 24 | 10-team status at pick 20 |
|---|---|---:|---|---|
| Chris Olave | WR | 22.1 | "if he has fallen past his ADP" | on the board |
| Kenneth Walker | RB | 22.2 | gone | on the board |
| Jeremiyah Love | RB | 22.4 | gone | on the board |
| Nico Collins | WR | 23.6 | "if he has fallen past his ADP" | on the board |

**The elite tight end and elite quarterback lockout gets stronger, not weaker — and this
is the counterintuitive result the plan exists to catch.** `Drafting from the 1.01` §"Two
things this slot cannot buy" rests on McBride at ADP 28.9 and Bowers at 35.8 sitting
"*just past* your 24/25 turn," and Josh Allen at 28.1 likewise. At 20/21 they are 8, 15
and 7 picks past instead of 4, 11 and 3. The knife edge the note's own Open Questions flag
as fragile ("a small ADP shift by late August flips 'structurally locked out' into
'available'") **tips away from availability.**

At the same time §1.3 shows all three gained board value — Bowers 9→8, McBride 10→9, Allen
18→12. So the note's structure survives but its argument inverts in shape: *you want them
more and can reach them less.* The corpus's own resolution — the per-week comparison —
narrows: TE 5.5 vs RB 9.8 at 10 teams, against TE 5.7 vs RB 10.7 at 12. A gap of 4.3
points a week, down from 5.0. **The "never a tight end at this turn" rule holds, by a
smaller margin, and the note must say so rather than repeat the old margin.**

One methodological caveat that must be written into the note and not buried: **every ADP
figure in this corpus is 12-team ADP.** `players.csv` column `adp_source` reads
`ffcalc-ppr-12tm-2026-07-25`. Raw ADP is a count of players taken, so it is roughly
comparable across league sizes for the *order* of the pool, but positions with fixed
one-per-team demand (QB, TE, K, D/ST) need two fewer bodies at 10 teams and will slide
slightly later than a 12-team ADP predicts. That direction *helps* McBride/Bowers/Allen
availability at 20/21 and partially offsets the paragraph above. **It is unmeasured, and
guessing at it is exactly what `_PLAN.md` §7 forbids** — re-fetch Fantasy Football
Calculator's 10-team PPR ADP and re-run. See §3 item 6.

### 2.5 What the 1.01 + 2.10/3.01 pairing should target

The pairing logic in `Drafting from the 1.01` — pair by position, pair safe with swing,
pair by bye week — is a property of the back-to-back turn and survives untouched.

What changes is the recommendation inside it. The 12-team note's headline is
"**2.12/3.01 is the best place in this draft to take two top-twelve receivers back to
back**," argued from tier depth: "running back tier three holds four players, while seven
of the fourteen in receiver tier two still have an ADP past pick 25. Four against seven."
Those counts come out of `Tiers by position`, which is regenerated by `build_board.py` off
the new baselines — **the tier boundaries will move, so this sentence must be re-derived
from the regenerated file, not adjusted by hand.** It is the one place in the note where
the argument is downstream of a generated artifact.

The direction the numbers point, before that regeneration:

- **The RB2 tier is worth materially less** (§1.3: every top-100 faller is a running
  back). A second bell cow at 20/21 buys less than it did.
- **The WR pool at 20/21 is deeper than the 12-team pool at 24/25** (§2.4 adds Olave and
  Collins to Rice, Wilson, Flowers, Smith).
- Both push the same way. **Pairing A — two alpha receivers — gets stronger, and it was
  already the default.**

So the script at 1 / 20 / 21 is: **Robinson at 1.01, then two receivers at 2.10/3.01**,
drawing from Rice (26.9), Wilson (28.3), Olave (22.1), Collins (23.6), Flowers (26.5),
Smith (28.0) — six names for two slots, against the 12-team note's four. The bye clash the
note flags (Wilson and Flowers both bye 13) still stands.

And the standing rules for that turn survive verbatim: no tight end, no quarterback.

---

## 3. Edit list, in order

Ordered so that nothing downstream is built against a stale input. **G** = generator,
**D** = data, **P** = prose, **O** = generated output (never hand-edit).

| # | File | Kind | Change | Type |
|---:|---|---|---|---|
| 1 | `Rome/…/Fantasy Football/_PLAN.md` | P | §1.2 lines 85–87 (slot table, effective starters, 192→160); §1.4 money and playoffs (**blocked on Q2/Q3**); §1.5 pick sequence; line 120 "22-pick"; line 46 format key; lines 14, 33, 110, 162, 166, 238, 254 | **re-reason** |
| 2 | `Rome/…/Data/build_board.py` | G | L23 `FORMAT`; L28 `BASELINE_RANK`; L34 `TWELFTH = 12` → `TENTH = 10` (and its comment); L36 `PICKS`; L37 `BOARD_DEPTH` (see §1.4); the prose strings at L180 (ADP source label), L271–290 (baseline table header + the two explanatory paragraphs) | **mixed** — constants mechanical, the L271–290 prose needs rewriting |
| 3 | `Rome/…/Data/simulate_season.py` | G | L36 `TEAMS = 12` → 10; L39 `PLAYOFF_TEAMS` (**blocked on Q3**); L38 `PAYOUT` (**blocked on Q2**); L118 `BASE_RANK` (duplicate of #2, must match); L280 `window = cands[:12]`; L434 format key; docstring L8/L15 and the prose at L232, L273, L456 | **re-reason** |
| 4 | `fantasy/football/build.py` | G | L73 `PICKS`; L220 `BASE_RANK` (third copy — must match #2 and #3); L514 masthead `"Full PPR · 12 teams · ESPN · the 1.01 is locked"` | mechanical |
| 5 | `Rome/…/Data/players.csv` | D | `adp_source` column: every row reads `ffcalc-ppr-12tm-2026-07-25` | data re-fetch — see #6 |
| 6 | `Rome/…/Data/raw/ffcalc-ppr-adp-2026-07-25.txt` | D | Re-fetch Fantasy Football Calculator **10-team** PPR ADP, re-derive the `adp` column. Until this lands, every ADP-dependent claim in §2.4/§2.5 carries a stated caveat | **re-reason** |
| 7 | *run* `python3 build_board.py` | O | Regenerates `Draft/2026 draft board.md` + `Draft/Tiers by position.md`. **Do not hand-edit either.** | mechanical |
| 8 | *run* `python3 simulate_season.py` | O | Regenerates `Draft/When to start drafting for upside.md` | mechanical |
| 9 | `Rome/…/Start Here/Your league, in one page.md` | P | The reference card. L10 format key; L61–75 roster block + "192 players drafted"; L90–103 money table (buy-in, prizes, pool, **Teams 12 → 10**, playoffs); L105–109 the 16 picks + "22-pick blind window"; L96 "4th–12th nothing" | **re-reason** — highest-stakes page in the corpus, it is the draft-day card |
| 10 | `Rome/…/Start Here/How the league is won.md` | P | L13 "three teams out of twelve"; L30 "Nine of twelve teams lose the identical $75"; L44 "finish top 6 of 12"; L46 "six-team bracket". The convex-payout spine is **blocked on Q2/Q3** — if the field is 6 of 10 the qualification rate goes 50%→60% and "do not sacrifice the mean in rounds 1 through 4" needs re-argument | **re-reason** |
| 11 | `Rome/…/Draft/Drafting from the 1.01.md` | P | The most important note. Pick sequence (L22); L26 slot-12 comparison (cut); the round labels 2.12/4.12/6.12/8.12; L54 the 2.12/3.01 paragraph and its tier counts (re-derive from #7); "Two things this slot cannot buy" (§2.4 — the argument inverts); the full script at L70–84; L90 "twelve human drafters"; ADP caveat at L18 | **re-reason** |
| 12 | `Rome/…/Draft/Who to take at 1.01.md` | P | L67 "top 6 of 12" (blocked on Q3); L69 the pick sequence; L112 the per-week figures and the 29th/31st/12th/12th sentence; add the injury-tolerance argument from §2.3 and state that it loses | **re-reason** |
| 13 | `Rome/…/Draft/Value over replacement in fantasy football.md` | P | L34 "Twelve teams times one quarterback slot"; L42–53 the per-week table and the 12th-best column; L61 the 12th quarterback; L67 the D/ST figure; L75 the K/D-ST-at-rank-3 paragraph (**§1.5**); L93–100 the fixed-slots/FLEX-share table | **re-reason** — this is the note the whole quantitative layer hangs off |
| 14 | `Rome/…/Concepts/Replacement level.md` | P | L31 is the plainest statement of the mechanism in the corpus and every number in it is 12: "Twelve teams each starting one tight end… twelve teams × two running back slots means twenty-four running backs are spoken for, and the twenty-fifth is where free begins" → ten / twenty / twenty-first | mechanical |
| 15 | `Rome/…/Concepts/Draft capital dominance.md` | P | L25 "Twelve teams, sixteen roster spots each. That is 192 players drafted" → ten / 160, and the following clause gets stronger (§1.4) | **re-reason** (one paragraph) |
| 16 | `Rome/…/Concepts/Positional scarcity as a supply constraint.md` | P | Baselines and the FLEX arithmetic | mechanical |
| 17 | `Rome/…/Concepts/Streaming a position.md` | P | "roughly the twelfth-best season-long option" → tenth; add the one sentence from §1.6 on the widened streamable set | mechanical + one addition |
| 18 | `Rome/…/Concepts/Sample size in a 17-game season.md` | P | L21 "finishing top six of twelve" (blocked on Q3) | mechanical |
| 19 | `Rome/…/Season/Waivers.md` | P | L35 "If you are in first place, you claim twelfth every week" → tenth; L41 "the team in twelfth"; add the §1.6 supply count — this is where the richer-wire claim belongs, with names | **re-reason** (the supply section) |
| 20 | `Rome/…/Season/Bye-week planning.md` | P | L34 denominator, and the severity re-argument from §1.6 | **re-reason** |
| 21 | `Rome/…/Season/Start-sit — a standing rule….md` | P | L59 "Six of twelve teams make the playoffs" | mechanical (blocked on Q3) |
| 22 | `Rome/…/Season/Weather and the fantasy playoffs.md` | P | L25 "Nine of twelve teams… the $900" — both numbers (blocked on Q2) | mechanical (blocked) |
| 23 | `Rome/…/Start Here/The 2026 season calendar.md` | P | L24 "14 matchups against 11 distinct opponents… top 6 of 12" → 9 distinct opponents; L25 the bracket size | mechanical (blocked on Q3) |
| 24 | `Rome/…/Start Here/The four players you already know.md` | P | L22 ADP provenance; L34 "across twelve teams roughly 29 running backs start each week… 10.7 points a week"; L42 "the twelfth sits at 156.5… the last tight end a 12-team league starts… 94 points, or 5.6 a week"; L70 "top six" | **re-reason** — all four are quantitative and all four move |
| 25 | `Rome/…/Start Here/Reading an NFL depth chart.md` | P | L54 "Top-12 quarterback league-wide"; L62 "blocks of twelve"; L64 "about 31 receivers are genuinely startable weekly" → 26. L62's "blocks of twelve" is an *industry convention*, not this league — keep it and sharpen the contrast in L64 | **re-reason** (one line) |
| 26 | `Rome/…/Start Here/Fantasy football glossary.md` | P | L76 "the turn": pick sequence and "22-pick blind window" | mechanical |
| 27 | `Rome/…/Draft/How much to spend on running backs.md` | P | L24 ADP provenance; L74 "fourth pays exactly what twelfth pays"; the "**13 of the first 24 picks are running backs**" finding → at 10 teams the relevant window is the first 20 picks, where it is **11 of 20** (and 5 of 10 through the first round). The dead-zone argument gets *stronger* — §1.3's fallers are exactly the dead zone | **re-reason** |
| 28 | `Rome/…/Draft/The last two rounds — kicker and defence.md` | P | L26 "168, 169 and 192" → 140, 141, 160; L74/L80/L91 "pick 192" → 160; L24 reads its arithmetic off the board's baseline table, which moves (§1.5) | **re-reason** (the arithmetic paragraph) |
| 29 | `Rome/…/Draft/Late-round quarterback.md` | P | The QB baseline moves 12→10 and Josh Allen rises 6 board slots (§1.3). The note's central claim — wait on QB — survives but its margin narrows; the turn numbers in its pick rule change | **re-reason** |
| 30 | `Rome/…/Draft/Reading the draft room.md` | P | Run-detection heuristics are keyed to a 12-team room and a 22-pick window | **re-reason** |
| 31 | `Rome/…/Sources/*.md` (3 files) | P | `ADP, rankings, and projections…` L44/L46/L58 (12-team ADP provenance + the 22-pick window); `What I checked and when` L29 (the ADP row); `Where fantasy football information comes from` L21/L66 ("12-team home league" ×2) | mechanical, **except** L46 which claims "the format matches on the two things that move ADP most — full PPR scoring and **12 teams**" — that sentence becomes false and must be rewritten or the ADP re-fetched (#6) |
| 32 | **All 109 vault `.md` frontmatter** | P | `format: espn-ppr1.0-12tm-std` → `espn-ppr1.0-10tm-std`. This key exists precisely for this: `_PLAN.md` §1 — "Stamp it into the frontmatter of every derived note so a later correction has a **greppable blast radius**." 109 of 109 files carry it; `build.py` renders it as a visible badge on **108 of 118 pages**. One `sed`, and it is also the verification that the conversion was complete | mechanical |
| 33 | `Rome/…/_Progress.md` | P | Record the conversion: the new baselines with §1.2's numbers, the K/D-ST rank-2 decision with §1.5's table, and the ADP-provenance gap. The corpus's own convention (L61, L109) is that baseline choices are documented rather than defaulted | **re-reason** |
| 34 | **New note** — `Rome/…/Concepts/League size and replacement level.md` | P | The football analogue of the basketball 10-vs-12 note. Contents: §1.1 derivation, §1.2 baseline table, §1.3 riser/faller table with a ratio column, §1.6's five mechanisms. It is the note every other edit can link to instead of re-arguing. Follow the basketball note's *method* (§1.7), not its category machinery | **new writing** |
| 35 | *run* `build.py` then `scripts/inject_hub.py` | O | Regenerates 118 pages. `inject_hub.py` is required — `build.py` strips the site hub tag on every rebuild (README) | mechanical |
| 36 | *verify* | — | `grep -rn "12tm\|12-team\|twelve teams\|22-pick\|\b192\b\|2\.12\|top six of twelve\|of twelve" ` over both the vault and `/fantasy/football/*.html` returns only the intended survivors (e.g. `Player archetypes`' "twelve labels", Mike Evans' "twelve seasons in"). Then re-run the merge agent's link checker | mechanical |

**Nothing in `/fantasy/football/*.html` is on this list except `build.py`.** All 118 pages
are outputs of steps 7, 8 and 35.

---

## 4. What can be deleted outright

Short list, deliberately. The corpus is small (`_PLAN.md` §0: "Target ~55 notes") and was
built single-slot from the start, so there is far less 12-team-only content than a
conversion usually turns up.

1. **`Drafting from the 1.01` line 26** — "Nobody else in this league has that as
   strongly. Slot 12 also picks back to back, but waits eleven picks for his first turn
   and never gets the best player on the board." Cut rather than convert. It is a
   consolation aside about a slot the reader does not have, it was the only by-slot hedge
   in the corpus, and with the count confirmed at 10 it is pure noise.

2. **`Drafting from the 1.01` line 90** — "The script assumes twelve human drafters
   behaving roughly like the market." Either delete or fold into the ADP caveat; as a
   standalone Open Question it is stale the moment the count changes.

3. **Any ADP figure not re-fetched under edit #6.** Not a content deletion but a
   *provenance* one: if the 10-team ADP pull does not happen, every ADP number in the
   corpus must be relabelled as 12-team-sourced rather than silently reused. The corpus's
   own standard (`_PLAN.md` §0 rule 8: "never present a modeled number as an observed
   one") makes silent reuse the worst available option.

**Explicitly not deletable, despite matching the greps:**

- `Player archetypes` — "the twelve labels every player reference resolves to." Twelve
  archetypes, unrelated to team count. Appears in `_PLAN.md`, `Fantasy Football.md`,
  `build.py:529` and the README.
- `Reading an NFL depth chart` L62 — "WR2 / WR3… blocks of twelve, a convention inherited
  from ranking lists." That is a *description of the industry's* convention and stays; only
  the following line's contrast with this league's 31→26 changes.
- Player-page prose: "twelve seasons in" (Mike Evans), "top-12 quarterback" as an industry
  tier label. Roughly a dozen such false positives — check each rather than sed blindly.

---

## 5. Open questions — the ones the corpus genuinely cannot answer

Determined from the corpus and **not** asked below: scoring format, roster slots, PPR,
acquisition system. All four are confirmed and sourced. See §6.

**Q0 — Is this the same league with two fewer teams, or a different league?**
Everything else depends on this. `Your league, in one page` line 17 says "All values
verified from the ESPN settings screens on **2026-07-25**." If two managers dropped out of
*that* league, only the team count, the pick map, the pool and the playoff field change,
and §6's confirmed settings all hold. If this is a **new** 10-team league, then nothing in
§6 is confirmed any more — it is a different ESPN instance with its own settings screens —
and the entire conversion is blocked until they are read off. *Answer this first.*

**Q1 — Is the 1.01 in the 10-team league the same locked slot, or a new draw?**
The task states the #1 pick is confirmed, so the answer is presumably "yes, confirmed" —
but the corpus's existing claim is "1.01 locked, **order already decided**" (`_PLAN.md`
§1.4), which is a claim about the *whole* draft order, not just slot 1. If the order was
redrawn, that sentence needs weakening even though the outcome for slot 1 is the same.

**Q2 — Money. The current structure does not survive the arithmetic.**
`_PLAN.md` §1.4: "$100 buy-in = $75 to the prize pool + $25 refundable deposit. Prizes 1st
$500 · 2nd $250 · 3rd $150. Pool = 12 × $75 = $900, and 500 + 250 + 150 = 900 — it
balances exactly, so EV at random is precisely zero."

At 10 teams the pool is **10 × $75 = $750** against **$900** of prizes. It does not
balance and one of three things must have changed: the buy-in, the prize schedule, or the
number of paid places. This is not cosmetic — the convex payout is the argued spine of
`How the league is won`, `Convex payoffs and roster variance`, `When to start drafting for
upside` (and `simulate_season.py:38`'s `PAYOUT` dict, which is stated net of stake:
`{1: 425.0, 2: 175.0, 3: 75.0}`). **The buy-in, the three prize amounts, and how many
places pay.**

**Q3 — Playoff field size.** Currently six of twelve (50%). At 10 teams, six of ten is
60% and four of ten is 40%. The corpus argues "do not sacrifice the mean in rounds 1
through 4" *because* qualification is a coin flip; at 60% that argument weakens and at 40%
it strengthens. `simulate_season.py:39` `PLAYOFF_TEAMS = 6` is a live input to a generated
note. **How many teams make the playoffs, and are the playoff weeks still 15–17?**

**Q4 — Regular-season length.** Currently weeks 1–14, 14 matchups against 11 distinct
opponents. Ten teams gives 9 distinct opponents, so a 14-week schedule now means five
repeat matchups (or the league runs 13 weeks with a 4-week playoff). This changes
`The 2026 season calendar` and `simulate_season.py:37` `REG_WEEKS = 14`. **Is the fantasy
regular season still weeks 1–14?**

**Q5 — Roster size, re-confirmed rather than assumed.** 16 spots + IR is confirmed for the
12-team league. It is the single most likely setting to have been changed alongside team
count, and it is the direct input to §1.1's derivation — a change from 7 bench to 6 moves
nothing, but a change to the *starter* line (a second FLEX, a superflex) moves every
baseline in this plan. **Confirm the starters row is still 1QB/2RB/2WR/1TE/1FLEX/1D-ST/1K.**

**Q6 — Keeper rules.** `_PLAN.md` §4.1 lists "Dynasty, keeper, best-ball, auction,
superflex, IDP" as out of scope *for the build*, and `How much to spend on running backs`
line 94 calls it "a managed redraft league" in passing. Nothing in the corpus *reads a
keeper setting off ESPN* the way it does scoring and roster — this is the one league
setting that is inferred rather than observed. If the 10-team league has keepers, the
1.01's value changes completely (a keeper league's first pick is worth less, because the
best players are already gone). **Are there keepers?** — the only item on this list the
corpus is silent on rather than merely out of date.

---

## 6. Settings determined from the corpus — do not re-ask, but do re-verify per Q0

Every line below is read off `Start Here/Your league, in one page.md`, which states at
line 17: "All values verified from the ESPN settings screens on **2026-07-25**," and is
corroborated by `_PLAN.md` §1.1–§1.3.

| Setting | Value | Source |
|---|---|---|
| Platform | ESPN | `Your league…` frontmatter, `_PLAN.md` §1 |
| Scoring | **Full PPR, fractional** — 1.0 per reception, 0.1/yd rush+rec, 0.04/yd pass, TD rush/rec 6, TD pass 4, INT −2, fumble lost −2 | `Your league…` §Scoring |
| Kicking | PAT 1 · FG 0–39 3 · 40–49 4 · 50–59 5 · 60+ 6 · **any FG missed −1** | `Your league…` §Scoring |
| D/ST | Def/return TD 6 · safety 4 · 1pt safety 1 · 0 allowed +5 · 46+ allowed −5 · yards-allowed brackets active (<100 +5 … 550+ −7) | `Your league…` §Defence |
| Starters | **1 QB · 2 RB · 2 WR · 1 TE · 1 FLEX (RB/WR/TE) · 1 D/ST · 1 K** = 9 | `Your league…` §Roster, `_PLAN.md` §1.2 |
| Bench / IR | **7 bench + 1 IR** (IR does not consume a bench spot); roster 16 | same |
| Not present | No superflex, no OP slot, no IDP | same |
| Acquisition | **Waivers, not FAAB.** 1-day period. **Order resets weekly to inverse standings.** No season acquisition limit | `Your league…` §Acquisition, `_PLAN.md` §1.3 |
| Lineup lock | Per-player, at each player's own kickoff | same |
| Draft type | **Snake** | `_PLAN.md` §1.4 |
| Draft slot | **1.01, locked** | `_PLAN.md` §1.4; `Your league…` L99; rendered in the site masthead, `build.py:514` |
| Season opens | Wednesday 9 September 2026 | `Your league…` §Money and format |
| Draft date | **Late August 2026, exact date TBC** — the corpus's own only unconfirmed item | `Your league…` L103, `_PLAN.md` §10.1 |

Two flags the corpus raises about its own data, which the conversion must carry forward:

- **The intermediate points-allowed brackets and the D/ST sack / INT / fumble-recovery
  values were never recorded.** `Your league…` line 59 and 120 both say so. Still a gap.
- **`Who to take at 1.01` expires 2026-08-15** and carries a `[!danger]` callout ordering a
  rewrite in the 72 hours before the draft. Today is 2026-07-31. The conversion does not
  discharge that obligation — it is a separate, later job.

---

## 7. Verification, before calling it done

1. All three copies of the baseline dict agree: `build_board.py:28`,
   `simulate_season.py:118`, `fantasy/football/build.py:220`.
2. All three copies of `PICKS` agree: `build_board.py:36`, `fantasy/football/build.py:73`,
   and the prose in `Your league, in one page` / `Drafting from the 1.01` / `_PLAN.md` §1.5.
3. `build_board.py`'s own assertions still pass — L610 `assert pool[rank-1]["vor"] == 0.0`
   and L612–615's tier-integrity checks. They are the build's fail-closed contract.
4. The board's "Replacement baselines used" table names Jaylen Warren (RB), Tee Higgins
   (WR), Jake Ferguson (TE), Dak Prescott (QB) as the baseline players. If it does not,
   the constant did not take.
5. `grep -rc "12tm" fantasy/football/*.html` returns 0 across all 118 pages.
6. Re-run the link checker from the merge (`scratchpad/linkcheck.py`) — edit #34 adds a
   note and edits #1/#11 change wikilinks, both of which can strand a link.
7. The site masthead reads "Full PPR · 10 teams · ESPN · the 1.01 is locked".
