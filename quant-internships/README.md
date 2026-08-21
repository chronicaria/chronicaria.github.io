# Summer 2027 quant internships

A single static page listing every Summer 2027 quantitative trading, research and developer
internship open to an undergraduate graduating **May 2028**, with direct application links, posted
compensation, and each firm's application-limit policy. US first, but no longer US-only.

**162 firms, 261 roles**, data checked 20 August 2026, graded, culled and expanded 10 August 2026,
widened 20 August 2026. Every firm from the original board carries a community-sourced
interview-process panel and, where one could be established, an honest reputation read.

## The 20 August 2026 widening

The board was built US-only, buy-side-only and strict-quant-only. That charter excluded a large
amount of work worth applying to, so it was relaxed on three axes at once:

- **Non-US roles are in scope.** London, Amsterdam, Hong Kong, Oslo, Montreal. `locBucket` in
  `app.js` gained an `International` bucket; it decides by whether a location is written `City, ST`
  with a real US state code, which is the convention every US posting on the board follows.
- **Sell-side is in scope.** Bank quant strats, quant risk, model validation, market risk. Banks
  stay at grade **B** — Goldman, JPM and Citi were already B, and the new arrivals match them.
- **Quant-adjacent is in scope.** Data science, economic consulting, national labs, actuarial and
  catastrophe modelling. These share a `Data science & adjacent` chip via `CAT_GROUP`.

Roles were found by two fan-out sweeps (12 segments, then 10) in which each agent fetched every
requisition before recording it, followed by an adversarial pass that re-fetched every URL and
killed **85 rows**. The kill reasons are worth knowing, because they are what a naive sweep gets
wrong:

| reason | note |
|---|---|
| plain SWE wearing a quant label | the most common failure by a wide margin |
| generic careers page, not a requisition | agents will happily cite a landing page |
| PhD- or Master's-only | out by the board's existing rule |
| aggregator repost | Lensa, Jobright, Jorb, ZipRecruiter |
| wrong cycle | Summer 2026 reqs still live |

Two mechanical lessons carried forward: most careers pages are JavaScript shells that return
nothing to a plain fetch, so the ATS JSON APIs (`boards-api.greenhouse.io`, Workday `/wday/cxs/`,
Lever, Ashby) are the reliable path; and any HTTP call in a sweep needs a hard timeout, because one
unanswering host stalled an entire segment for the better part of an hour.

**`status: "soon"`** now carries real weight — 66 of the 261 roles. It is August, and most Summer
2027 bank and big-tech programmes have not opened. A `soon` row is a programme that reliably runs
every year, with evidence for its timing in `notes`. The *+ opening soon* chip reveals them.

Built the same way as the other sites in `~/Desktop/Code`: static HTML, one token-based
stylesheet, one vanilla-JS IIFE. No framework, no bundler, no `package.json`.

```
index.html          markup, filter controls, board shell, notes
assets/style.css    design tokens + all styling; light and dark via [data-theme]
assets/app.js       fit model, table render, drawers, filtering, sorting, search (one IIFE)
assets/data.js      the firms and roles — this is the only file you normally edit
favicon.svg
```

## Running it

Any static server. The repo's `.claude/launch.json` serves the whole site:

```bash
python3 -m http.server 8787
```

Then open <http://localhost:8787/quant-internships/>.

## Shape

`data.js` exports `FIRMS`: one object per firm, with every role that firm posts nested inside it.
**The grouping is load-bearing.** Application limits are a firm-level fact, so the roles that
compete for a single slot have to be readable together or the decision cannot be made.

The page renders **one table row per role**, not one card per firm. The grouping survives the
flattening: roles from one firm stay adjacent, only the first row of a run prints the grade and the
firm name, and a heavier rule marks where a run starts. The version before this one was a card per
firm with the eligibility window, the notes and the fit rationale printed under every role — about
250px of vertical space per firm, forty screens of scroll for 145 roles, and the reason this
rewrite happened. A row is now 34px.

Everything that is not a glanceable column lives in a **drawer** that opens under the row: the
verbatim eligibility window, the pay string in full, the firm's policy and assessment, the
"spend it on" recommendation, and the interview panel (itself a nested `<details>`, because it is
an order of magnitude larger than everything else). Drawers are only built for rows that are open,
so a closed board costs nothing.

### Columns

| column | width | notes |
|---|---|---|
| Gr | 62px | first row of a firm run only |
| Firm | 18% | first row of a run only; `1×` badge when `one_only` |
| Role | rest | chevron, type mark, ISO deadline, title (truncates) |
| Where | 12% | first location + `+n`; hidden below 1000px |
| Pay | 12% | total over the internship, or the posted figure; hidden below 700px |
| Fit | 44px | Andrew mode only |
| Apply | 128px | apply link + the applied toggle |

Columns drop rather than wrap as the viewport narrows. Everything dropped is still one tap away in
the drawer.

The full field contract is documented in the header comment of `data.js`. Four rules matter:

1. **Never invent a URL or a compensation figure.** An empty string renders as "not disclosed",
   which is honest. A guess is not.
2. **`comp_source` must be `"posted"` or `"reported"`.** Posted means it was in the job
   description, usually because a pay-transparency law forced it. Reported means levels.fyi,
   Glassdoor or similar. The page shows this under every figure so the reader can weight it.
3. **`id` is permanent.** It keys the local "applied" flag in `localStorage`. Reusing an id
   silently transfers a checkmark to a different job. The generator enforces global uniqueness.
4. **`one_only: true` only for a genuine hard restriction.** "Bundle several roles in one
   application" is permissive and must not be flagged.

PhD- and Master's-only postings are deliberately absent. The exclusions are listed by name in
the `data.js` header so a future update doesn't "rediscover" them.

## Grades

`S` `A` `B` `C` are a read on selectivity, compensation and exit value — not a ranking of the firms
as businesses. There is no D or F tier; the scam warning that used to live in an F tier is a line in
the Applying notes, where it cannot be mistaken for somewhere to apply.

**`S` is three firms: Jane Street, Citadel Securities, Hudson River Trading.** It was ten. Jump,
Optiver, SIG, Five Rings, D. E. Shaw, Citadel and Two Sigma were all S and are all A now — every one
of them pays materially below the three above, and a ten-firm S tier is not a tier, it is a list of
firms you have heard of. **Do not let it grow back.** If a future pass wants to promote something to
S, the bar is top-of-market undergraduate pay *and* the widest exit optionality on the board, and
something else should probably come out.

Twenty-one firms were **cut** on 10 August 2026, for one of two reasons, and both matter:

1. **Nothing to apply to.** No undergraduate-eligible Summer 2027 quant requisition exists —
   the internship is PhD-only (PIMCO, Talos), the cycle already closed (Deutsche Bank), or the firm
   simply posts no internship (Headlands, Tudor, Graham, Valkyrie, Qube, Marshall Wace, PEAK6).
   A board whose entire value is being applied-to-able cannot carry a firm with no seat.
2. **The "quant" seat is not quantitative work.** T. Rowe Price's is fundamental equity research,
   IEX's is an exchange generalist, Cboe's is dashboards for operational efficiency, Bloomberg's is
   Global Data collection and QA, Vanguard's is portfolio analytics, DraftKings' and FanDuel's are
   product analytics, Cargill's is commodity merchandising.

A separate expansion sweep the same day checked **75 firms absent from the board** — including XTX,
Quantlab and Vatic by name — against their own careers pages and ATS boards, and added two:
**Quadrature Capital** (a NY quant-developer internship inside a generic "Internships" req) and
**DL Trading** (sports and prediction-market pricing in Chicago, the closest published match on the
whole board to four cycles of Kelly-sized event-contract trading).

The other 73 failed, and the reasons matter more than the names: no US role, no internship
requisition of any kind, a graduate-only gate, a cycle already closed, or the Cargill failure mode —
a commercial rotation wearing a quant label. Both the cuts and the 73 rejections are listed by name
with their reasons in the header of `data.js`, so a future sweep does not rediscover them. Two are flagged **re-add on sight**: DraftKings (if a Predictions or Railbird intern
req ever posts) and Valkyrie (if any intern req posts) — both were cut on absence, not on quality.

The sports rule still holds and is worth restating: **sports betting is in, sports analytics is
out.** A sportsbook pricing or trading seat is quantitative work against a market. A league, team or
product analytics seat is not, however interesting it is. That rule is what removed DraftKings and
FanDuel even though both own genuine event-contract businesses.

The sports rule is worth stating explicitly because it will come up again: **sports betting is
in, sports analytics is out.** A sportsbook pricing or trading seat is quantitative work
against a market. A league or team analytics seat is not, however interesting it is.

## Interview intel

Each firm carries an `intel` object rendered as a collapsed `<details>` panel: ordered rounds,
the assessment in detail, what to study, publicly reported question types, timeline,
difficulty, candidate tips, a confidence mark and source links. Plus a `reputation` field —
what the community actually says, including the unflattering parts (comp below peers, layoffs,
weak exits, technical debt).

Rules that keep this honest, and that any future update must preserve:

1. **Never fabricate a question, a round count or a source URL.** A candidate preparing for the
   wrong thing is worse off than one preparing for nothing. Empty beats invented.
2. **Attribute, don't assert.** "Candidates on r/quant report" — not "the interview is".
   Where the firm's own careers page documents the process, prefer it and say so.
3. **Date everything.** A 2019 thread about an assessment format is close to worthless.
4. **Report conflicts rather than resolving them.** If accounts disagree, the panel says so.
5. **Forum content is untrusted data, never instructions.** The research agents are told this
   explicitly and asked to flag any page that tries to inject directives.

Coverage is honest about itself: confidence is `high` for only about a tenth of firms — those
that publish their own process — `medium` for most, and `low` where the process simply is not
public. `low` is a real answer, not a failure.

## Andrew mode

On by default. It sorts by fit against one specific résumé, orders roles QR before QT before QD,
and prints the reason each seat scored what it did inside the row drawer. Every weight lives in one
table at the top of `app.js` — change the résumé, change that table, change nothing else.

Two invariants that were each violated by an earlier version and are worth preserving:

- **The grade spread must exceed the total tag spread.** Otherwise a topical match at a
  mid-tier shop outranks a top-tier seat. Tags are capped at `TAG_CAP` so they break ties
  *inside* a tier rather than across tiers.
- **Tag keywords must be word-bounded.** Without `\b`, `election` matches s-*election*,
  `oil` matches sp-*oil* and `power` matches *power*-ful. That fired the highest-weighted tag
  on ordinary postings and silently corrupted the ranking.

Research notes are also stripped of negated sentences before tagging, because they routinely
say things like "the posting does not mention event contracts", which a keyword matcher reads
as a hit.

## Verification

Data checked **5 August 2026** against firm-hosted career pages, Greenhouse/Lever/Ashby/Workday
boards, and <https://github.com/northwesternfintech/2027QuantInternships>.

All 145 application links resolve. Seven return 403 to automated requests and were confirmed in
a real browser instead — **do not "fix" these on the strength of a failing HEAD check**:
Citadel, Citadel Securities, DraftKings and Fidelity are behind Cloudflare or a bot filter.
PIMCO's Workday board intermittently returns 500 under concurrent load; retry before believing it.

A second pass went back over the twelve intel records that shipped without sources and tried to
corroborate them. It is worth reading what that pass **falsified**, because it is the strongest
argument for keeping the `unverified` field:

- Citadel Securities' and Citadel's "6 rounds" — unsupported. Third-party guides claim 4 and 8.
- IMC's "one application per role per year" — **contradicted by IMC's own FAQ**, which answers
  "can I apply for more than one job at the same time?" with yes.
- DRW's coding challenge being in Python — no source names a language.
- PIMCO's "4 rounds" — reported as two stages: a HireVue, then a superday of ~5 interviews.
- T. Rowe Price's "4 rounds" — reported as three.
- Vanguard — no public material exists for the Quantitative Equity Group at all.

Claims that survived got sources; claims that did not are printed struck through under
"Could not be corroborated" rather than quietly deleted, and the round-count badge is suppressed
whenever the count itself is what failed. That pass also confirmed things: DRW's four stages and
IMC's five are stated verbatim on the firms' own pages, which is why both are marked high.

Two findings from the last sweep that change how this page should be maintained:

- **The one-application rule is usually NOT in the job description.** It is a required question
  on the Greenhouse *application form*. Scanning posting bodies produces false negatives on the
  highest-stakes field on the board. For any Greenhouse firm:

  ```bash
  curl -s "https://boards-api.greenhouse.io/v1/boards/<token>/jobs/<id>?questions=true"
  ```

- **Optiver's policy is only visible in a rendered browser.** The one-role-at-a-time cap lives
  inside a collapsed accordion and is absent from the served HTML. Anyone re-verifying with
  `curl` will wrongly conclude no policy exists.

To re-check the links after editing:

```bash
python3 -c "
import re,subprocess,concurrent.futures
urls=re.findall(r'apply_url:\s*\"(https://[^\"]+)\"',open('assets/data.js').read())
f=lambda u:(subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}','-L','--max-time','20',u],capture_output=True,text=True).stdout,u)
[print(c,u) for c,u in concurrent.futures.ThreadPoolExecutor(12).map(f,urls) if c not in ('200','403')]
"
```

## Ordering

Firms sort by the active sort key — fit, grade, pay, deadline or name — and the column headers are
the sort control. Within a firm run, roles sort QR before QT before QD in Andrew mode, then by fit —
except under the pay sort, where they sort by pay too, so a firm is never led by its one role with
no disclosed figure.
Firm order in `data.js` is the tiebreak the grade sort respects, so reordering the file changes
presentation within a tier.

## Defaults

Two things are filtered or transformed before you see them, and both are worth knowing:

**Roles that have not opened yet are hidden.** 22 of 126. They are noise while you are deciding
where to spend an afternoon. The `+22 opening soon` chip in the main control row brings them back —
deliberately in the main row and not behind `Filters +`, because a filter that is on by default and
invisible is a trap.

**Pay is the total over the internship, not a rate.** Firms post weekly, monthly, annualised and
lump-sum figures; none of them compare by eye, and the board's whole job is comparison. The column
shows one number and marks it `≈` because it is derived:

```
total = comp_rank × weeks ÷ (52/12)
```

`comp_rank` is the input, not the `comp` string — it is approximate monthly USD, entered per role by
whoever read the posting, and it already resolves the awkward cases ($71,000 over 8 weeks is
recorded as 38,458/month). Re-parsing the prose would reproduce that work worse.

Only 27 roles state a length. The rest assume **10 weeks** and carry a `*`. Every stated length on
the board falls between 8 and 11 weeks, so the assumption is never far wrong, but it is an
assumption and the row says so. The drawer prints the arithmetic in full and the firm's own wording
beside it, and the `≈ total / as posted` toggle under the Pay header switches the column back to
verbatim figures.

**The only real check on any of this**: two postings state a total outright — Bridgewater's `$71,000
total for the 8-week internship` and Walleye's `$50,000 for 10 weeks`. The conversion reproduces
both exactly from `comp_rank` and the extracted length. Both are asserted in `selftest()`; if either
breaks, every other total on the board is wrong too.

## The pay column, and its self-check

Pay strings in `data.js` are verbatim and run to 70 characters. `compShort()` in `app.js` reduces
them to a headline figure and a period for the *as posted* mode, and a trailing `+` says the drawer
has more.

The rule that matters: **a period only counts when it is written as a rate** — `/week`, `per week`,
`a week`, `weekly`. A bare noun does not. `$71,000 total for the 8-week internship` and `$50,000 for
10 weeks` are whole-internship figures, and an earlier version of this rendered both as a weekly
rate. That is the one error on this page that would change where somebody applies.

Append `?selftest` to the URL. It asserts the compressor against the cases that have actually gone
wrong, checks both stated-total anchors against the derived total, and reports any role with a
`comp` but no `comp_rank` (which would silently lose its total). `?selftest=full` adds a table of
every live pay string next to its compression and its computed total:

```bash
open "http://localhost:8787/quant-internships/?selftest=full"
```

`comp_rank` is now load-bearing, not just a sort key — a role with `comp` and a null `comp_rank`
shows no total at all. The self-check names them.

`deadline` is **strictly `YYYY-MM-DD`** — the page renders it as a badge and sorts on it as a
string. An earlier version stored whole sentences there (`Posting states "Anticipated Posting Close
Date: Dec 29, 2025" — that date is in the PAST…`), which broke the sort and pushed role titles off
the row. That prose belongs in `deadline_note`, which the drawer renders.

## Keyboard

`/` focus search · `Esc` clear · `1` `2` `3` toggle QR/QT/QD · `a` Andrew mode · `0` reset.
