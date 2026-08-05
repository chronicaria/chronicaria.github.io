# PLAN — refresh the Fantasy Football Encyclopedia and convert it from 12 teams to 10

Written 2026-07-31; expanded 2026-08-02 into the research-and-execution plan. Not a
corpus page. This file sits at the corpus root next to
`README.md`; `build.py` reads only the Obsidian vault and never scans this directory, so
nothing here is published. Do not move it into the vault — `build.py` skips exactly one
filename (`_PLAN.md`, line 130) and any other `_PLAN-*.md` would render into
`meta/` on the next build.

---

## Execution contract — read this before using any player name below

This is a **fresh-research campaign followed by a 10-team rebuild**, not a prose-only
conversion. The current board is a July 23–25 snapshot: FFToday projections are dated
2026-07-23, every populated ADP row is a 2026-07-25 Fantasy Football Calculator
**12-team** proxy,
and `player_context.csv` is an nflverse/contract snapshot dated 2026-07-25. The camp
reporting window straddled that snapshot, and material camp developments continued
after it. Those bytes remain useful as a control, but they are not the final input to a
draft decision.

The two facts supplied by Andrew are locked:

- the league now has **10 teams**;
- Andrew still drafts at **1.01** in a snake.

Everything else that can move — projections, roster membership, camp roles, injuries,
PUP/NFI status, contracts, ADP, tiers, and the names available at each turn — must be
researched again. Accordingly:

1. **All available subagent slots stay occupied whenever the campaign is running.** The
   controller maintains more ready, non-overlapping work than the platform can execute,
   immediately replaces a completed worker, and bursts to the platform concurrency cap.
2. **Research agents produce evidence receipts, not competing edits.** Shared CSVs,
   model code, and generated output each have one writer. This is how the campaign can
   use maximal research concurrency without corrupting the build.
3. **A fresh, versioned research freeze precedes every numerical rewrite.** No July
   player name, rank, baseline player, 1.01 recommendation, or 20/21 target in §§1–2 is
   authoritative until it survives the refresh in §§8–16.
4. **The July calculations are regression fixtures.** They show what league-size alone
   did to the old snapshot and give the new run something concrete to explain. They are
   not expected outputs after the player and market data change.
5. **Dynamic events reopen only their dependency cone.** An injury or depth-chart change
   dispatches a focused impact cell and invalidates affected projections, ranks, tiers,
   turn plans, and pages; it does not require 100 agents to reread unrelated facts.
6. **Missing or conflicting evidence remains missing or conflicted.** It never becomes
   a silent default, a majority vote over syndicated reports, or an invented consensus.

Sections 0–6 preserve the already-computed conversion analysis and edit inventory.
Sections 8–16 govern execution and supersede any player-specific conclusion in those
earlier sections when fresh evidence disagrees. Section 7 is the final release gate.

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
        │                         → writes Draft/Availability and injury risk.md
        ├── Data/simulate_season.py → writes Draft/When to start drafting for upside.md
        │
        └── PersonalSite/fantasy/football/build.py
                 ├── re-implements the board arithmetic (build.py:220) for draft-room.html
                 ├── copies both CSVs to fantasy/football/data/
                 └── renders all 109 notes → 118 HTML pages
```

Three files independently hard-code the replacement baselines. Two of them
(`Data/build_board.py` and `football/build.py`) also hard-code the pick array;
`Data/simulate_season.py` derives snake order from `TEAMS` and `ROUNDS`. **All coupled
inputs must be changed together or the site will contradict itself**, which is the exact
failure `build_board.py`'s docstring says it exists to prevent ("so the interactive table
and the markdown note can never disagree").

Rebuild sequence after any edit, from the corpus root:

```bash
cd "/Users/andrewpark/Desktop/Rome/Sports/NFL/Fantasy Football/Data"
python3 build_board.py           # regenerates board, tiers, and availability notes
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

### 1.2 What that did to the July 25 numbers, computed from the frozen CSV

All figures below are computed from `Data/players.csv` (243 rows with a projection, 2026-07-25
FFToday stat lines scored under this league's rules) — not estimated.

This table isolates the effect of league size on the old input snapshot. The refresh may
change every named baseline player and point total; the mechanism and the requirement to
recompute do not change.

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

### 2.3 What the July 25 snapshot said at 1.01 — a hypothesis the refresh must retest

Recomputing the board on 10-team baselines leaves the top seven in the same order (§1.3).
The corpus's tiebreaker chain in `Who to take at 1.01` runs on full-PPR receiving volume,
the two-stage payout, bye week, and observed availability — **none of which is a function
of league size**, except criterion 2, which is blocked on Q2/Q3.

The frozen-snapshot result was **Bijan Robinson**, on the same reasoning and with the
note's own expiry warning governing: "If it is draft night and this has not been
rewritten since 2026-07-25, do not use it." This is the control hypothesis for the new
1.01 agents, not permission to publish Robinson after a mechanical league-size edit.

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

### 2.4 The gap from 1.01 to 2.10, and what the July market suggested it bought

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

### 2.5 The July hypothesis for the 1.01 + 2.10/3.01 pairing

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

So the historical script to challenge at 1 / 20 / 21 is: **Robinson at 1.01, then two
receivers at 2.10/3.01**,
drawing from Rice (26.9), Wilson (28.3), Olave (22.1), Collins (23.6), Flowers (26.5),
Smith (28.0) — six names for two slots, against the 12-team note's four. The bye clash the
note flags (Wilson and Flowers both bye 13) still stands.

The old run also said no tight end and no quarterback at that turn. Those rules survive
only if the fresh 10-team ADP, tiers, and opportunity-cost calculation reproduce them.

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
| 5 | `Rome/…/Data/players.csv` | D | All 149 populated ADP rows read `ffcalc-ppr-12tm-2026-07-25`; 94 rows have no ADP/source, and one of 150 raw captured records did not join. Re-fetch and emit an explicit coverage/unjoined report | data re-fetch — see #6 |
| 6 | `Rome/…/Data/raw/ffcalc-ppr-adp-2026-07-25.txt` | D | Re-fetch Fantasy Football Calculator **10-team** PPR ADP, re-derive the `adp` column. Until this lands, every ADP-dependent claim in §2.4/§2.5 carries a stated caveat | **re-reason** |
| 7 | *run* `python3 build_board.py` | O | Regenerates `Draft/2026 draft board.md`, `Draft/Tiers by position.md`, and `Draft/Availability and injury risk.md`. **Do not hand-edit them.** | mechanical |
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
| 32 | **All 108 current-format vault-note frontmatter records** | P | `format: espn-ppr1.0-12tm-std` → `espn-ppr1.0-10tm-std`. This key exists precisely for this: `_PLAN.md` §1 — "Stamp it into the frontmatter of every derived note so a later correction has a **greppable blast radius**." 108 of 109 vault notes carry it; the skipped internal `_PLAN.md` does not. `build.py` renders the field as a visible badge on **108 of 118 pages**. Apply mechanically and verify the exact count | mechanical |
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
  rewrite in the 72 hours before the draft. The 2026-08-02 expansion of this plan does
  not discharge that obligation; §§8–16 make that refresh part of this campaign.

---

## 7. Verification, before calling it done

Completion requires evidence at every layer, in this order:

1. **Research freeze.** Every imported projection, ADP sample, roster fact, injury
   status, and role claim has a receipt, a source/access timestamp, a freshness state,
   and a resolved or explicitly conflicted disposition. The run manifest names the
   exact input snapshots and hashes. No required parent input is expired.
2. **League contract.** The 10-team count and locked 1.01 are recorded. The settings gate
   has re-verified starter slots, bench/IR, scoring, draft rounds, keepers, playoffs,
   season length, payout, waivers, and the exact draft date. Any unresolved setting is
   attached to the outputs it blocks rather than guessed.
3. **Data contracts.** Player keys are unique; teams, positions, byes, and numeric fields
   are valid; the projection pool and context join are reported; every missing context
   row is visible; populated/missing/unjoined ADP coverage is reported; no blank was
   silently turned into zero or an average. Derived CSVs inherit the oldest parent
   timestamp.
4. **Model identity.** All three copies of the baseline dictionary agree:
   Data/build_board.py, Data/simulate_season.py, and fantasy/football/build.py. The two
   executable copies of the snake pick array and every published prose copy agree.
5. **10-team arithmetic.** With the confirmed one-FLEX lineup, the model uses RB24,
   WR26, TE10, and QB10; the K/DST decision is documented. Every position's current
   baseline row has VOR exactly zero. The board and Draft Room reproduce the same ranks,
   VOR, adjusted VOR, and tiers from the same frozen inputs.
6. **Snake identity.** The 16-round pick sequence is
   1, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101, 120, 121, 140, 141, 160; the last pick is
   16 × 10; the blind window is 18 picks; the rendered round labels are 2.10/3.01,
   4.10/5.01, and so on.
7. **Fresh strategy.** The 1.01 decision and every turn queue were recomputed after the
   final projection, health, role, and 10-team ADP freeze. The July Robinson/WR/WR result
   is allowed to survive only if the new evidence independently reproduces it.
8. **Semantic residue sweep.** Search the vault and rendered site recursively for 12tm,
   12-team, twelve teams, 22-pick, 192, 2.12, top six of twelve, and equivalent prose.
   Each surviving match is classified as current-setting defect, historical/source
   provenance, industry convention, or unrelated language such as twelve archetypes.
   A blind global replacement is a failure.
9. **Structural validation.** Data/build_board.py and Data/simulate_season.py checks
   pass; Data/check_links.py passes; a new deterministic local-site validator crawls all
   rendered HTML, local assets, CSV links, player links, and search-index URLs. The old
   plan named scratchpad/linkcheck.py, but that file is absent and cannot count as
   evidence. From the vault root, the existing checks are:

       python3 Data/build_board.py --check
       python3 Data/simulate_season.py --check
       python3 Data/check_links.py --json
10. **Browser QA.** Serve the repository root and check desktop plus narrow layouts for
    the fantasy landing page, football home, Draft Room, both 1.01 notes, the reference
    card, representative early/middle/late player pages, the 32-offenses table, source
    ledger, search, filters, every numeric sort, nav, theme, downloads, and the hub band.
11. **Fresh render.** The masthead reads "Full PPR · 10 teams · ESPN · the 1.01 is
    locked"; every current-format note carries espn-ppr1.0-10tm-std; the global as-of
    date equals the frozen research run; no page claims to be fresher than its oldest
    dependency.
12. **Final diff.** One integrator reviews the vault diff and generated diff for scope,
    expected orphan deletion, unexplained rank moves, and accidental loss of citations
    before publish.

---

## 8. The control plane — maximal useful concurrency is the default

The campaign runs a durable dispatcher rather than a sequence of hand-written prompts.
Its target worker count is **the maximum concurrency the platform permits**. There is no
planned idle capacity while any research, corroboration, impact analysis, rewrite, or
verification task remains.

The initial queue contains at least 56 independent work units:

| Pool | Initial work units | Purpose |
|---|---:|---|
| Franchise scouts | 32 | One exclusive team each: roster, transactions, first-team work, role battles, injuries, beneficiaries |
| Official-record monitors | 2 | NFL transaction wire plus club releases/roster designations |
| Health specialists | 4 | PUP/NFI/IR and surgery; practice/return reporting; suspension/discipline; historical availability |
| Position/role specialists | 4 | QB; RB/handcuff; WR; TE/OL and route/snap context |
| Projection/ranking specialists | 4+ | One per independent projection or rank family, plus a normalizer |
| ADP/mock specialists | 3+ | ESPN market/mocks; 10-team PPR public market; sample and platform audit |
| League/schedule specialists | 2 | ESPN settings/payout/playoffs and NFL byes/calendar |
| Data-pipeline specialists | 2 | Projection/context joins and source-snapshot manifests |
| Independent verifiers | 3 minimum | High-impact and conflicting findings; expand one-for-one with the verification backlog |

If the platform allows 12 concurrent subagents, the dispatcher runs 12 and keeps the
remaining tasks queued. If it allows 64, it launches the whole initial burst and creates
new impact cells as findings arrive. Near-infinite token availability is spent on broad
coverage, independent checking, and fast re-runs — not on giving several agents
permission to overwrite the same CSV.

### 8.1 Always-busy scheduling rule

Whenever a worker finishes, the controller immediately assigns the highest available
item in this order:

1. unclaimed breaking news or a league-setting change;
2. an expired named-event freshness check;
3. independent verification of a high-impact or conflicting claim;
4. a downstream impact task created by an approved receipt;
5. the next unreviewed franchise or top-160 player;
6. current-source recertification, player-context gap closure, citation audit, or link QA;
7. an unchanged-source recheck whose SLA is due.

A no-change finding still returns a dated receipt and immediately frees the worker for
the next item. An agent never waits for a whole wave if useful read-only work is ready.

### 8.2 Coordinator and integrator are different roles

- The **campaign controller** owns task state, priorities, leases, dependency invalidation,
  run IDs, and the publish gate. It does not decide player projections by fiat.
- **Research workers** read sources and submit receipts. They do not edit shared data.
- **Verifiers** receive the claim and evidence, not the collector's conclusion. They
  approve, reject, or preserve a conflict.
- **Data stewards** are single writers for players.csv, player_context.csv, and any new
  current-status table.
- The **model owner** is the single writer for the three coupled baseline
  implementations and simulation settings.
- **Prose owners** get non-overlapping note groups after the data freeze.
- One **release integrator** runs all generators, reviews orphan deletion, injects the
  hub, and produces the release receipt.

## 9. Durable task, evidence, and dependency ledgers

Before the large fan-out, create lightweight machine-readable campaign state in the
vault's Data directory:

| Artifact | Role |
|---|---|
| research-task-ledger.csv | Queue, state, priority, entity scope, lease owner/expiry, dependency, verifier, and receipt |
| research-receipts.jsonl | Append-only evidence and no-change receipts |
| current-status.csv | Current team, roster/status, role, health, event date, confidence, and source pointer |
| dependency-manifest.json | Maps source/data fields to board, note, player, team, and site outputs |
| research-run-manifest.json | Run ID, cutoff, exact snapshots/hashes, settings version, commands, and accepted blockers |

The task state machine has one canonical-write path:

    queued -> leased -> researched -> verification_pending
           -> approved -> applied -> recomputed -> published

    conflicted  -> labelled branches or quarantine; never a silent point estimate
    quarantined -> closed until a new qualifying receipt reopens it
    rejected    -> closed and retained; never applied

Only the controller mutates task state or leases and appends to the canonical receipt
ledger. Workers return structured results to the controller; they never append directly
to the shared CSV/JSONL files. The alternative at very high throughput is one atomic
per-task receipt file followed by controller compaction. Both paths use the idempotency
key `(run_id, source_snapshot_hash, subject, claim_type, event_at)` so a reclaimed task
or repeated no-change check cannot create duplicate leases or downstream impact cells.

Research leases should be short and reclaimable: roughly 20–30 minutes for breaking
items and 90 minutes for a whole-team sweep. A worker renews by heartbeat; an expired
lease returns safely to the queue because the canonical files were never in that
worker's ownership.

Every receipt records at minimum:

- run, task, team/player/league subject, claim type, and old/new value;
- fact, reported expectation, model, market observation, or community lead;
- canonical URL, source family, author, and Official/Reported/Community grade;
- event, publication/update, observation, and access timestamps;
- season, platform, scoring, team count, population, and roster version;
- role confidence and health confidence;
- source snapshot path or hash;
- corroborates, contradicts, and supersedes relationships;
- proposed data fields and affected downstream artifacts;
- impact tier, owner, verifier, disposition, and rationale.

This fills the current provenance gap: players.csv has only one ADP source label and
player_context.csv one broad source field, neither of which can safely carry a live
injury or camp-role workflow.

## 10. Research data plane — what the agents must refresh

### 10.1 League contract, first

Two agents independently read the current ESPN league/settings screens and reconcile:

- 10 teams and snake draft;
- Andrew at 1.01 and whether the rest of the order is locked;
- Full PPR fractional scoring, including every kicker and D/ST bracket;
- 1QB/2RB/2WR/1TE/1FLEX/1D-ST/1K starters, bench, IR, and 16 rounds;
- waivers, acquisition caps, lineup locks, and trade rules;
- keeper/redraft status;
- buy-in, payouts, paid places, playoff field/weeks, and regular-season length;
- exact draft date and timezone.

The settings receipt is a hard dependency for replacement levels, simulation, payoff
strategy, season pages, and the draft countdown. The plan does not re-ask settings that
are unchanged from §6, but it does not assume a different 10-team league inherited them.

### 10.2 Thirty-two franchise scouts

One agent owns each NFL franchise and returns a structured delta against the July 25
snapshot:

- executed transactions and current roster/designation;
- QB starter or competition;
- RB touch hierarchy and handcuff/injury inheritance;
- WR target order, three-receiver usage, slot/outside role;
- TE route/blocking role;
- first-team camp and preseason deployment;
- PUP, NFI, IR, suspension, holdout, surgery, and return expectations;
- coordinator/play-caller, offensive-line, and scheme changes;
- changed games, carries, targets, receptions, yards, touchdowns, risk, or rationale;
- the two-to-four players whose fantasy summary belongs in The 32 offenses;
- explicit no-material-change status when nothing moved.

Team scouts submit receipts only. Cross-team events such as trades create linked old-team
and new-team tasks before either team is considered complete.

### 10.3 Source-specialist lanes

Run these continuously beside the team swarm:

| Lane | Source/use rule | Deliverable |
|---|---|---|
| Transactions/rosters | NFL and club records establish executed facts | Dated membership/designation deltas |
| Injuries/health | Official status where available; named camp reporting before regular-season reports exist | Current health branch, timetable, beneficiary set |
| Beat/camp roles | Named, dated reporting establishes expectations only | Low/base/high volume or role branches |
| Projection sources | Current 2026 native stat lines preferred; foreign scoring totals are audit-only | Versioned source snapshots and normalized stat-line comparisons |
| Rankings | Dated, format-labelled consensus or experts audit the board | Disagreement flags, never substituted for VOR |
| ADP/mocks | ESPN 10-team Full-PPR preferred; otherwise labelled 10-team proxy with sample/window | Market timing distribution and turn availability |
| nflverse/context | Roster, 2023–25 usage/snaps/injuries, age, draft data | Regenerated observed context and join report |
| Contracts | Current contract source, cross-checked with roster identity | Contract/roster-pressure deltas |
| Schedule/byes | Official schedule | Bye validation and 1.01 roster-combination constraints |
| K/DST | League scoring plus current source inputs | Explicitly modelled ordering with uncertainty |
| Rookies/backups | Draft capital, roster survival, role, and handcuff paths | Expanded coverage beyond the current 243/203 rows |

No source gets to answer a question outside its authority. A club transaction page can
establish that a player signed; it cannot establish his workload. A rank can flag a
disagreement; it cannot replace a projection. Preseason box-score production alone
cannot change a forecast.

### 10.4 Source certification gates

Before a numerical source enters the freeze, verify:

- correct 2026 season and visible publication/update/access dates;
- current player population, teams, rookies, and roster state;
- native format and method;
- league size and scoring for ADP/ranks;
- raw stat lines rather than silently incompatible fantasy-point totals for projections;
- stable snapshot retained before a mutable page is replaced;
- sample size and date window for ADP;
- explicit missing-field behavior.

The current FFToday July 23 file and 12-team FF Calculator July 25 file remain archived
as the old control. They do not pass the fresh 10-team import gate merely because their
web pages still load.

## 11. Verification and conflict policy

1. Official facts outrank Reported expectations; Community material opens a research
   task but never establishes a value.
2. Normalize only like-for-like claims: same subject, claim type, horizon, date, format,
   population, and unit. ADP, rank, projection, and observed usage never vote against
   one another because they answer different questions.
3. Two equal Reported sources that disagree remain two receipts. Mark the field
   conflicted, lower role or health confidence, and retain low/base/high branches. Do
   not average incompatible narratives.
4. A newer page supersedes an older one only when the underlying event or numerical
   payload is newer. A fresh page shell or roster badge is not a fresh projection.
5. Every top-160 player change, quarterback change, lead-RB/handcuff change, current
   injury/return claim, tier-boundary change, or 1.01 candidate requires a verifier who
   was not the collector.
6. Deduplicate source families. A team release copied by a reporter, aggregator, and
   social post is one fact, not four-source consensus.
7. Every correction links old receipt to new receipt and invalidates its dependency
   targets. Rejected findings remain in the ledger so a later agent does not rediscover
   and reapply them.

## 12. Dynamic event workflows

An approved event automatically dispatches its smallest complete impact cell:

| Trigger | Parallel impact tasks | Outputs invalidated until recomputed |
|---|---|---|
| Injury, PUP/NFI/IR, surgery, clearance | official/status verifier; role/health analyst; backup/teammate inheritance; games/volume projection; ADP check | player row, context/status, team summary, board/tier, 1.01/turn queues |
| Signing, release, trade, suspension | old/new team checks; roster verifier; touch/target budget; affected players; projection and market impact | both teams, related players, rankings, waiver/handcuff advice |
| First-team role or coach quote | source verifier; snap/role specialist; competing-player branch; projection sensitivity | role confidence, risk, rationale, affected tier |
| New projection snapshot | schema/source certification; player/team join; scoring recompute; independent provider comparison | players.csv, VOR, tiers, all numerical prose |
| New ADP or mock batch | format/sample certification; movement diff; pick-availability simulation | value deltas, turn targets, reach/wait rules |
| League-setting change | second settings read; baseline/simulation owner; blast-radius mapper | format key, all model and strategy outputs |
| Named checkpoint | full affected-team/source sweep; expired-receipt scan | any artifact whose oldest parent missed the SLA |

The controller creates the dependency tasks as soon as a receipt is approved. Quiet-team
workers immediately pull another team-signal slice, top-player review, source
recertification, or independent check. This is the mechanism that keeps maximal agents
useful rather than merely numerous.

## 13. Execution DAG and waves

The waves are dependency barriers for writes, not barriers to read-only research.
Agents continue filling future-wave evidence queues while a prior wave integrates.

| Wave | Maximum-concurrency work | Single-writer fan-in / exit gate |
|---|---|---|
| 0. Snapshot | Hash current vault/data/generator/output; archive July sources; seed task/dependency ledgers | Clean baseline and run ID |
| 1. Settings | Independent ESPN reads; resolve Q0–Q6 and draft date | Signed settings receipt |
| 2. League sweep | 32 team agents plus every specialist lane; top-160/player-context gap tasks | One fresh or explicit no-change receipt per required scope |
| 3. Adjudication | One verifier per high-impact/conflicted finding; source-family dedupe | No unreviewed critical receipt |
| 4. Data freeze | Projection, context, current-status, ADP, schedule, and settings stewards integrate approved deltas | Immutable input manifest and changed-row report |
| 5. Model conversion | Independent math analyses; model owner updates all coupled constants and settings; recompute board/context/simulation | Reproducible 10-team board, tiers, availability, simulation |
| 6. Draft decisions | Parallel 1.01 candidates, 20/21 and later-turn scenarios, roster-construction and mock agents | One evidence-backed draft card plus contingencies |
| 7. Corpus rewrite | Disjoint note-owner groups use the same run; stale-output mapper opens targeted player/team edits | All current prose bound to run ID |
| 8. Build/release | One release owner regenerates notes/site, injects hub, validates and browser-QAs | Section 7 passes and diff accepted |
| 9. Live refresh | Event monitor and named checkpoints reopen impacted DAG branches | Draft −48h and day-of release receipts |

Blocked workers do not sit idle. They work on independent source capture, no-change
certification, historical context joins, link/dependency mapping, or the next checkpoint
queue. Only the single writer waits at a barrier.

## 14. Data and model implementation

### 14.1 Canonical data refresh

1. Preserve dated raw copies of every projection and ADP source.
2. Refresh Data/nflverse and contract inputs, then run fetch_nflverse.sh and
   build_context.py; require complete QB/RB/WR/TE coverage and explicitly report the 20
   K plus 20 D/ST rows that are excluded from player context by design.
3. Rebuild players.csv from certified current projection stat lines, current teams and
   byes, and 10-team market data. Do not hand-patch it to resemble a newer web page.
4. Add current-status.csv for present-tense health/roster/role claims. Historical
   availability stays in player_context.csv; current injury expectation must not be
   smuggled into a three-year availability rate.
5. Emit a changed-row manifest so team, player, board, and prose owners know exactly
   which downstream pages reopened.

### 14.2 Coupled 10-team model change

With the confirmed current starter line:

- drafted population: 10 × 16 = **160**;
- effective replacement ranks: **RB24, WR26, TE10, QB10**;
- K/DST: independently review the §1.5 rank-2 streaming model and record the decision;
- turn sequence:
  **1, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101, 120, 121, 140, 141, 160**;
- format key: **espn-ppr1.0-10tm-std**.

One model owner changes all coupled sites in one lease:

- vault Data/build_board.py;
- vault Data/simulate_season.py;
- repository fantasy/football/build.py;
- generated/prose copies in _PLAN.md, Your league in one page, and Drafting from the
  1.01.

The simulation cannot become authoritative until payouts, playoff field, season length,
and keeper status clear the settings gate. The Draft Room independently reimplements
VOR, so agreement with the vault board is a hard release invariant.

### 14.3 Rebuild order

From the vault Data directory:

    sh fetch_nflverse.sh
    python3 build_context.py
    python3 build_board.py
    python3 simulate_season.py

Then:

    cd /Users/andrewpark/Desktop/Code/PersonalSite/fantasy/football
    python3 build.py
    cd /Users/andrewpark/Desktop/Code/PersonalSite
    python3 scripts/inject_hub.py

Data/build_board.py overwrites three notes — 2026 draft board, Tiers by position, and
Availability and injury risk. Data/simulate_season.py overwrites When to start drafting
for upside. Those four notes are never assigned to prose agents.

## 15. Draft strategy and site rewrite

### 15.1 The 1.01 decision system

After Wave 5, dispatch independent agents for:

- each credible 1.01 candidate's fresh role, health, projection, adjusted VOR, and floor/
  ceiling case;
- opportunity cost of the 18-pick wait;
- at least five current 10-team ESPN-like mocks from 1.01, including at least one human
  room if available;
- distributions, not single names, at picks 20/21, 40/41, 60/61, and later turns;
- positional-run and tier-cliff scenarios;
- bye-week and roster-complement checks;
- robust branches for a target taken one pick before the turn;
- same-day injury/transaction triggers that change the top pick or turn queue.

The publishable output is a draft-day card: current pick at 1.01, ranked contingency
queue at every turn, do-not-reach thresholds, position/tier needs, and the evidence/event
that would change each instruction. It is versioned to the final data freeze. It never
contains a fixed player merely because §2 contained one on July 25.

### 15.2 Disjoint prose ownership

After the model freeze, assign separate writers:

| Owner group | Vault scope |
|---|---|
| Reference/settings | _PLAN.md; Start Here/Your league in one page; How the league is won; season calendar |
| Core draft | Drafting from the 1.01; Who to take at 1.01; VOR; RB spend; late QB; reading room; last rounds |
| Concepts | Replacement, league size, scarcity, streaming, draft capital, payoff/sample-size notes |
| Season | Waivers, bye weeks, start-sit, injury reports, weather/playoffs |
| Teams/players | The 32 offenses and only the player dossiers opened by the changed-row/dependency manifests |
| Sources/progress | Evidence policy, provenance ledger, ADP/projection distinctions, _Progress.md |
| Metadata | All 108 current-format frontmatter records, applied mechanically after the setting freeze |

Add the planned League size and replacement level note and a current team/injury/role
ledger generated from approved receipts. Keep genuine historical or third-party
12-team references labelled as such. Remove only claims that pretend the current league
or current market is 12-team.

### 15.3 User-facing surfaces

The generated release must update:

- the fantasy landing panel and football home masthead/1-20-21 CTA;
- Draft Room pick chips, VOR, adjusted VOR, rank, tier, filters, and data timestamp;
- draft board, tiers, 1.01 pages, and reference card;
- player fact cards and any affected ledes;
- The 32 offenses and current injury/role ledger;
- search-index entries so 10 team, 1.01, and 20/21 surface the right pages;
- source/provenance pages and every as-of/expires badge;
- the site-wide football format marker.

Generated HTML is reviewed but never used as an upstream editing surface.

## 16. Refresh cadence, stop conditions, and campaign handoff

### 16.1 Named-event cadence

Use the corpus's event calendar and add fast event SLAs:

- **Now / camp:** complete the July 26-to-current delta sweep; scan every team daily for
  roster, first-team role, PUP/NFI, injury, holdout, and discipline changes.
- **Breaking event:** dispatch within 30 minutes; target verified resolution within two
  hours for top-160 impact.
- **Second preseason game:** recertify first-team deployment and role branches; ignore
  raw preseason yardage and touchdowns.
- **August 30 cutdown:** run 32 simultaneous roster-resolution tasks, then re-pull
  projections/ADP and reopen every beneficiary/handcuff path.
- **Final preseason:** health and depth-chart pass.
- **Draft −7 days:** full league, projection, market, settings, and mock refresh.
- **Draft −72 hours:** settle 1.01 candidate evidence and every turn branch.
- **Draft −48 hours:** mandatory raw projection and 10-team ADP pull, canonical rebuild,
  independent board audit, corpus render, and release candidate.
- **Draft day:** hourly settings/news/injury monitoring; rebuild only the affected
  dependency cone, then issue a final timestamped draft card.
- **In season:** transactions and role news daily; official injury reports Wednesday
  through Friday; inactive check on game day; Monday waiver-impact cycle.

### 16.2 When an individual task stops

A worker stops only after submitting:

- an approved evidence candidate or explicit no-change receipt;
- exact source/access time and scope;
- contradiction and confidence status;
- proposed changed fields and dependency targets;
- no undeclared canonical-file edits.

### 16.3 When a wave stops

A wave stops only when every required scope has a fresh receipt, all critical conflicts
have a disposition, and its fan-in artifact is immutable and hashed. Running out of
agents, tokens, or convenient sources is not a scientific completion condition.

### 16.4 When the campaign is done

The campaign is complete only when:

1. all 32 teams and every source lane meet the release SLA;
2. the league settings receipt closes every strategy-affecting question or marks the
   dependent output unavailable;
3. current projection, context, health/role, and 10-team ADP data are frozen and
   reproducible;
4. the 10-team board, tiers, simulation, and Draft Room agree;
5. the 1.01 and every turn queue use the final run rather than July names;
6. all source notes and current-format pages carry honest timestamps/provenance;
7. every Section 7 gate passes;
8. the controller leaves behind the task ledger, receipts, run manifest, changed-row
   manifest, commands, hashes, rejected findings, open conflicts, and next event trigger
   so the next agent swarm can resume without rediscovering the campaign.
