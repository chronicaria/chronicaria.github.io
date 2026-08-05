# Summer 2027 quant internships

A single static page listing every Summer 2027 quantitative trading, research and developer
internship in the United States open to an undergraduate graduating **May 2028**, with direct
application links, posted compensation, and each firm's application-limit policy.

**86 firms, 145 roles**, checked 5 August 2026. Every firm carries a community-sourced
interview-process panel and, where one could be established, an honest reputation read.

Built the same way as the other sites in `~/Desktop/Code`: static HTML, one token-based
stylesheet, one vanilla-JS IIFE. No framework, no bundler, no `package.json`.

```
index.html          markup, filter controls, board shell, notes
assets/style.css    design tokens + all styling; light and dark via [data-theme]
assets/app.js       fit model, filtering, sorting, search, applied-tracking (one IIFE)
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

`data.js` exports `FIRMS`: one object per firm, with every role that firm posts nested
inside it. **The grouping is load-bearing.** Application limits are a firm-level fact, so the
roles that compete for a single slot have to be rendered together or the decision cannot be
made. A flat role list — which this page used to be — hides exactly the thing that matters.

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

`S` `A` `B` `C` are a read on selectivity, compensation and exit value — not a ranking of the
firms as businesses. `S` is the handful of seats where an offer resets a career; `C` is
smaller, regional, or a genuine quant desk inside a firm that is not primarily a quant shop.

There is no D or F tier. Every firm on the board is a quant seat: the B and C tiers were
audited firm by firm against community sources, and anything whose "quant" role turned out to
be operations, credit-risk reporting, regulatory engineering or team-side sports analytics was
**removed** rather than parked in a low tier. Eleven firms were cut that way and seventeen were
regraded in both directions. The scam warning that used to live in an F tier is now a line in
the Applying notes, where it cannot be mistaken for somewhere to apply.

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

On by default. It sorts by fit against one specific résumé, orders roles QR before QT before
QD, hides grade F, and prints the reason each seat scored what it did. Every weight lives in
one table at the top of `app.js` — change the résumé, change that table, change nothing else.

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

Firms sort by the active sort key — fit, grade, pay, deadline or name. Within a card, roles
sort QR before QT before QD in Andrew mode, then by fit. Firm order in `data.js` is the
tiebreak the grade sort respects, so reordering the file changes presentation within a tier.

## Keyboard

`/` focus search · `Esc` clear · `1` `2` `3` toggle QR/QT/QD · `a` Andrew mode · `0` reset.
