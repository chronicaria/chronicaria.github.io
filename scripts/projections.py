"""
projections.py -- Core projection engine for the Chronicaria basketball-league dashboard.

This module is a faithful Python port of the BasketballGM (zengm) rating math, plus a
numpy-vectorized Monte Carlo development projection on top of it.

Ported from the zengm source (verified against the pulled repo as of this build):
  - limit_rating      <- src/worker/core/player/limitRating.ts
  - bound             <- src/common/helpers.ts (helpers.bound)
  - coaching_effect   <- src/common/budgetLevels.ts (levelToEffect / coachingEffect)
  - player_ovr        <- src/worker/core/player/ovr.basketball.ts
  - team_ovr          <- src/worker/core/team/ovr.basketball.ts
  - develop_paths     <- src/worker/core/player/developSeason.basketball.ts
  - pot_p75_peak      <- src/worker/core/player/develop.ts (monteCarloPot)

All numeric constants in this file were copied directly from the above source files and
verified on the pulled repo. The player_ovr formula reproduces every stored OVR value in
the league export with zero mismatches.

Determinism: all randomness uses a numpy Generator (np.random.default_rng(seed)), so the
same seed yields byte-identical output. This keeps static-site rebuilds diff-clean.

Python 3.9 compatible. Only third-party dependency is numpy.
"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

# ---------------------------------------------------------------------------
# Canonical rating order. Order matters: every numpy array layout that holds
# the 15 subratings uses THIS order on its last axis.
# ---------------------------------------------------------------------------
RATINGS = [
    "hgt", "stre", "spd", "jmp", "endu", "ins", "dnk", "ft", "fg", "tp",
    "oiq", "diq", "drb", "pss", "reb",
]

# Index lookups used by the vectorized development code.
_R_INDEX = {k: i for i, k in enumerate(RATINGS)}
_HGT = _R_INDEX["hgt"]


# ===========================================================================
# Pure ports
# ===========================================================================

def limit_rating(x: float) -> int:
    """Port of limitRating.ts.

    Clamp to [0, 100] then FLOOR to an integer. Applied to every non-hgt rating
    every season.
    """
    if x > 100:
        return 100
    if x < 0:
        return 0
    return int(math.floor(x))


def bound(x: float, lo: float, hi: float) -> float:
    """Port of helpers.bound: clamp x to [lo, hi]."""
    return max(lo, min(hi, x))


# --- coaching ---------------------------------------------------------------

# Constants from budgetLevels.ts
_MAX_LEVEL = 100
_BUDGET_LEVEL_SCALE = 1.1
DEFAULT_COACHING_LEVEL = 34  # DEFAULT_LEVEL; at this level the effect is exactly 0.


def _level_to_effect(level: float) -> float:
    """Port of levelToEffect (budgetLevels.ts)."""
    if level != level:  # NaN check
        return 0.0
    # Math.round in JS is round-half-up; for the integer-ish levels we use here
    # (e.g. 34) this is unambiguous. Use floor(x+0.5) to match JS semantics.
    rounded = math.floor(level + 0.5)
    x = (3 * (rounded - 1)) / (_MAX_LEVEL - 1) - 1
    if x < 0:
        return _BUDGET_LEVEL_SCALE * x
    return _BUDGET_LEVEL_SCALE * math.tanh(x)


def coaching_effect(level: float = DEFAULT_COACHING_LEVEL) -> float:
    """Port of coachingEffect (budgetLevels.ts). 0.09 * levelToEffect(level).

    coaching_effect(34) == 0.0 exactly (DEFAULT_LEVEL).
    """
    return 0.09 * _level_to_effect(level)


# --- player ovr -------------------------------------------------------------

# Coefficients and offsets in RATINGS order (hgt..reb). Verified against
# ovr.basketball.ts: this exact formula reproduces all stored OVR values.
_OVR_COEF = np.array([
    0.159,   # hgt
    0.0777,  # stre
    0.123,   # spd
    0.051,   # jmp
    0.0632,  # endu
    0.0126,  # ins
    0.0286,  # dnk
    0.0202,  # ft
    0.01,    # fg   (note: fg coef is 0.01)
    0.0726,  # tp
    0.133,   # oiq
    0.159,   # diq
    0.059,   # drb
    0.062,   # pss
    0.01,    # reb  (note: reb coef is 0.01)
], dtype=np.float64)

_OVR_OFFSET = np.array([
    47.5,  # hgt
    50.2,  # stre
    50.8,  # spd
    48.7,  # jmp
    39.9,  # endu
    42.4,  # ins
    49.5,  # dnk
    47.0,  # ft
    47.0,  # fg
    47.1,  # tp
    46.8,  # oiq
    46.7,  # diq
    54.8,  # drb
    51.3,  # pss
    51.4,  # reb
], dtype=np.float64)

_OVR_INTERCEPT = 48.5


def _fudge(r: float) -> float:
    """Fudge factor from ovr.basketball.ts (scalar)."""
    if r >= 68:
        return 8.0
    if r >= 50:
        return 4 + (r - 50) * (4 / 18)
    if r >= 42:
        return -5 + (r - 42) * (9 / 8)
    if r >= 31:
        return -5 - (42 - r) * (5 / 11)
    return -10.0


def player_ovr(ratings: Mapping[str, float]) -> int:
    """Port of ovr.basketball.ts. Accepts a dict-like mapping of the 15 keys."""
    r = _OVR_INTERCEPT
    for i, key in enumerate(RATINGS):
        r += _OVR_COEF[i] * (ratings[key] - _OVR_OFFSET[i])
    val = math.floor(r + _fudge(r) + 0.5)  # Math.round == round-half-up
    if val > 100:
        return 100
    if val < 0:
        return 0
    return int(val)


def player_ovr_vec(arr: np.ndarray) -> np.ndarray:
    """Vectorized player_ovr.

    arr: numpy array of shape (..., 15) in RATINGS order.
    Returns an int array of shape (...) with identical rounding/clamp behavior.
    """
    arr = np.asarray(arr, dtype=np.float64)
    # r over the last axis
    r = _OVR_INTERCEPT + np.sum((arr - _OVR_OFFSET) * _OVR_COEF, axis=-1)

    # Vectorized piecewise fudge factor. np.select is rank-agnostic, so this
    # handles a single (15,) vector (-> 0-d/scalar result) as well as (N, 15)
    # and (N, M, 15) batches. Conditions are listed high-threshold-first so the
    # first match wins, mirroring the if/elif ladder in ovr.basketball.ts.
    fudge = np.select(
        [r >= 68, r >= 50, r >= 42, r >= 31],
        [
            np.full_like(r, 8.0),
            4 + (r - 50) * (4 / 18),
            -5 + (r - 42) * (9 / 8),
            -5 - (42 - r) * (5 / 11),
        ],
        default=-10.0,
    )

    # Math.round (round-half-up) == floor(x + 0.5)
    val = np.floor(r + fudge + 0.5)
    val = np.clip(val, 0, 100)
    return val.astype(np.int64)


# --- team ovr ---------------------------------------------------------------

def team_ovr(player_ovrs: Sequence[float], playoffs: bool = False) -> int:
    """Port of team/ovr.basketball.ts (numPlayersOnCourt == 5 branch).

    Sort player ovrs descending, take top 10, pad to length 10 with 0.0, then
    compute a MOV-anchored team rating on an absolute 0-100 scale (50 == even).
    """
    ovrs = sorted((float(o) for o in player_ovrs), reverse=True)[:10]
    while len(ovrs) < 10:
        ovrs.append(0.0)

    if playoffs:
        a, b, k = 0.6388, -0.2245, 157.43
    else:
        a, b, k = 0.3334, -0.1609, 102.98

    predicted_mov = -k
    for i in range(10):
        predicted_mov += a * math.exp(b * i) * ovrs[i]

    raw_ovr = predicted_mov * 50.0 / 15.0 + 50.0
    if playoffs:
        raw_ovr -= 40.0
    return int(math.floor(raw_ovr + 0.5))  # Math.round


def team_ovr_paths(ovr_stack: np.ndarray, playoffs: bool = False) -> np.ndarray:
    """Vectorized :func:`team_ovr` over many simulations and seasons at once.

    ``ovr_stack`` is a float array of shape ``(n_players, n_sims, n_seasons)``
    holding every roster slot's simulated OVR. For each ``(sim, season)`` the
    players are sorted descending, the top 10 taken (padded to 10 with 0.0 just
    like :func:`team_ovr`), and the MOV-anchored formula applied. Returns an int
    array of shape ``(n_sims, n_seasons)``.

    This is the coupling step for team projections: combining draw ``k`` from
    each independently-developing player gives one joint league-state sample, so
    percentiles over the sim axis yield an honest team-OVR distribution.
    """
    ovr_stack = np.asarray(ovr_stack, dtype=np.float64)
    if ovr_stack.ndim != 3:
        raise ValueError("ovr_stack must be (n_players, n_sims, n_seasons)")
    n_players = ovr_stack.shape[0]

    sorted_desc = -np.sort(-ovr_stack, axis=0)  # descending along the player axis
    if n_players >= 10:
        top = sorted_desc[:10]
    else:
        pad = np.zeros((10 - n_players,) + ovr_stack.shape[1:], dtype=np.float64)
        top = np.concatenate([sorted_desc, pad], axis=0)

    if playoffs:
        a, b, k = 0.6388, -0.2245, 157.43
    else:
        a, b, k = 0.3334, -0.1609, 102.98

    weights = a * np.exp(b * np.arange(10))             # (10,)
    predicted_mov = -k + np.tensordot(weights, top, axes=(0, 0))  # (n_sims, n_seasons)
    raw = predicted_mov * 50.0 / 15.0 + 50.0
    if playoffs:
        raw -= 40.0
    return np.floor(raw + 0.5).astype(np.int64)


# ===========================================================================
# Vectorized development
#
# Port of developSeason.basketball.ts. We simulate all n_sims paths together
# with numpy. The correlation structure from the source is reproduced exactly:
#   * base_change is ONE draw per (sim, season), SHARED across all 14 non-hgt
#     ratings -- a good/bad development year lifts/sinks the whole player.
#   * the uniform(0.4, 1.4) multiplier is INDEPENDENT per rating (and per sim,
#     per season).
#   * age_modifier is deterministic per rating EXCEPT endu for age<=23, which is
#     a fresh uniform(0, 9) draw (independent per sim/season).
# ===========================================================================

# Non-hgt ratings, in the order developSeason iterates them (matches RATINGS
# minus hgt, since dicts preserve insertion order and ratingsFormulas keys are a
# permutation of RATINGS\{hgt}; correlation is per-season-shared so exact key
# order within a season does not affect the result, but we keep RATINGS order).
_NON_HGT = [k for k in RATINGS if k != "hgt"]
_NON_HGT_IDX = np.array([_R_INDEX[k] for k in _NON_HGT])  # indices into the 15-wide array


def _shooting_age_mod(age: int) -> float:
    if age <= 27:
        return 0.0
    if age <= 29:
        return 0.5
    if age <= 31:
        return 1.5
    return 2.0


def _iq_age_mod(age: int) -> float:
    if age <= 21:
        return 4.0
    if age <= 23:
        return 3.0
    if age <= 27:
        return 0.0
    if age <= 29:
        return 0.5
    if age <= 31:
        return 1.5
    return 2.0


def _iq_limits(age: int) -> Tuple[float, float]:
    if age >= 24:
        return (-3.0, 9.0)
    return (-3.0, 7.0 + 5.0 * (24 - age))


def _spd_age_mod(age: int) -> float:
    if age <= 27:
        return 0.0
    if age <= 30:
        return -2.0
    if age <= 35:
        return -3.0
    if age <= 40:
        return -4.0
    return -8.0


def _jmp_age_mod(age: int) -> float:
    if age <= 26:
        return 0.0
    if age <= 30:
        return -3.0
    if age <= 35:
        return -4.0
    if age <= 40:
        return -5.0
    return -10.0


def _endu_age_mod_old(age: int) -> float:
    # For age > 23 (the young branch is a uniform draw handled separately).
    if age <= 30:
        return 0.0
    if age <= 35:
        return -2.0
    if age <= 40:
        return -4.0
    return -8.0


def _dnk_age_mod(age: int) -> float:
    if age <= 27:
        return 0.0
    return 0.5


# Per-rating change limits (lo, hi). endu/iq are computed per-age; the rest are
# constant. stre is unbounded.
_INF = float("inf")
_CONST_LIMITS = {
    "stre": (-_INF, _INF),
    "spd": (-12.0, 2.0),
    "jmp": (-12.0, 2.0),
    "endu": (-11.0, 19.0),
    "dnk": (-3.0, 13.0),
    "ins": (-3.0, 13.0),
    "ft": (-3.0, 13.0),
    "fg": (-3.0, 13.0),
    "tp": (-3.0, 13.0),
    "drb": (-2.0, 5.0),
    "pss": (-2.0, 5.0),
    "reb": (-2.0, 5.0),
    # oiq, diq handled per-age via _iq_limits
}


def _age_curve_base(age: int) -> float:
    """Deterministic age-curve value used in calcBaseChange."""
    if age <= 21:
        return 2.0
    if age <= 25:
        return 1.0
    if age <= 27:
        return 0.0
    if age <= 29:
        return -1.0
    if age <= 31:
        return -2.0
    if age <= 34:
        return -3.0
    if age <= 40:
        return -4.0
    if age <= 43:
        return -5.0
    return -6.0


def develop_paths(
    start_ratings: Mapping[str, float],
    start_age: int,
    n_years: int,
    n_sims: int,
    coaching_level: float = DEFAULT_COACHING_LEVEL,
    seed: int = 0,
) -> Dict[str, np.ndarray]:
    """Vectorized Monte Carlo development.

    start_ratings: dict of the 15 keys (the CURRENT, already-known ratings).
    Advances the player one season at a time for n_years, passing the INCREMENTED
    age each season (developSeason is called for ageTemp = start_age+1 ... per
    develop.ts).

    Returns:
      {"ratings": ndarray (n_sims, n_years+1, 15),  # axis1 idx 0 == current
       "ovr":     ndarray (n_sims, n_years+1)}      # player_ovr per (sim, year)
    """
    rng = np.random.default_rng(seed)
    ce = coaching_effect(coaching_level)

    # Current ratings as a float vector in RATINGS order.
    base = np.array([float(start_ratings[k]) for k in RATINGS], dtype=np.float64)

    # ratings[sim, year, 15]
    ratings = np.empty((n_sims, n_years + 1, 15), dtype=np.float64)
    ratings[:, 0, :] = base  # index 0 == undeveloped current

    cur = np.tile(base, (n_sims, 1))  # (n_sims, 15) working state

    for t in range(1, n_years + 1):
        age = start_age + t  # the incremented age passed to developSeason

        # --- STEP 1: height bump (young only) ---
        if age <= 21:
            hr = rng.random(n_sims)  # one uniform per sim
            hgt = cur[:, _HGT]
            if age <= 20:
                bump1 = (hr > 0.99) & (hgt <= 99)
                hgt = hgt + bump1.astype(np.float64)
            bump2 = (hr > 0.999) & (hgt <= 99)
            hgt = hgt + bump2.astype(np.float64)
            cur[:, _HGT] = hgt

        # --- STEP 2: base_change (one shared value per sim/season) ---
        age_curve = _age_curve_base(age)
        if age <= 23:
            noise = np.clip(rng.normal(0.0, 5.0, n_sims), -4.0, 20.0)
        elif age <= 25:
            noise = np.clip(rng.normal(0.0, 5.0, n_sims), -4.0, 10.0)
        else:
            noise = np.clip(rng.normal(0.0, 3.0, n_sims), -2.0, 4.0)
        base_change = age_curve + noise  # (n_sims,)
        # Coaching: val *= 1 + sign(val) * coaching_effect
        sign = np.where(base_change > 0, 1.0, -1.0)
        base_change = base_change * (1.0 + sign * ce)

        # --- STEP 3: per-rating deltas for the 14 non-hgt ratings ---
        # Independent uniform(0.4, 1.4) per (sim, rating).
        umult = rng.uniform(0.4, 1.4, (n_sims, len(_NON_HGT)))

        # Build age_modifier and limits per non-hgt rating (in _NON_HGT order).
        age_mods = np.empty((n_sims, len(_NON_HGT)), dtype=np.float64)
        lo = np.empty(len(_NON_HGT), dtype=np.float64)
        hi = np.empty(len(_NON_HGT), dtype=np.float64)

        for j, key in enumerate(_NON_HGT):
            if key in ("ins", "ft", "fg", "tp", "drb", "pss", "reb"):
                age_mods[:, j] = _shooting_age_mod(age)
            elif key in ("oiq", "diq"):
                age_mods[:, j] = _iq_age_mod(age)
            elif key == "spd":
                age_mods[:, j] = _spd_age_mod(age)
            elif key == "jmp":
                age_mods[:, j] = _jmp_age_mod(age)
            elif key == "dnk":
                age_mods[:, j] = _dnk_age_mod(age)
            elif key == "stre":
                age_mods[:, j] = 0.0
            elif key == "endu":
                if age <= 23:
                    # Fresh uniform(0,9) per sim/season -- independent draw.
                    age_mods[:, j] = rng.uniform(0.0, 9.0, n_sims)
                else:
                    age_mods[:, j] = _endu_age_mod_old(age)
            else:
                raise RuntimeError("unhandled rating " + key)

            if key in ("oiq", "diq"):
                klo, khi = _iq_limits(age)
            else:
                klo, khi = _CONST_LIMITS[key]
            lo[j] = klo
            hi[j] = khi

        # delta = bound((base_change + age_mod) * umult, lo, hi)
        delta = (base_change[:, None] + age_mods) * umult
        delta = np.clip(delta, lo, hi)  # broadcasts (n_sims,14) against (14,)

        # Apply to the non-hgt ratings: clamp [0,100] then floor (limit_rating).
        vals = cur[:, _NON_HGT_IDX] + delta
        vals = np.clip(vals, 0.0, 100.0)
        vals = np.floor(vals)
        cur[:, _NON_HGT_IDX] = vals

        ratings[:, t, :] = cur

    ovr = player_ovr_vec(ratings)  # (n_sims, n_years+1)
    return {"ratings": ratings, "ovr": ovr}


# ===========================================================================
# Friendly wrapper + percentile helpers
# ===========================================================================

def percentiles(
    arr_over_sims: np.ndarray,
    pcts: Sequence[int] = (10, 25, 50, 75, 90),
) -> Dict[str, List[float]]:
    """arr shape (n_sims, n_years+1) -> {"p10":[...], "p25":[...], ...}.

    Percentiles are computed over the sims axis (axis 0) for each year.
    """
    arr = np.asarray(arr_over_sims, dtype=np.float64)
    out = {}
    for p in pcts:
        vals = np.percentile(arr, p, axis=0)
        out["p" + str(p)] = [float(v) for v in np.atleast_1d(vals)]
    return out


def simulate_player(
    ratings: Mapping[str, float],
    start_age: int,
    start_season: int,
    seasons_ahead: int = 6,
    n_sims: int = 1000,
    coaching_level: float = DEFAULT_COACHING_LEVEL,
    seed: int = 0,
) -> Dict[str, object]:
    """Friendly wrapper around develop_paths.

    Returns season/age axes, OVR + per-subrating percentile bands, and the
    monteCarloPot-style 75th-percentile peak OVR through age 29.
    """
    paths = develop_paths(
        ratings, start_age, seasons_ahead, n_sims,
        coaching_level=coaching_level, seed=seed,
    )
    rat = paths["ratings"]  # (n_sims, seasons_ahead+1, 15)
    ovr = paths["ovr"]      # (n_sims, seasons_ahead+1)

    seasons = [start_season + i for i in range(seasons_ahead + 1)]
    ages = [start_age + i for i in range(seasons_ahead + 1)]

    ovr_bands = percentiles(ovr)

    sub_bands = {}
    for i, key in enumerate(RATINGS):
        sub_bands[key] = percentiles(rat[:, :, i])

    return {
        "seasons": seasons,
        "ages": ages,
        "ovr": ovr_bands,
        "subratings": sub_bands,
        # monteCarloPot always evaluates potential at the DEFAULT coaching level
        # (develop.ts passes DEFAULT_LEVEL regardless of the player's team), so
        # pot is a team-agnostic ceiling. n_sims is forwarded so the pot estimate
        # uses the same sample size as the bands above.
        "pot_p75_peak": _pot_p75_peak(
            ratings, start_age, seed=seed, n_sims=n_sims,
        ),
    }


def _pot_p75_peak(
    ratings: Mapping[str, float],
    age: int,
    seed: int = 0,
    n_sims: int = 1000,
) -> int:
    """Port of monteCarloPot (develop.ts).

    Simulate aging up to (but not including) 30, tracking the running max OVR
    starting from the current (pre-development) OVR, then return the 75th
    percentile via the engine's index: sorted[floor(0.75 * n_sims)].

    Coaching is fixed at DEFAULT_COACHING_LEVEL to mirror the engine, which
    always computes potential at the default level (so it is a team-agnostic
    ceiling, not a function of the player's current team).
    """
    cur_ovr = player_ovr(ratings)
    if age >= 29:
        return cur_ovr

    # Develop from age+1 up to 29 inclusive: that's (30 - (age+1)) == 29-age years.
    n_years = 29 - age
    paths = develop_paths(
        ratings, age, n_years, n_sims,
        coaching_level=DEFAULT_COACHING_LEVEL, seed=seed,
    )
    ovr = paths["ovr"]  # (n_sims, n_years+1); column 0 is the current ovr

    # Running peak across all developed years (incl. the starting ovr column).
    max_ovr = ovr.max(axis=1)  # (n_sims,)
    # The starting column equals cur_ovr for every sim, so max already >= cur_ovr.

    sorted_max = np.sort(max_ovr)
    idx = int(math.floor(0.75 * n_sims))
    return int(sorted_max[idx])


# ===========================================================================
# Team projection (coupled simulation over a roster)
# ===========================================================================

def player_ovr_paths(
    ratings: Mapping[str, float],
    start_age: int,
    seasons_ahead: int = 6,
    n_sims: int = 1000,
    coaching_level: float = DEFAULT_COACHING_LEVEL,
    seed: int = 0,
) -> np.ndarray:
    """Per-sim OVR paths for one player: shape (n_sims, seasons_ahead+1).

    Thin wrapper over :func:`develop_paths` returning just the OVR array. Use the
    same per-player seed as the player page so a team's projection is consistent
    with the player's own displayed projection.
    """
    paths = develop_paths(
        ratings, start_age, seasons_ahead, n_sims,
        coaching_level=coaching_level, seed=seed,
    )
    return paths["ovr"]


def simulate_team(
    player_ovr_arrays: Sequence[np.ndarray],
    contract_exps: Sequence[int],
    seasons: Sequence[int],
    replacement_ovr: float = 40.0,
    pcts: Sequence[int] = (10, 25, 50, 75, 90),
    playoffs: bool = False,
) -> Optional[Dict[str, object]]:
    """Coupled team-OVR projection under two roster scenarios.

    ``player_ovr_arrays``: one (n_sims, n_seasons) OVR array per current roster
    player (from :func:`player_ovr_paths`, aligned so column 0 == current season).
    ``contract_exps``: each player's last contracted season (same order).
    ``seasons``: the season ints, seasons[0] == current.

    Two scenarios are returned as percentile bands per season:
      * ``core`` ("guaranteed core"): once a player's contract lapses, that roster
        slot is filled at ``replacement_ovr`` (the floor if the team re-signs no
        one and replaces departures with replacement-level talent).
      * ``proj`` ("projected roster"): every current player is retained and ages
        forward (the continuity scenario).
    The gap between the two is the value of the team's expiring talent above
    replacement. Both pad to >= 10 roster slots with ``replacement_ovr`` so a thin
    roster is filled rather than crashing the MOV-calibrated formula to nonsense.
    """
    if not player_ovr_arrays:
        return None
    stack = np.stack([np.asarray(a, dtype=np.float64) for a in player_ovr_arrays])
    n_players, n_sims, n_seasons = stack.shape
    seasons_arr = np.asarray(list(seasons)[:n_seasons], dtype=np.int64)
    exps = np.asarray([int(e) for e in contract_exps], dtype=np.int64)

    beyond = seasons_arr[None, :] > exps[:, None]                      # (P, T)
    core_stack = np.where(beyond[:, None, :], float(replacement_ovr), stack)
    proj_stack = stack

    def _pad(st: np.ndarray) -> np.ndarray:
        if st.shape[0] >= 10:
            return st
        fill = np.full((10 - st.shape[0], n_sims, n_seasons), float(replacement_ovr))
        return np.concatenate([st, fill], axis=0)

    core_team = team_ovr_paths(_pad(core_stack), playoffs)             # (n_sims, T)
    proj_team = team_ovr_paths(_pad(proj_stack), playoffs)

    def _bands(team: np.ndarray) -> Dict[str, list]:
        out: Dict[str, list] = {}
        for p in pcts:
            out["p%d" % p] = [float(np.percentile(team[:, t], p)) for t in range(n_seasons)]
        return out

    core_counts = [int(np.sum(~beyond[:, t])) for t in range(n_seasons)]
    current = int(round(float(np.median(proj_team[:, 0]))))
    return {
        "core": _bands(core_team),
        "proj": _bands(proj_team),
        "current": current,
        "core_counts": core_counts,
        "n_players": n_players,
    }


def projected_win_pct(team_ovrs: Mapping[object, float], sigma: float = 12.0) -> Dict[object, float]:
    """Pairwise round-robin expected win% from a single season's team OVRs.

    For each pair, the expected point margin is ``(ovr_a - ovr_b) * 0.3`` -- the
    inverse of team_ovr's MOV->rating scaling (50 == even, slope 50/15). The win
    probability is ``Phi(margin / sigma)`` with ``sigma`` ~ the game-to-game
    margin SD (~12). A team's projected win% is the mean of its win probabilities
    against every other team (an equal-strength-of-schedule round robin).

    This is a RELATIVE model: it depends only on OVR *differences*, so it is robust
    to a league whose absolute team-OVR scale runs hot. Returns {key: win_pct}.
    """
    keys = list(team_ovrs.keys())
    if len(keys) < 2:
        return {k: 0.5 for k in keys}
    inv = 1.0 / (sigma * math.sqrt(2.0))

    def win_prob(margin: float) -> float:
        return 0.5 * (1.0 + math.erf(margin * inv))

    out: Dict[object, float] = {}
    for a in keys:
        probs = [win_prob((float(team_ovrs[a]) - float(team_ovrs[b])) * 0.3)
                 for b in keys if b != a]
        out[a] = sum(probs) / len(probs)
    return out


# ===========================================================================
# Self-test / demo
# ===========================================================================

if __name__ == "__main__":
    import json
    import os

    repo = "/Users/andrewpark/Desktop/Code/chronicaria.github.io"
    export_path = os.path.join(repo, "league-data", "day20.json")

    with open(export_path) as f:
        data = json.load(f)

    ga = data.get("gameAttributes", {})
    season = ga.get("season") if isinstance(ga, dict) else None
    players = data["players"]

    # (a) OVR parity check over every rating row with all 15 keys + 'ovr'.
    mismatches = 0
    checked = 0
    for p in players:
        for rr in p.get("ratings", []):
            if "ovr" not in rr:
                continue
            if not all(k in rr for k in RATINGS):
                continue
            checked += 1
            if player_ovr(rr) != rr["ovr"]:
                mismatches += 1
    print("OVR parity: checked={} mismatches={}".format(checked, mismatches))

    # Vectorized parity spot-check (must agree with scalar path).
    sample = []
    for p in players:
        rr = p["ratings"][-1]
        if all(k in rr for k in RATINGS):
            sample.append([rr[k] for k in RATINGS])
        if len(sample) >= 50:
            break
    sample_arr = np.array(sample, dtype=np.float64)
    vec = player_ovr_vec(sample_arr)
    scal = np.array([player_ovr(dict(zip(RATINGS, row))) for row in sample])
    print("Vec vs scalar mismatches:", int(np.sum(vec != scal)))

    # (b) Determinism check.
    demo_r = {k: 50 for k in RATINGS}
    d1 = develop_paths(demo_r, 22, 6, 500, seed=12345)
    d2 = develop_paths(demo_r, 22, 6, 500, seed=12345)
    det_ok = bool(np.array_equal(d1["ovr"], d2["ovr"])) and bool(
        np.array_equal(d1["ratings"], d2["ratings"])
    )
    print("Determinism (same seed identical):", det_ok)

    # (c) Sanity projection: one young player and one old player.
    cur_season = season if season is not None else 2029

    def _age_of(p, s):
        return s - p["born"]["year"]

    young = None
    old = None
    for p in players:
        rr = p["ratings"][-1]
        if not all(k in rr for k in RATINGS):
            continue
        a = _age_of(p, cur_season)
        if young is None and a <= 21 and a >= 18:
            young = (p, rr, a)
        if old is None and a >= 33:
            old = (p, rr, a)
        if young and old:
            break

    for label, tup in (("YOUNG", young), ("OLD", old)):
        if tup is None:
            print(label, "-> none found")
            continue
        p, rr, a = tup
        pid = p.get("pid", 0)
        sim = simulate_player(
            rr, a, cur_season, seasons_ahead=6, n_sims=1000,
            seed=7 * 100003 + pid,
        )
        name = p.get("firstName", "?") + " " + p.get("lastName", "?")
        print("\n{} {} (age {}), start ovr {}".format(label, name, a, rr["ovr"]))
        print("  ages:", sim["ages"])
        print("  p10 :", [int(round(x)) for x in sim["ovr"]["p10"]])
        print("  p50 :", [int(round(x)) for x in sim["ovr"]["p50"]])
        print("  p90 :", [int(round(x)) for x in sim["ovr"]["p90"]])
        print("  pot_p75_peak:", sim["pot_p75_peak"])
