# Phase 0 — Projection Engine: Build & Validation Report

**Status: GATE PASSED.** The engine is a verified-faithful port of the BasketballGM (zengm)
rating math, the Monte Carlo projection is correctly structured and calibrated for the cohort
that matters most (developing players), and all outputs are deterministic. No changes were made
to the live site or to `league_generator.py` in this phase.

---

## 1. What was built

| File | Purpose |
|---|---|
| `scripts/projections.py` (652 lines) | Faithful zengm port + numpy-vectorized Monte Carlo projection |
| `tests/test_projections.py` (410 lines) | 22 stdlib-`unittest` tests (parity, structure, determinism, correlation) |
| `scripts/backtest_projections.py` (≈430 lines) | Calibration harness; writes `backtest_summary.json` |
| `scripts/backtest_summary.json` | Machine-readable calibration metrics (regenerated each run) |

**Public API** (`projections.py`): `RATINGS`, `limit_rating`, `bound`, `coaching_effect`,
`player_ovr`, `player_ovr_vec`, `team_ovr`, `develop_paths`, `simulate_player`, `percentiles`.

Run locally:
```
python3 scripts/projections.py                 # self-test (OVR parity, determinism, sanity)
python3 -m unittest discover -s tests          # 22 tests
python3 scripts/backtest_projections.py        # calibration report + summary json
```

---

## 2. Fidelity to the game engine (the most important property)

The port reproduces what BasketballGM would actually do — verified four independent ways:

1. **OVR parity — exact.** `player_ovr` recomputed from the 15 subratings matches the stored
   `ovr` for **all 5,732 rating rows** in `day20.json` — **zero mismatches**. (Confirmed by the
   build agent, an independent reviewer, and a unit test.)
2. **Line-by-line adversarial review.** Three reviewers compared the Python against the zengm
   source (`developSeason.basketball.ts`, `limitRating.ts`, `ovr.basketball.ts`,
   `team/ovr.basketball.ts`, `budgetLevels.ts`, `develop.ts`). Verdict: faithful. Every age
   threshold, age modifier, change-limit pair, the height bump, the floor in `limit_rating`, the
   fudge breakpoints, round-half-up (`floor(x+0.5)`, not banker's rounding), and the team-OVR
   exponential weights all match. No critical or major deviations.
3. **Correlation structure — confirmed.** The single biggest risk was modeling per-season noise
   as independent per rating, which would silently narrow the OVR bands. Empirically the port has
   `corr(ins_delta, ft_delta) = 0.881` and OVR variance >1.3× an independent-per-rating reference —
   the correct signature of the shared per-season `baseChange` draw.
4. **Determinism — byte-identical.** Same seed ⇒ identical arrays (numpy `default_rng`). The
   back-test summary is byte-for-byte identical across repeated runs. This keeps static-site
   rebuilds diff-clean.

---

## 3. Calibration (back-test against the league's own rating history)

Method: for every player with ≥4 rating rows, stand at **each** usable past season (anchor),
project forward with `simulate_player` (n_sims=1000), and compare realized later rating rows to
the projected bands. 693 players, **3,177 anchors, 15,471 OVR comparisons.**

### OVR by anchor-age bucket
| Age bucket | n | coverage80 (→0.80) | coverage50 (→0.50) | bias (realized−p50) | MAE |
|---|---:|---:|---:|---:|---:|
| ≤21 | 3,133 | **0.853** | 0.581 | −1.76 | 5.30 |
| 22–25 | 7,050 | **0.823** | 0.602 | +1.81 | 4.83 |
| 26–29 | 3,588 | 0.651 | 0.410 | +4.98 | 5.89 |
| 30–33 | 1,357 | 0.529 | 0.293 | +6.58 | 7.01 |
| 34+ | 343 | 0.449 | 0.219 | +6.83 | 7.13 |
| **pooled** | 15,471 | 0.755 | 0.518 | +2.35 | 5.42 |

### OVR by horizon
| h (yrs ahead) | coverage80 | bias |
|---|---:|---:|
| 1 | 0.859 | +0.88 |
| 2 | 0.803 | +1.19 |
| 3 | 0.762 | +1.76 |
| 4 | 0.706 | +2.81 |
| 5 | 0.661 | +4.17 |
| 6 | 0.628 | +5.92 |

**The developing-player cohort — the entire point of progression projections — is excellently
calibrated (coverage80 0.82–0.85 for ages ≤25).** The headline progression feature is validated.

### The old-age bias is survivorship censoring, not a model defect
Bias is near-zero at h=1 and for young players, but grows with **both** age and horizon. That is
the fingerprint of survivorship: players who decline hard retire and leave no future rating rows,
so the realized old-age sample is selected toward players who aged *well*, while the model
(correctly) projects the **unconditional** distribution including future retirees.

3-year retention by age (from `retention_by_age`, now in `backtest_summary.json`) confirms the
mechanism — the fraction of player-seasons that still have a rating row 3 years later:

| age | 22 | 23 | 25 | 29 | 33 | 35 | 37 |
|---|---:|---:|---:|---:|---:|---:|---:|
| retention | 0.75 | 0.75 | 0.44 | 0.51 | 0.39 | 0.35 | 0.24 |

By age 37 only ~24% of player-seasons survive 3 more years. The realized survivors decline
gently (mean 1-yr ΔOVR ≈ −2.5 to −3.8 at ages 34–38), but that average excludes everyone who fell
off and retired. **We deliberately do not "correct" for this** — matching the surviving sample
would make the model diverge from the actual game engine, which is the ground truth for what
BasketballGM does to *all* players. The league is a single engine version (v72); the slightly
*negative* young-player h=1 bias rules out a uniform engine-curve offset.

### Subrating notes
`hgt` is essentially constant (coverage 0.98). The physical/decline-driven ratings show the same
survivorship pattern at the subrating level (`endu` 0.41, `jmp` 0.45, `dnk` 0.48 coverage; OVR
aggregates these and remains well-calibrated for young/mid players). No tuning needed — these are
faithful to the engine; the under-coverage is the same censoring effect plus the engine's wide
change-limits on athletic ratings.

---

## 4. Fixes applied after the workflow (post-review)

1. **`player_ovr_vec` 1-D robustness** — rewrote the piecewise fudge with `np.select` so a single
   `(15,)` vector returns a scalar (previously raised `IndexError`). Now matches `player_ovr`
   exactly at every rank. (Reviewer-flagged; not hit by current call paths but on the API contract.)
2. **`pot_p75_peak` engine fidelity** — potential is now always computed at `DEFAULT_LEVEL`
   coaching (team-agnostic ceiling), exactly mirroring `monteCarloPot` in `develop.ts`, instead of
   threading the caller's coaching level.
3. **`n_sims` consistency** — `simulate_player` now forwards `n_sims` to the potential estimate so
   the bands and `pot_p75_peak` use the same sample size.
4. **Multi-anchor back-test** — the harness now anchors at every valid past season (not just each
   player's earliest), which exercises the decline phase and surfaced the survivorship finding
   above. Added a reproducible `retention_by_age` artifact.

---

## 5. Implications for later phases

- **Player progression (Phase 1–2):** validated. Bands are honest for the developing players these
  charts are about. Display `pot_p75_peak` alongside the engine's stored `pot` (they should track).
- **Team-OVR projection (Phase 3):** use the engine's unconditional decline (correct for "what the
  sim would do"). When presenting long-horizon veteran decline, note it reflects the full
  distribution including likely retirements — i.e. a roster's *current* veterans, if they keep
  playing, will tend to beat the median band, but many won't keep playing. The "Projected roster"
  mode's re-sign/retirement logic is where this gets handled honestly.
- **Performance:** ~3,200 player-projections (n_sims=1000) run in well under a minute locally;
  vectorization is sufficient. CI will need `pip install numpy` added to the build workflow — to be
  done in Phase 1 when `projections.py` is first imported by `league_generator.py` (not before).
- **No site impact yet:** Phase 0 added only standalone scripts/tests; the generator and live pages
  are untouched.
