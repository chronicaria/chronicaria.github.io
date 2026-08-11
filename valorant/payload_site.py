"""Emit ``payload/site.json`` and the four ``payload/player/<short>.json`` files.

Reads the MWPA round-player artifact and the box-score database, and writes the front-page and
per-player halves of the payload contract in ``CONTRACT.md``.  Nothing here re-derives credit:
``mwpa_round_players.csv`` is one row per (match, round, player) with the centered credit, the
round's leverage and their product already on it.

Every interval on the site comes from one shared match-level resample.  ``mwpa.Bootstrapper`` is
imported rather than reimplemented so that the headline, a component, a two-round weapon cell and a
synergy pair are all drawn from the same 100,000 replicates at seed 20260726 and are therefore
comparable to each other and to the published RWPA intervals.

The two gate values that changed for this site -- ranking on, rate suppression off -- live in
``meta.gate`` and their reasons in ``meta.cav``.  They are data, not code: nothing in the view
decides them.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import date
from inspect import signature
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

LAB = Path("/Users/andrewpark/Desktop/Rome/Sports/Esports/Valorant/valorant-impact-lab")
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from valorant_impact.match_leverage import match_win_probability, round_leverage  # noqa: E402
from valorant_impact.mwpa import BUY_BANDS, Bootstrapper  # noqa: E402

# The per-round win probability the match model assumes for every future round.  Read off the
# model rather than written down here, because the caveat about the boundary seam is only true
# for whatever value that model actually uses.
NEUTRAL_ROUND_P = float(signature(match_win_probability).parameters["p"].default)

# The work set used to live in a session scratchdir under /private/tmp, which is a directory the
# operating system is entitled to delete: the site's own build depended on temp space belonging to
# a session that had already ended. It lives beside the release it was cut from now.
WORK = LAB / "data" / "quad_work_2026-08-04"
DATABASE = LAB / "data" / "valorant_matches_v16.sqlite3"
RELEASE = "model_suite_release_2026-08-02_v15"

BOOTSTRAP = 100_000
SEED = 20260726
CONFIDENCE = 0.95
# Pinned, and it moves when the corpus does: this is the act's own mean over the 1,713 rounds of
# the 83-match corpus, where the 68-match corpus read 0.16427272872711246. The guard below is the
# point of the literal — a ledger whose mean leverage is not this one is not the ledger this
# payload was written for, and the run stops rather than emitting numbers off the wrong corpus.
MEAN_LEVERAGE = 0.16000625403664115

RATE_FLOOR_ROUNDS = 0
THIN_ROUNDS = 20
WEAPON_MIN_ROUNDS = 10

# The rounds needed for a leverage-weighted rate to exclude zero, and for a side contrast to
# resolve.  Both are measurements from the research, not properties of this payload; they are here
# so the caveats can name them next to the exposure the payload actually carries.
ROUNDS_TO_EXCLUDE_ZERO = 726
ROUNDS_FOR_SIDE_SPLIT = 14_000

# THE LADDER.  ``player_matches.tier`` is per match, so each of the four has a trajectory across
# the act rather than a rank.  Two things about it are traps and both are handled here rather than
# in the view:
#
#   1. Riot's own enum puts ``Unrated`` at id 0 on the same integer ladder that has Iron 2 at 4.
#      Plotting the id therefore drops "no rank has been issued yet" a division below Iron 1 and
#      opens a player page with a six-rung jump that is an artefact and not an event.  The ladder
#      emitted in ``meta.gate.tier_order`` drops id 0 for that reason, and the placement window is
#      carried as its own state.
#   2. ``Unrated`` is the name of a QUEUE on every reference site in this space, sitting beside
#      Competitive and Deathmatch.  All 68 act matches are Competitive.  The string never reaches
#      the payload, let alone a page: a match played before a rank was issued carries ``null``.
UNRATED = "Unrated"
# A flat path must not fill its panel: rule 5 says no cell's rendering is a function of another
# row's value, and a one-division axis would make Trzzcko's three flat matches look like a range.
TIER_AXIS_MIN_SPAN = 3
# THE ARTWORK, AND THE ONE RULE ABOUT IT: three families ship and each is emitted as an explicit
# name -> file map, so the view resolves an image by LOOKUP and never by string surgery.  A name
# with no file is simply absent from the map, the view renders the word alone, and there is no
# path by which this site can emit a broken image.  One slug rule for all three; one audit for all
# three; and the folder list here is what ``build.py``'s declared-families guard checks the disk
# against, so a fourth folder appearing on disk stops the build instead of shipping unexamined.
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ASSET_FAMILIES = (
    # (family, folder, what the map is keyed by, the job, the source line)
    ("agent", "agent", "the agent name in the round frame",
     "identification beside a word that is always rendered"),
    ("weapon", "weapon", "the weapon name in the round frame",
     "one distinct silhouette per breakdown row, on a theme-invariant plate"),
    ("rank", "rank", "the division name on the ladder",
     "recognition beside the division word, which is what encodes"),
)
ASSET_SOURCE = "valorant-api.com, serving Riot Games' own artwork"

FOCAL = (
    ("ab8bf38e-c2c4-5408-9a96-90ee3eb01af9", "MartinLutherKing#racis", "martin"),
    ("7b17dc93-bba8-50f3-ba4f-7e753d901a65", "SN0RLAX#143", "snorlax"),
    ("82d91329-7a9d-5d30-ac3f-5cd2e4764d15", "TheMarias#Bunny", "themarias"),
    ("bafecb36-4e90-5f84-adc7-04d6acb22dfa", "Trzzcko#SFang", "trzzcko"),
)

CREDIT_TYPES = ("kill_credit", "death_debit", "plant", "defuse", "alive_clock")
# THE TWO THAT NEARLY CANCEL, AND THE ROW THEY BECOME.  Kill credit runs +1.845 per match against
# a death debit of -1.828 on the same player: two rows an order of magnitude longer than the other
# four, pointing opposite ways, that between them force a component axis so wide that plant,
# defuse and the clock are invisible on it.  They are also the same event seen twice -- a duel
# resolves, somebody is paid and somebody is debited -- so the sum is a quantity and not a
# convenience.  It is bootstrapped as its own column rather than added out of two intervals,
# because the two are strongly negatively correlated and their interval widths do not add.
DUEL_PARTS = ("kill_credit", "death_debit")
DUEL_CREDIT = "duel_credit"
# The five rows the rail draws, in the order it draws them.
COMPONENT_ORDER = (DUEL_CREDIT,) + tuple(
    credit for credit in CREDIT_TYPES if credit not in DUEL_PARTS) + ("lobby_adjustment",)

# THE FREE PISTOL.  Everybody starts a pistol round holding it, so a Classic count measures how
# many pistol rounds the act contained rather than anything about the player.  It is excluded from
# the card's most-used guns and the exclusion is published in `meta.gate` so the view reads the
# name rather than typing it.
FREE_PISTOL = "Classic"
# How many agents and guns the card names.  A player with fewer shows fewer; nothing is padded.
CARD_TOP_N = 3

SIDES = ("attack", "defense")
BUY_ORDER = tuple(name for name, _, _ in BUY_BANDS)

REQUIRED_COLUMNS = (
    "match_id", "round_id", "puuid", "player", "team", "agent", "is_focal", "rwpa",
    "rwpa_centered", "map", "started_at", "round_number", "attack_team", "winning_team",
    "side", "leverage", "mwpa", "team_loadout", "buy_class", "round_won", "weapon",
) + tuple("mwpa_" + credit for credit in CREDIT_TYPES)


# --------------------------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------------------------

def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("round-player artifact is missing columns: %s" % ", ".join(missing))
    frame["is_focal"] = frame["is_focal"].astype(bool)

    residual = frame.groupby(["match_id", "round_id"])["rwpa_centered"].sum().abs().max()
    if residual > 1e-9:
        raise ValueError("centered credit does not sum to zero within a round: %s" % residual)
    if abs(float(frame["leverage"].mean()) - MEAN_LEVERAGE) > 1e-12:
        raise ValueError(
            "mean leverage %r does not match the contract value %r"
            % (float(frame["leverage"].mean()), MEAN_LEVERAGE)
        )
    found = set(frame.loc[frame["is_focal"], "puuid"])
    absent = [name for puuid, name, _ in FOCAL if puuid not in found]
    if absent:
        raise ValueError("focal players absent from the artifact: %s" % ", ".join(absent))
    return frame


def load_match_context(database: Path, match_ids: Sequence[str]) -> Dict[str, Any]:
    """Match metadata, final score and the surrender check, from the box-score database."""
    placeholders = ",".join("?" * len(match_ids))
    connection = sqlite3.connect(str(database))
    try:
        matches = pd.read_sql_query(
            "select match_id, started_at, map, season_short, round_count from matches "
            "where match_id in (%s)" % placeholders, connection, params=list(match_ids))
        teams = pd.read_sql_query(
            "select match_id, team_id, rounds_won, rounds_lost, won from team_results "
            "where match_id in (%s)" % placeholders, connection, params=list(match_ids))
        surrendered = pd.read_sql_query(
            "select count(*) as n from rounds where result = 'Surrendered' and match_id in (%s)"
            % placeholders, connection, params=list(match_ids))
        # THE BOX SCORE, for the trading card and for nothing else.  Kills, deaths and assists
        # are not in the ledger -- the ledger holds credit, which is a different thing from a
        # kill -- so they come from the platform's own per-match record.  One row per
        # (match, player); the card averages over the act matches the player actually appears in.
        box = pd.read_sql_query(
            "select match_id, puuid, agent, kills, deaths, assists from player_matches "
            "where match_id in (%s)" % placeholders, connection, params=list(match_ids))
    finally:
        connection.close()

    if len(matches) != len(match_ids):
        raise ValueError("%d of %d matches missing from the database"
                         % (len(match_ids) - len(matches), len(match_ids)))
    # SURRENDERED ROUNDS ARE COUNTED, NOT REFUSED, and the distinction is between a round and a
    # match.  This gate used to drop any match containing one, on the argument that leverage is
    # priced from the race to 13 and a surrender ends that race early.  That argument is about the
    # rounds nobody played: a surrendered round is AWARDED, with no events and no kills, and it is
    # already outside the scored slice because the core marks it `behavior_eligible = False`.  The
    # rounds before the surrender were played under a genuine race, against a score the players
    # could not know would be conceded, so their leverage at the time was real and dropping them
    # threw away the only data the match actually contains.  The box score agrees: `team_results`
    # records the played scoreline (6-3 on the one such match in this act), not an inflated one,
    # and `match_index` reconciles the scored round count against it.  What is kept is the count,
    # because a number nothing renders is a fact nobody can check.
    surrendered_rounds = int(surrendered["n"].iloc[0])
    seasons = sorted(matches["season_short"].dropna().unique().tolist())
    if len(seasons) != 1:
        raise ValueError("expected a single act, found %s" % seasons)
    return {
        "act": seasons[0],
        "matches": matches.set_index("match_id"),
        "teams": teams.set_index(["match_id", "team_id"]),
        "box": box,
        "surrendered_rounds": surrendered_rounds,
    }


# --------------------------------------------------------------------------------------------
# the ladder
# --------------------------------------------------------------------------------------------

def load_tier_ladder(database: Path) -> List[Dict[str, Any]]:
    """Riot's division ladder, read off the corpus instead of written down here.

    ``player_matches.tier`` is a name with no order on it.  The order is in the raw box-score
    payload, where each player carries ``{"id": 7, "name": "Bronze 2"}``, so the ladder is
    every distinct pair the corpus has ever seen, sorted by id.  Reading it rather than
    declaring it means a future act that introduces a division gets it for free, and it means
    the site cannot disagree with the platform about what beats what.

    ``Unrated`` (id 0) is dropped: it is not a division, and leaving it on the ladder is the
    enum artefact this whole block exists to refuse.
    """
    connection = sqlite3.connect(str(database))
    try:
        seen: Dict[int, str] = {}
        for (blob,) in connection.execute("select payload_json from raw_matches"):
            for player in json.loads(blob).get("players", []):
                tier = player.get("tier") or {}
                if tier.get("name") and tier.get("id") is not None:
                    seen.setdefault(int(tier["id"]), str(tier["name"]))
    finally:
        connection.close()
    if not seen:
        raise ValueError("no tier enum in raw_matches: the ladder cannot be read")
    unrated = [name for tier_id, name in seen.items() if tier_id == 0]
    if unrated and unrated[0] != UNRATED:
        raise ValueError("tier id 0 is %r, not %r" % (unrated[0], UNRATED))
    return [{"id": tier_id, "name": seen[tier_id]} for tier_id in sorted(seen) if tier_id]


def load_tiers(database: Path, match_ids: Sequence[str]) -> pd.DataFrame:
    """The tier every player carried in every act match, with its start time to order by."""
    placeholders = ",".join("?" * len(match_ids))
    connection = sqlite3.connect(str(database))
    try:
        frame = pd.read_sql_query(
            "select pm.match_id, pm.puuid, pm.tier, m.started_at from player_matches pm "
            "join matches m using (match_id) where pm.match_id in (%s)" % placeholders,
            connection, params=list(match_ids))
    finally:
        connection.close()
    if frame["tier"].isna().any():
        raise ValueError("%d act player-matches carry no tier at all"
                         % int(frame["tier"].isna().sum()))
    return frame.sort_values(["started_at", "match_id"])


def placement_window(tiers: pd.DataFrame) -> Dict[str, Any]:
    """How long the unranked prefix lasts, measured on the act rather than assumed.

    The claim the site makes on every player page is that an ``Unrated`` match means *no rank had
    been issued yet* -- which is only true if it is always a prefix.  It is: verified here, and the
    build refuses to emit a payload where it is not.
    """
    prefix = 0
    holders = 0
    windows = Counter()
    for _, part in tiers.groupby("puuid", sort=False):
        names = list(part["tier"])
        if UNRATED not in names:
            continue
        holders += 1
        leading = 0
        while leading < len(names) and names[leading] == UNRATED:
            leading += 1
        if names.count(UNRATED) == leading:
            prefix += 1
        # Only a player who plays past the window measures it.  128 of the 132 holders in this
        # act played exactly one act match, so their "window" is a censored 1 and carries nothing.
        if leading < len(names):
            windows[leading] += 1
    if prefix != holders:
        raise ValueError("%d of %d act players carry Unrated somewhere other than as a prefix"
                         % (holders - prefix, holders))
    if len(windows) != 1:
        raise ValueError("the placement window is not one length: %s" % sorted(windows.items()))
    matches = next(iter(windows))
    return {
        "matches": int(matches),
        "holders": int(holders),
        "completed": int(sum(windows.values())),
        "share_of_act": float((tiers["tier"] == UNRATED).mean()),
        "act_player_matches": int(len(tiers)),
    }


def rank_track(
    matches: Sequence[Dict[str, Any]],
    tier_by_key: Dict[Any, str],
    ordinal_of: Dict[str, int],
    puuid: str,
) -> List[Dict[str, Any]]:
    """One row per match in the player's own order: the division held, or the placement state.

    ``ordinal`` is a position on ``meta.gate.tier_order``, one-based, and is the only number the
    figure may use for a y value.  ``state`` is ``placement`` exactly when no rank had been issued
    yet, and then ``tier`` and ``ordinal`` are both null -- never a zero, never an em dash, and
    never the string the platform uses for the queue.
    """
    track = []
    for i, entry in enumerate(matches):
        name = tier_by_key.get((entry["match_id"], puuid))
        if name is None:
            raise ValueError("no tier row for %s in %s" % (puuid, entry["match_id"]))
        ranked = name != UNRATED
        if ranked and name not in ordinal_of:
            raise ValueError("tier %r is not on the ladder" % name)
        track.append({
            "i": i,
            "match_id": entry["match_id"],
            "started_at": entry["started_at"],
            "tier": name if ranked else None,
            "ordinal": ordinal_of[name] if ranked else None,
            "state": "ranked" if ranked else "placement",
        })
    return track


def ladder_summary(track: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """First and last division, the placement count, and how often the ladder actually moved.

    Steps are counted between consecutive *ranked* matches, so the one thing about these four
    people that measurably moved is a count and not an impression.
    """
    ranked = [row for row in track if row["state"] == "ranked"]
    up = down = 0
    for before, after in zip(ranked, ranked[1:]):
        if after["ordinal"] > before["ordinal"]:
            up += 1
        elif after["ordinal"] < before["ordinal"]:
            down += 1
    return {
        "first": ranked[0]["tier"] if ranked else None,
        "last": ranked[-1]["tier"] if ranked else None,
        "low": min(ranked, key=lambda row: row["ordinal"])["tier"] if ranked else None,
        "high": max(ranked, key=lambda row: row["ordinal"])["tier"] if ranked else None,
        "placement": sum(1 for row in track if row["state"] == "placement"),
        "ranked": len(ranked),
        "steps_up": up,
        "steps_down": down,
    }


def tier_against_mwpa(
    frame: pd.DataFrame,
    tiers: pd.DataFrame,
    ordinal_of: Dict[str, int],
    minimum_ranked: int = 5,
) -> Dict[str, Any]:
    """Does the ladder agree with the rating?  Measured, so the caveat can quote it.

    For every focal player-match with at least ``minimum_ranked`` ranked others in the lobby:
    the lobby's mean division ordinal against that match's MWPA, against the lobby adjustment it
    earned, and against that adjustment as a rate.  The ladder moves on results; MWPA is centered
    so that a lobby's surplus cannot be banked.  If the two agreed, this number would say so.
    """
    ordinals = tiers.assign(ordinal=tiers["tier"].map(ordinal_of))
    by_match: Dict[str, List[Any]] = {}
    for match_id, part in ordinals.groupby("match_id", sort=False):
        by_match[match_id] = list(zip(part["puuid"], part["ordinal"]))

    focal = frame.loc[frame["is_focal"]].copy()
    focal["lobby_adjustment"] = focal["mwpa"] - sum(
        focal["mwpa_" + credit] for credit in CREDIT_TYPES)
    grouped = focal.groupby(["match_id", "puuid"]).agg(
        mwpa=("mwpa", "sum"), adjustment=("lobby_adjustment", "sum"), rounds=("mwpa", "size"))

    lobby, mwpa, adjustment, adjustment_rate = [], [], [], []
    for (match_id, puuid), row in grouped.iterrows():
        others = [o for p, o in by_match.get(match_id, []) if p != puuid and o == o]
        if len(others) < minimum_ranked:
            continue
        lobby.append(float(np.mean(others)))
        mwpa.append(float(row["mwpa"]))
        adjustment.append(float(row["adjustment"]))
        adjustment_rate.append(100.0 * float(row["adjustment"]) / float(row["rounds"]))

    def r(values: Sequence[float]) -> float:
        return round(float(np.corrcoef(lobby, values)[0, 1]), 3)

    spreads = [max(o for _, o in rows) - min(o for _, o in rows)
               for rows in (([(p, o) for p, o in v if o == o]) for v in by_match.values())
               if len(rows) >= 2]
    return {
        "n": len(lobby),
        "minimum_ranked": minimum_ranked,
        "r_mwpa": r(mwpa),
        "r_lobby_adjustment": r(adjustment),
        "r_lobby_adjustment_rate": r(adjustment_rate),
        "lobby_spread_median": float(np.median(spreads)),
        "lobby_spread_max": int(max(spreads)),
    }


def build_ladder(
    frame: pd.DataFrame,
    index: pd.DataFrame,
    database: Path,
    match_ids: Sequence[str],
    asset_dir: Path,
) -> Dict[str, Any]:
    """Everything the ladder half of the payload needs, measured once and shared.

    ``tracks`` is per focal player, in that player's own match order, which is the x axis the
    trajectory figure and the per-match ``tier`` column both read.
    """
    order = load_tier_ladder(database)
    ordinal_of = {entry["name"]: i + 1 for i, entry in enumerate(order)}
    tiers = load_tiers(database, match_ids)
    tier_by_key = dict(zip(zip(tiers["match_id"], tiers["puuid"]), tiers["tier"]))

    tracks = {}
    for puuid, _, short in FOCAL:
        played = set(frame.loc[frame["puuid"] == puuid, "match_id"])
        ordered = [{"match_id": row["match_id"], "started_at": row["started_at"]}
                   for _, row in index.iterrows() if row["match_id"] in played]
        tracks[short] = rank_track(ordered, tier_by_key, ordinal_of, puuid)

    return {
        "order": order,
        "ordinal_of": ordinal_of,
        "tier_by_key": tier_by_key,
        "tracks": tracks,
        "summaries": {short: ladder_summary(track) for short, track in tracks.items()},
        "placement": placement_window(tiers),
        "correlation": tier_against_mwpa(frame, tiers, ordinal_of),
        "assets": all_assets(frame, tiers, asset_dir),
    }


def png_size(path: Path) -> List[int]:
    """A PNG's intrinsic pixel size, read from the IHDR chunk of the file itself.

    The view needs a width and a height on every element so nothing reflows on load, and two of
    the three families are not square: Riot's weapon art is 96 wide at 17 to 73 tall.  A view that
    guessed would either distort the art or shift the row, and a constant written down here would
    be a second copy of a fact the file already carries.  So the file is the source, once.
    """
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("%s is not a PNG with an IHDR first" % path.name)
    return [int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")]


def asset_family(names: Sequence[str], folder: Path, prefix: str, job: str) -> Dict[str, Any]:
    """One family's name -> file map, its intrinsic sizes, and its own audit.

    ``files`` is the whole interface: the view looks a name up and renders the word alone when it
    is not there.  ``px`` is keyed the same way and carries each file's real intrinsic size, so the
    view can compute a contain-fit without opening a file or assuming a shape.
    """
    def slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    on_disk = sorted(path.name for path in folder.glob("*.png")) if folder.is_dir() else []
    files, px, missing = {}, {}, []
    for name in sorted(names):
        filename = "%s.png" % slug(name)
        if filename in on_disk:
            files[name] = prefix + filename
            px[name] = png_size(folder / filename)
        else:
            missing.append(name)
    return {
        "dir": prefix,
        "job": job,
        "files": files,
        "px": px,
        "missing": missing,
        "unused": [name for name in on_disk if prefix + name not in set(files.values())],
        "source": ASSET_SOURCE,
        # The nominal edge of the family: square for agent and rank, the shared WIDTH for
        # weapon, whose heights differ per file.  A view that wants one number reads this; a
        # view that has to fit a box reads ``px``.
        "intrinsic_px": max((size[0] for size in px.values()), default=0),
    }


def all_assets(frame: pd.DataFrame, tiers: pd.DataFrame, asset_dir: Path) -> Dict[str, Any]:
    """Every family that ships, declared the same way, from the same slug rule.

    The name set per family is the set the ACT actually contains, never the platform's whole
    catalogue.  The corpus ladder runs to Immortal 2; this act's lobbies run Iron 2 to Gold 3.  A
    badge for a division nobody in this act held would be art with no row to sit in, and it would
    turn the ``missing`` audit into permanent noise that nobody could ever act on.

    ``Unrated`` is not in the rank set and never can be.  It is not a low division, it is the
    absence of one, and it is 21.8% of this act's player-matches; it is carried as the
    ``placement`` state and drawn as an EMPTY slot beside that word.  The assertion below is what
    stops a later edit from quietly slugging it into ``unrated.png``.
    """
    divisions = {str(name) for name in tiers["tier"].dropna().unique()} - {UNRATED}
    sets = {
        "agent": {str(name) for name in frame["agent"].dropna().unique()},
        "weapon": {str(name) for name in frame["weapon"].dropna().unique()},
        "rank": divisions,
    }
    if any(UNRATED in names for names in sets.values()):
        raise ValueError("Unrated reached an asset family; it is not a thing with a picture")
    return {family: asset_family(sets[family], asset_dir / folder,
                                 "assets/%s/" % folder, job)
            for family, folder, _, job in ASSET_FAMILIES}


# --------------------------------------------------------------------------------------------
# cells
# --------------------------------------------------------------------------------------------

def _round(value: Optional[float], digits: int) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


def headline(bootstrapper: Bootstrapper, part: pd.DataFrame) -> Dict[str, Any]:
    stat = bootstrapper.rate(part, "mwpa")
    # The headline the site ranks on is per MATCH PLAYED, not per 100 rounds.  Per 100 rounds is
    # the estimator's own unit and nobody counts their season in rounds; per match reads straight
    # as "+6.4% is six extra wins per hundred matches".  It is the SAME quantity the bootstrap
    # resampled, rescaled by rounds-per-match, which runs 19.5 to 21.2 across the four and is a
    # positive constant within a player -- so a BCa interval, being transformation-respecting,
    # carries its endpoints across exactly and covers_zero does not move.  No second bootstrap.
    scale = (stat["rounds"] / stat["matches"]) / 100.0 if stat["matches"] else None
    return {
        "impact": _round(stat["total"] / stat["matches"], 6) if stat["matches"] else None,
        "impact_lo": _round(stat["lo"] * scale, 6) if scale and stat["lo"] is not None else None,
        "impact_hi": _round(stat["hi"] * scale, 6) if scale and stat["hi"] is not None else None,
        "rate": stat["rate"], "lo": stat["lo"], "hi": stat["hi"],
        "covers_zero": stat["covers_zero"], "total": stat["total"],
        "rounds": stat["rounds"], "matches": stat["matches"],
    }


def breakdown(
    bootstrapper: Bootstrapper,
    part: pd.DataFrame,
    keys: pd.Series,
    order: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """One cell per distinct key, with its interval.  A key with no rounds never appears."""
    cells = []
    for key, slice_ in part.groupby(keys, sort=False):
        stat = bootstrapper.rate(slice_, "mwpa")
        if not stat["rounds"]:
            continue
        cells.append({
            "key": str(key),
            "rounds": stat["rounds"],
            "matches": stat["matches"],
            "rate": stat["rate"], "lo": stat["lo"], "hi": stat["hi"],
            "total": stat["total"],
            "covers_zero": stat["covers_zero"],
            "thin": bool(stat["rounds"] < THIN_ROUNDS),
        })
    if order is not None:
        rank = {key: i for i, key in enumerate(order)}
        cells.sort(key=lambda cell: (rank.get(cell["key"], len(rank)), cell["key"]))
    else:
        cells.sort(key=lambda cell: (cell["key"] in ("Other", "Unknown"),
                                     -cell["rounds"], cell["key"]))
    return cells


def weapon_keys(part: pd.DataFrame, minimum: int) -> pd.Series:
    """Round-start primary, with the long tail folded into ``Other``.

    Without this a player's weapon table runs to a dozen rows of one or two rounds, each drawn from
    a single match and so each carrying a zero-width interval.  The fold keeps that exposure in the
    table rather than discarding it, and keeps it out of the cells that can be read.
    """
    weapon = part["weapon"].fillna("Unknown")
    counts = weapon.value_counts()
    small = set(counts[counts < minimum].index)
    return weapon.where(~weapon.isin(small), "Other")


def _derived_credits(part: pd.DataFrame) -> pd.DataFrame:
    """The frame with the two columns the ledger does not carry: the centering, and the duel.

    ``mwpa_lobby_adjustment`` is what the raw credit types miss; ``mwpa_duel_credit`` is the kill
    credit and the death debit summed per round-player, so that the row the rail draws is a
    resampled quantity rather than two intervals added together.
    """
    part = part.copy()
    raw_total = sum(part["mwpa_" + credit] for credit in CREDIT_TYPES)
    part["mwpa_lobby_adjustment"] = part["mwpa"] - raw_total
    drift = float((part["mwpa_lobby_adjustment"] + raw_total - part["mwpa"]).abs().max())
    if drift > 1e-9:
        raise ValueError("credit types do not reconstruct the raw ledger: %.3e" % drift)
    part["mwpa_" + DUEL_CREDIT] = sum(part["mwpa_" + credit] for credit in DUEL_PARTS)
    return part


def duel_parts(bootstrapper: Bootstrapper, part: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """The two halves of the duel row, kept because combining them is a display decision.

    The rail draws one signed row; the sentence under it says which two numbers went into it, and
    the breakdown of a ledger is not something a reader should have to take on trust.  Neither
    carries a ``share``: the shares on ``components`` sum to one over the rows that are drawn.
    """
    part = _derived_credits(part)
    block = {}
    for credit in DUEL_PARTS:
        stat = bootstrapper.rate(part, "mwpa_" + credit)
        block[credit] = {"rate": stat["rate"], "lo": stat["lo"], "hi": stat["hi"],
                         "total": stat["total"]}
    return block


def components(bootstrapper: Bootstrapper, part: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """The five parts of the headline: the duel, the two objective plays, the clock, the centering.

    The five decompose the *raw* ledger, so on their own they miss the headline by the centering --
    for the four focal players that gap runs from +0.006 to -0.082 per 100, which reads as an
    arithmetic error rather than as a modelling choice.  It is neither: centering subtracts the mean
    credit of everyone else in the round, and no single credit type owns that subtraction.

    Booking it as its own row makes the decomposition additive and puts the lobby adjustment on the
    page rather than in a footnote.  It is the difference between MWPA and RWPA, so it is the one
    component a reader most needs to see.  It is computed per row rather than as a residual, which
    is why it carries a real interval::

        mwpa - sum(mwpa_<credit>) == (rwpa_centered - rwpa) * leverage
                                  == -lobby_mean_others * leverage

    Kill credit and death debit arrive as one row, ``duel_credit``.  See ``DUEL_PARTS``: they are
    the two ends of one event and, drawn apart, their two enormous opposite spans set an axis on
    which the other three rows have no visible length.  The two are still emitted, under
    ``duel_parts``, so nothing is lost.
    """
    part = _derived_credits(part)
    names = list(COMPONENT_ORDER)
    totals = {credit: float(part["mwpa_" + credit].sum()) for credit in names}
    absolute = sum(abs(value) for value in totals.values())
    block = {}
    for credit in names:
        stat = bootstrapper.rate(part, "mwpa_" + credit)
        block[credit] = {
            "rate": stat["rate"], "lo": stat["lo"], "hi": stat["hi"],
            "total": stat["total"],
            "share": _round(abs(totals[credit]) / absolute, 4) if absolute > 0 else None,
        }
    return block


def card(part: pd.DataFrame, box: pd.DataFrame, puuid: str) -> Dict[str, Any]:
    """The facts a player recognises themselves by, measured rather than remembered.

    Everything on this site above this function is an estimate with an interval around it.  These
    are counts.  A kill happened or it did not, and a mean of thirty-eight of them needs no
    bootstrap -- so the card prints them plainly and the null rule never appears on it.  That is
    the division of labour the card exists to make: the headline is the claim, and these are the
    facts the claim is about.

    Three measurements and two lists:

    * per-match kills, deaths and assists, from the platform's own box score, averaged over the
      act matches this player is in.  Not per round: a match is what the headline divides by, and
      a card whose denominators disagreed with the headline's would be two cards.
    * rounds per match, which is what "a match" means on this site -- it is the constant the
      per-100-rounds rate is rescaled by, so it belongs beside the numbers it explains.
    * top agents by MATCHES, because an agent is a per-match choice and a round count would rank
      the agent whose matches ran long.  Ties break on rounds, then on name, so the list is
      deterministic across runs.
    * most-used guns by ROUNDS, because a gun is a per-round choice.  ``FREE_PISTOL`` is excluded:
      everybody starts a pistol round holding it, so its count measures the act's round structure
      rather than the player.  The excluded count is carried so the caveat can quote it.

    Neither list is padded.  A player with two agents shows two.
    """
    mine = box.loc[(box["puuid"] == puuid)
                   & (box["match_id"].isin(part["match_id"].unique()))]
    matches = int(part["match_id"].nunique())
    if len(mine) != matches:
        raise ValueError("%s: %d box-score rows against %d act matches"
                         % (puuid, len(mine), matches))

    rounds_by_agent = part["agent"].value_counts()
    agents = []
    for name, played in mine["agent"].value_counts().items():
        agents.append({"name": str(name), "matches": int(played),
                       "rounds": int(rounds_by_agent.get(name, 0))})
    agents.sort(key=lambda row: (-row["matches"], -row["rounds"], row["name"]))

    weapons_all = part["weapon"].fillna("Unknown").value_counts()
    kept = weapons_all.drop(labels=[FREE_PISTOL], errors="ignore")
    weapon_rounds = int(kept.sum())
    weapons = [{"name": str(name), "rounds": int(rounds),
                "share": _round(rounds / float(weapon_rounds), 4) if weapon_rounds else None}
               for name, rounds in kept.head(CARD_TOP_N).items()]

    return {
        "matches": matches,
        "rounds": int(len(part)),
        "rounds_per_match": _round(len(part) / float(matches), 2),
        "kills_per_match": _round(float(mine["kills"].mean()), 2),
        "deaths_per_match": _round(float(mine["deaths"].mean()), 2),
        "assists_per_match": _round(float(mine["assists"].mean()), 2),
        "agents": agents[:CARD_TOP_N],
        "agents_played": len(agents),
        "weapons": weapons,
        "weapon_rounds": weapon_rounds,
        "weapon_excluded": {"name": FREE_PISTOL,
                            "rounds": int(weapons_all.get(FREE_PISTOL, 0))},
    }


def synergy(
    bootstrapper: Bootstrapper,
    frame: pd.DataFrame,
    subject: str,
    partners: Sequence[Sequence[str]],
) -> List[Dict[str, Any]]:
    """Ordered pairs: the subject's own MWPA over the rounds a partner also played.

    Ordered because the two directions are different numbers -- Martin's rate alongside SN0RLAX is
    not SN0RLAX's rate alongside Martin.  A pair that never shared a round keeps its row, with a
    null rate, because the emptiness is the finding.
    """
    mine = frame.loc[frame["puuid"] == subject]
    rows = []
    for partner_puuid, partner_name, partner_short in partners:
        theirs = frame.loc[frame["puuid"] == partner_puuid, ["match_id", "round_id"]]
        shared = mine.merge(theirs, on=["match_id", "round_id"], how="inner")
        stat = bootstrapper.rate(shared, "mwpa")
        rows.append({
            "partner_short": partner_short,
            "partner_name": partner_name,
            "shared_matches": stat["matches"],
            "shared_rounds": stat["rounds"],
            "rate": stat["rate"], "lo": stat["lo"], "hi": stat["hi"],
            "covers_zero": stat["covers_zero"],
            "thin": bool(stat["rounds"] < THIN_ROUNDS),
        })
    return rows


# --------------------------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------------------------

def _entry(label: str, definition: str, unit: str, fmt: str, tier: str) -> Dict[str, str]:
    return {"label": label, "definition": definition, "unit": unit, "format": fmt, "tier": tier}


POINTS = "match win probability points"
ROUND_POINTS = "round win probability points"
RATE_UNIT = "match win probability points per 100 rounds"
PROBABILITY = "probability"

# Every probability on this site prints to one decimal place: 97.6%, never 98%.  A percentage
# point is a tenth of the smallest number on a match page, and rounding it away turns a real
# move into no move at all.  The formats live here so no view can decide otherwise.
PROBABILITY_FORMAT = ".1%"
# AND THE MOVE KEEPS THE PROBABILITY'S PRECISION, not MWPA's.  `dp` is +.1% where the other
# twelve fields in these units are +.2%, so one match page prints one kill as -24.1% on the curve
# and +24.14% in the swing panel below it.  That is deliberate: `dp` is the DIFFERENCE of two
# `p` values and `p` is written .1%, so a second decimal on the difference would claim precision
# neither number it comes from prints.  It is also the hover readout on a curve carrying 12,116
# action nodes, and it is the threshold that decides which clock nodes are a row in the round
# timeline -- 9,558 of 27,108 nodes are drift this format cannot write.
PROBABILITY_DELTA_FORMAT = "+.1%"
# The estimator's own unit, on `rate` and on both of its endpoints.  It is a constant because
# `null`'s definition has to SPELL a zero in it, and the loose literal that spelling used to
# carry was `+.4f` -- "+0.0000", a zero in a format no field on this site has written since the
# six grain and component fields moved to `+.2%`.  One string, read by the field and by the
# sentence that quotes the field.
RATE_FORMAT = "+.3f"


def build_dict(facts: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """A definition for every field the view renders.  The view hardcodes none of this."""
    bands = ", ".join(
        "%s below %s" % (name, format(int(high), ",")) if low == 0
        else "%s from %s" % (name, format(int(low), ","))
        if high > 10 ** 8
        else "%s from %s to %s" % (name, format(int(low), ","), format(int(high), ","))
        for name, low, high in BUY_BANDS
    )
    return {
        "mwpa": _entry(
            "MWPA",
            "Match win probability added. A player's round credits, each centered on the mean "
            "credit of everyone else who played that round, each multiplied by the round's "
            "marginal match value, and summed. A value of +62.00% is six tenths of a match "
            "win added.",
            POINTS, "+.2%", "headline"),
        "impact": _entry(
            "Impact per match",
            "MWPA divided by the matches the player was in: the share of a match win their "
            "credited actions are worth, per match played. +6.4% is six extra wins per hundred "
            "matches. It is the per-100-rounds rate rescaled by the player's own rounds per "
            "match, a positive constant, so the BCa endpoints carry across unchanged and so "
            "does `covers_zero`.",
            "match win probability per match", "+.1%", "headline"),
        "rate": _entry(
            "MWPA per 100 rounds",
            "MWPA divided by the rounds the player was credited in, times 100. It is the "
            "estimator's own unit; the four are ranked on `impact`.",
            RATE_UNIT, RATE_FORMAT, "headline"),
        "lo": _entry(
            "Interval low",
            "Lower bound of the %s BCa bootstrap interval, from %s replicates at seed %d, "
            "resampling whole matches so that rounds from one match move together."
            % (format(facts["confidence"], PROBABILITY_FORMAT),
               format(facts["bootstrap"], ","), facts["seed"]),
            RATE_UNIT, RATE_FORMAT, "headline"),
        "hi": _entry(
            "Interval high",
            "Upper bound of the same interval as `lo`. The width is the honest statement about "
            "this exposure; it is not an error bar to be squinted past.",
            RATE_UNIT, RATE_FORMAT, "headline"),
        "covers_zero": _entry(
            "Interval covers zero",
            "True when the interval spans zero, meaning this exposure does not separate the number "
            "from no effect at all. Check `matches` first: a cell whose rounds all come from one "
            "match has a zero-width interval and this flag carries no information there.",
            "", "bool", "headline"),
        "total": _entry(
            "Season total",
            "Signed sum of the player's MWPA across the act, in matches added rather than a rate.",
            "matches added", "+.3f", "headline"),
        "rounds": _entry(
            "Rounds",
            "Rounds in which the player carries at least one eligible ledger row. A player absent "
            "from a round has no row and contributes no zero.",
            "rounds", ".0f", "diagnostic"),
        "matches": _entry(
            "Matches",
            "Distinct matches contributing at least one round. This is also the number of clusters "
            "the bootstrap has to resample, which is what sets the interval width.",
            "matches", ".0f", "diagnostic"),
        "rank": _entry(
            "Rank",
            "Position among the four when sorted by `impact`, best first. Ranking is on by decision "
            "rather than because the data separates the players; the interval on each card is what "
            "keeps the ordering honest.",
            "", ".0f", "headline"),
        "thin": _entry(
            "Thin cell",
            "True when the cell has fewer than %d rounds. The rate and interval are still shown. "
            "The flag says the exposure is small, not that the number is wrong."
            % facts["rate_floor_marker_rounds"],
            "", "bool", "diagnostic"),
        "share": _entry(
            "Share of ledger",
            "The component's share of the player's total absolute credit across the components "
            "the rail draws — the duel as one row, then plant, defuse, the alive clock and the "
            "lobby adjustment. It describes what the ledger is made of, not how much of the "
            "headline the component explains.",
            "share of the absolute ledger", ".1%", "diagnostic"),
        # This entry used to close by arguing that a running total is here BECAUSE it is not an
        # average.  It is now the numerator of one -- the tracker divides it by `i` + 1 -- and an
        # argument against the figure a field feeds does not belong in the definition of the
        # field.  The argument is here, where the other format and wording arguments are.
        "cumulative": _entry(
            "Running total",
            "MWPA summed over every match up to and including this one, in match order. The "
            # NO WORKED EXAMPLE HERE ANY MORE. It used to close on "trzzcko's +0.510 over 8
            # is the +6.4% the front-page rail prints", which was two stale things at once:
            # the standings rail it quoted has been deleted, and the literals were the
            # 68-match corpus. A definition that hardcodes a count goes wrong every time the
            # act grows, and the thing it pointed at is now the label at the end of the line.
            "tracker divides it by `i` + 1, the matches played to that point, which is what "
            "makes each line end on that player's `impact`, the number written at the end "
            "of the line.",
            "matches added", "+.3f", "headline"),
        "exposure": _entry(
            "Exposure",
            "The rounds behind a cell, said against `gate.exposure_threshold_rounds` — the "
            "rounds a leverage-weighted rate needs before its interval can exclude zero. It is "
            "the answer to why an interval is as wide as it is, and it is printed instead of an "
            "interval on a cell whose rounds all come from one match.",
            # One decimal, like every other percentage on the site. At .0% a
            # 13-round cell and a 17-round cell both printed "2%", and the
            # whole-number form is the one thing the format rule forbids.
            "share of the threshold", ".1%", "diagnostic"),
        "null": _entry(
            "The null",
            "The value that means no claim. It is %s in a rate and %s on the match win "
            "probability curve, and it is drawn as one continuous rule at full strength: every "
            "quantity on this site is read as a departure from it, or as a failure to depart "
            "from it."
            % (format(0.0, RATE_FORMAT), format(0.5, PROBABILITY_FORMAT)),
            "", "text", "headline"),
        # THE CARD'S OWN FIELDS, and they are the only counts on this site.  Everything else
        # here is an estimate carrying an interval; a kill happened or it did not.  One decimal,
        # because the second one on a mean of eight to sixty-six matches is noise, and because
        # these sit in a block with `rounds_per_match`, which is the constant the headline is
        # rescaled by and is quoted to one decimal everywhere else on the site.
        "kills_per_match": _entry(
            "Kills",
            "Kills per match played, from the platform's own box score, averaged over the act "
            "matches this player appears in. It is a count and not an estimate: there is no "
            "interval on it and the null rule does not apply to it.",
            "per match", ".1f", "box score"),
        "deaths_per_match": _entry(
            "Deaths",
            "Deaths per match played, on the same denominator as kills.",
            "per match", ".1f", "box score"),
        "assists_per_match": _entry(
            "Assists",
            "Assists per match played, on the same denominator as kills. An assist splits 0.20 "
            "of a kill's credit in the ledger; here it is only counted.",
            "per match", ".1f", "box score"),
        "rounds_per_match": _entry(
            "Rounds",
            "The rounds this player was credited in, divided by their matches. This is what a "
            "match means for them, and it is the positive constant that turns the estimator's "
            "per-100-rounds rate into the impact per match at the top of the card.",
            "per match", ".1f", "box score"),
        "card_agents": _entry(
            "Most-played agents",
            "The agents this player picked most, counted in MATCHES, because an agent is chosen "
            "once per match. A player with fewer than `gate.card_top_n` agents shows only what "
            "they have; nothing is padded.",
            "", "text", "box score"),
        "card_weapons": _entry(
            "Most-used guns",
            "The round-start primaries this player held most, counted in ROUNDS, because a gun "
            "is chosen once per round. `gate.free_pistol` is excluded: everybody starts a pistol "
            "round holding it, so its count measures how many pistol rounds the act contained "
            "rather than anything about the player.",
            "", "text", "box score"),
        "leverage": _entry(
            "Round leverage",
            "The swing L = P(match win | this round won) - P(match win | this round lost), at the "
            "score entering the round, from the exact race-to-13 recursion with win-by-two "
            "overtime. Bounded by 0.5, which is its value at 12-12.",
            "match win probability per round win probability", ".4f", "diagnostic"),
        "li": _entry(
            "Leverage index",
            "The round's leverage divided by the act mean, so 1.00x is an ordinary round and "
            "3.05x is one that mattered three times as much. It is a display index and nothing "
            "else: L is what multiplies a credit, and dividing by it was the error this project "
            "ruled out rather than a second way to weight.",
            "multiples of the act mean leverage", ".2f", "diagnostic"),
        "mean_leverage": _entry(
            "Mean leverage",
            "The mean of L over every round-player in the act. It exists to index leverage for "
            "display and is never multiplied into a credit.",
            "match win probability per round win probability", ".4f", "diagnostic"),
        "confidence": _entry(
            "Confidence level",
            "The nominal coverage of every interval on this site. One number, one bootstrap, "
            "one seed: a headline, a two-round weapon cell and a synergy pair are all drawn "
            "from the same replicates and are therefore comparable to each other.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "wp_series": _entry(
            "Match win probability curve",
            "The focal side's match win probability as one continuous line that moves inside a "
            "round rather than once at each boundary. With the score at (a, b) and the focal "
            "side holding round win probability "
            "q, the match probability is W(a, b+1) + q x L(a, b), so the curve is the round "
            "model the ledger already produces, mapped onto the match by that round's own "
            "leverage. Its slope is the leverage, which is why a node's vertical move is the "
            "same number as that event's match impact rather than a second version of it.",
            "", "text", "headline"),
        "p": _entry(
            "Match win probability",
            "The focal side's probability of winning the match at one point on the curve, "
            "given the score and the state of the round in progress.",
            PROBABILITY, PROBABILITY_FORMAT, "headline"),
        "q": _entry(
            "Round win probability",
            "The focal side's probability of winning the round in progress. It is the round-level "
            "quantity the ledger is built on; the curve is this number mapped onto the match.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "dp": _entry(
            "Move",
            "The change in match win probability from the previous node. On an `action` node "
            "this is exactly that event's raw match impact, because the curve's slope is the "
            "round's leverage: a kill that moves the line 3.4 points moved the match 3.4 "
            "points. On the other three kinds it belongs to nobody, and `kind` says which.",
            POINTS, PROBABILITY_DELTA_FORMAT, "headline"),
        "kind": _entry(
            "Node kind",
            "Which of four different claims a point on the curve is making: `round_start`, "
            "`clock`, `action` or `terminal`. They are drawn differently because only one of "
            "them is attributable to a player.",
            "", "text", "diagnostic"),
        "kind_round_start": _entry(
            "Round start",
            "The buy is known and the model prices the round before anyone has acted. It is "
            "usually the largest move nobody made: round-start round win probability has a "
            "standard deviation of %.3f across the act, so an eco round opens with the match "
            "already leaning away. It belongs to the economy, never to a player, and carries "
            "no MWPA." % facts["round_start_sd"],
            "", "text", "diagnostic"),
        "kind_clock": _entry(
            "Clock",
            "Probability drifting between credited actions as the round ages. This is the "
            "alive-clock component of the ledger, split across each side's survivors.",
            "", "text", "diagnostic"),
        "kind_action": _entry(
            "Action",
            "An event with a time on it: a kill, a plant, a defuse, a revive, a spike "
            "detonation or an expired timer. The line's vertical move at one is that event's "
            "match impact, in match win probability points. Only the first three are credit "
            "types — the rest move the curve and are credited to nobody, which is why an "
            "action row can name an actor and still put nothing in that player's ledger.",
            "", "text", "diagnostic"),
        "kind_terminal": _entry(
            "Terminal",
            "The round resolves. The gap from the last action to here is the model's own "
            "calibration error at the terminal, which the ledger books to a team side rather "
            "than to a player. It is drawn rather than smoothed away.",
            "", "text", "diagnostic"),
        "x": _entry(
            "Position in the match",
            "Where a node sits along the match axis: the round number minus one, plus the "
            "share of that round's own clock elapsed. Whole numbers are round boundaries, so "
            "every round is the same width however long it took.",
            "rounds", ".3f", "diagnostic"),
        "t": _entry(
            "Time into the round",
            "Milliseconds from the start of the round to the node. The round's last event sets "
            "the horizon its x position is measured against.",
            "milliseconds", ".0f", "diagnostic"),
        "wp_before": _entry(
            "Match WP entering the round",
            "The focal side's match win probability at the score entering the round, before the "
            "round is priced. It is the value the curve arrives at from the previous round.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "wp_after": _entry(
            "Match WP after the round",
            "The same quantity once the round has resolved. This is a reconciliation and not an "
            "identity: the last round's value is a structural probability read off the score, "
            "not the result, and the two differ often enough that asserting equality would fail.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "p_before": _entry(
            "Round WP before the action",
            "The focal side's round win probability immediately before a credited action.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "p_after": _entry(
            "Round WP after the action",
            "The focal side's round win probability immediately after the same action. The "
            "difference between the two is what the ledger pays out.",
            PROBABILITY, PROBABILITY_FORMAT, "diagnostic"),
        "delta": _entry(
            "Action swing",
            "The action's move in round win probability, before leverage. Multiplying it by the "
            "round's leverage is what turns it into match units.",
            ROUND_POINTS, PROBABILITY_DELTA_FORMAT, "diagnostic"),
        "terminal_type": _entry(
            "Ended by",
            "How the round resolved, as the platform recorded it: an elimination, a defuse, a "
            "detonation, or a timer running out.",
            "", "text", "diagnostic"),
        # `+.2%`, not the `+.4f` these carried, because the two of them ADD UP to the `mwpa` in
        # the column beside them: on trzzcko's Summit match the row read MWPA -14.71%, attack
        # -0.1359, defense -0.0112. One quantity, one unit, three columns, and two of the three
        # were written in the other format. The sum is now visible as a sum.
        "attack_mwpa": _entry(
            "Attack MWPA",
            "The player's MWPA in this match summed over the rounds their team attacked.",
            POINTS, "+.2%", "exploratory"),
        "defense_mwpa": _entry(
            "Defense MWPA",
            "The player's MWPA in this match summed over the rounds their team defended.",
            POINTS, "+.2%", "exploratory"),
        # THE ROW THE RAIL DRAWS, and the two the rail no longer draws apart.  It is bootstrapped
        # as its own column: the kill credit and the death debit are strongly negatively
        # correlated within a round, so an interval for their sum is not the two intervals added.
        "duel_credit": _entry(
            "Duel credit",
            "Kill credit and death debit as one signed row: what the player's duels were worth "
            "net, after paying for the ones they lost. The two are the two ends of one event, "
            "and they are also an order of magnitude longer than every other component and "
            "pointed opposite ways — drawn apart they set an axis on which plant, defuse and "
            "the clock have no visible length. Resampled as a single column, never added out "
            "of two intervals: within a round the two are strongly negatively correlated, so "
            "their widths do not add.",
            POINTS, "+.2%", "diagnostic"),
        "kill_credit": _entry(
            "Kill credit",
            "Probability gained at kills the player made. An unassisted kill pays the killer in "
            "full; an assisted one pays 0.80 to the killer and splits 0.20 across the assists. "
            "That split is a construction convention, not an estimate.",
            POINTS, "+.2%", "diagnostic"),
        "death_debit": _entry(
            "Death debit",
            "Probability lost when the player died, debited in full to the victim. It is typically "
            "the largest single piece of a player's absolute ledger.",
            POINTS, "+.2%", "diagnostic"),
        "plant": _entry(
            "Plant",
            "Probability gained by planting the spike, paid to the planter.",
            POINTS, "+.2%", "diagnostic"),
        "defuse": _entry(
            "Defuse",
            "Probability gained by defusing, paid to the defuser.",
            POINTS, "+.2%", "diagnostic"),
        "alive_clock": _entry(
            "Alive clock",
            "The probability drift between events, split equally across each side's survivors. It "
            "is bookkeeping for who was present while the state aged, not a measure of survival "
            "skill.",
            POINTS, "+.2%", "diagnostic"),
        # The sixth component row has always been in the payload and was the one field with no
        # dictionary entry, which left the view to invent a label for it.
        "lobby_adjustment": _entry(
            "Lobby adjustment",
            "The centering itself, booked as its own row: the mean credit of everyone else in the "
            "round, which no single credit type owns. With it the components sum to the "
            "headline exactly.",
            POINTS, "+.2%", "diagnostic"),
        "agent": _entry(
            "Agent",
            "The agent the player picked. Only the player with several hundred rounds on each of "
            "three agents has cells here that can be told apart; for everyone else this table is "
            "one usable row or none.",
            "", "text", "exploratory"),
        "map": _entry(
            "Map",
            "The map played. Seven of the pool's thirteen appear in this act, which spreads a "
            "player's matches thin enough that most map cells are a handful of games.",
            "", "text", "exploratory"),
        "side": _entry(
            "Side",
            "Attack or defense, from the player's team's point of view in that round. Sides swap "
            "at the half and again each round in overtime.",
            "", "text", "exploratory"),
        "buy_class": _entry(
            "Buy class",
            "The team's round-start loadout band, in credits: %s. The cut points come from this "
            "corpus's own loadout distribution rather than Counter-Strike convention." % bands,
            "", "text", "exploratory"),
        "weapon": _entry(
            "Weapon",
            "The player's round-start primary. Anything with fewer than %d rounds is folded into "
            "`Other` rather than emitted as a tail of one-round cells."
            % facts["weapon_min_rounds"],
            "", "text", "exploratory"),
        "key": _entry(
            "Cell",
            "The value of the breakdown dimension this row covers.",
            "", "text", "diagnostic"),
        "partner_short": _entry(
            "Partner",
            "The other player in an ordered synergy pair. The row is the subject's own MWPA over "
            "the rounds this partner also played.",
            "", "text", "exploratory"),
        "partner_name": _entry(
            "Partner name",
            "The partner's Riot id. Only the four consented players are ever named.",
            "", "text", "exploratory"),
        "shared_matches": _entry(
            "Shared matches",
            "Matches in which both players of the pair appear.",
            "matches", ".0f", "exploratory"),
        "shared_rounds": _entry(
            "Shared rounds",
            "Rounds in which both players of the pair carry a ledger row. This is the exposure the "
            "pair's interval is drawn from.",
            "rounds", ".0f", "exploratory"),
        "score": _entry(
            "Score",
            "Final rounds won, the four players' team first.",
            "rounds", ".0f", "diagnostic"),
        "won": _entry(
            # The label a reader sees, not the field name. `won` is what the
            # column is called in the payload; "Result" is what it says.
            "Result",
            "Whether the four players' team won the match.",
            "", "bool", "diagnostic"),
        "started_at": _entry(
            "Started",
            "Match start time as the platform reported it, in UTC. Matches are ordered by it "
            "everywhere on the site.",
            "", "date", "diagnostic"),
        "match_id": _entry(
            "Match",
            "The platform's match identifier, and the join key between every file in this payload.",
            "", "text", "diagnostic"),
        "focal": _entry(
            "Focal players",
            "Which of the four played in this match. Everyone else in it is a match-scoped "
            "pseudonym.",
            "", "text", "diagnostic"),
        "i": _entry(
            "Match index",
            "Zero-based position of the match in the player's own chronological order. It is "
            "not the tracker's x — that is the act's shared match order, so four series with "
            "8, 32, 60 and 8 matches sit on one timeline. `i` is the denominator: `cumulative` "
            "over `i` + 1 is the player's running `impact`.",
            "", ".0f", "diagnostic"),
        "short": _entry(
            "Short name",
            "The player's slug, used for file names and links.",
            "", "text", "diagnostic"),
        "name": _entry(
            "Name",
            "The player's Riot id.",
            "", "text", "diagnostic"),
        "puuid": _entry(
            "Player id",
            "The player's stable identifier. It is stable only for these four; every other player "
            "in the corpus is re-pseudonymized per match.",
            "", "text", "diagnostic"),
        "tier": _entry(
            "Division",
            "The competitive division the platform had the player at when this match was played. "
            "It is per match, so a player has a path across the act rather than a rank. A null "
            "means no rank had been issued yet, which is a measurement and not a missing value.",
            "", "text", "ladder"),
        "rank_track": _entry(
            "Rank trajectory",
            "One step per match, in the player's own match order: the division held, its position "
            "on `gate.tier_order`, and whether a rank existed at all. This is the only source the "
            "trajectory figure draws from, and its `ordinal` is the only number allowed to be a y "
            "value there.",
            "", "text", "ladder"),
        "ordinal": _entry(
            "Ladder position",
            "One-based position on `gate.tier_order`, which is the platform's ladder with its "
            "unranked state removed. The platform's own enum numbers the unranked state zero on "
            "the same scale as the divisions; plotting that would put a player who has no rank "
            "yet below the bottom division, so this site does not carry it.",
            "", ".0f", "ladder"),
        "state": _entry(
            "Rank state",
            "`ranked` or `placement`. In placement the platform had issued no rank, so there is "
            "no division, no ladder position and no axis to draw one against.",
            "", "text", "ladder"),
        "ladder": _entry(
            "Ladder summary",
            "First and last division of the act, the highest and lowest held, how many matches "
            "were played before a rank existed, and how many times the division moved up and "
            "down between consecutive ranked matches.",
            "", "text", "ladder"),
        "lobby_tiers": _entry(
            "Lobby divisions",
            "The range of divisions in this match's lobby, and how many of the ten had no rank "
            "issued yet. A lobby is not division-homogeneous, which is the one thing about "
            "divisions that a match page can answer.",
            "", "text", "ladder"),
    }


def build_cav(facts: Dict[str, Any]) -> List[Dict[str, str]]:
    """Interpretation caveats. Every number in them is computed, not asserted."""
    return [
        {
            "id": "act_scope",
            "text": (
                "Every number here is act %s alone — %s matches, %s rounds — with nothing pooled "
                "across acts."
                % (facts["act"], format(facts["matches"], ","), format(facts["rounds"], ","))
            ),
        },
        {
            "id": "two_scoring_provenances",
            "text": (
                "%s of these matches were priced inside the model release, each by a fold fit "
                "without it. %s were collected after the release was cut, and cross-fitting keeps "
                "its predictions but not its models, so those are priced by a refit on the "
                "release's own core at the parameters all five folds already chose. Neither kind "
                "was in the training data of the model that scored it; what differs is that one "
                "model saw four fifths of the corpus and the other saw all of it, worth a mean "
                "%s of round win probability across the act's states."
                % (format(facts["scored_in_release"], ","),
                   format(facts["scored_after_release"], ","),
                   format(facts["scoring_seam_mean_abs"], ".1%"))
            ),
        },
        {
            "id": "surrendered_rounds_are_not_played_rounds",
            "text": (
                "%s rounds in this act ended in a surrender. A surrendered round is awarded, not "
                "played — no events, no kills — so it is outside every number here, while the "
                "rounds played before it stay in: they ran under a real race to 13, against a "
                "score nobody yet knew would be conceded. The scoreline on such a match is the "
                "played one, and the round count reconciles against it."
                % format(facts["surrendered_rounds"], ",")
            ),
        },
        {
            "id": "rank_by_decision",
            "text": (
                "The four are ordered on impact per match because that decision was taken for "
                "this site, not because the data separates them. %s No page prints a rank "
                "number any more: what survives is the order the four are listed in, on the "
                "season tracker's legend and in the columns of the match cross-tab. Read that "
                "order as a sort, and the interval on each card as the result."
                % facts["covers_zero_text"]
            ),
        },
        {
            "id": "side_split_unresolvable",
            "text": (
                "The attack/defense split cannot resolve at this exposure: it needs roughly %s "
                "rounds at this credit variance and the act has %s. Both cells are published "
                "with their intervals; the width there is the sample, not the player."
                % (format(ROUNDS_FOR_SIDE_SPLIT, ","), format(facts["rounds"], ","))
            ),
        },
        {
            "id": "no_abilities",
            "text": (
                "Abilities do not exist in this data at any grain — four integers per "
                "player-match, null in every round record — so smokes, flashes and mollies are "
                "absent from every number here. Revives are UNCREDITED rather than absent: a "
                "revive is a timed event, so the curve moves under one and the round timeline "
                "prints that move beside whoever cast it, but revive is not one of the five "
                "credit types and no player's ledger carries it. The five are the whole ledger, "
                "and no cell renders a zero for utility."
            ),
        },
        {
            "id": "pseudonymous_opponents",
            "text": (
                "Everyone but the four is a match-scoped pseudonym: the same person in two "
                "matches carries two unrelated names, and nothing here links them."
            ),
        },
        {
            "id": "noindex_is_not_access_control",
            "text": (
                "A noindex tag and a robots.txt keep this out of search results, which is not "
                "access control: the pages sit in a public repository, readable by anyone with "
                "the URL, including round-level detail on %s players who did not consent to any "
                "of it. The point was raised before the build and the decision to publish was "
                "reaffirmed."
                % format(facts["players"] - len(FOCAL), ",")
            ),
        },
        {
            "id": "thin_cells_shown",
            "text": (
                "The %d-round floor marks a cell rather than suppressing it: below it a cell "
                "carries `thin` and still prints its number and interval. Per-round MWPA has a "
                "standard deviation of %.4f in this act, so a %d-round mean carries a pure-noise "
                "standard error of about %.2f per 100 rounds against a spread between the four "
                "of %.2f — read a thin cell as description, not estimate."
                % (facts["rate_floor_marker_rounds"], facts["mwpa_sd"],
                   facts["rate_floor_marker_rounds"], facts["thin_noise_se"],
                   facts["player_rate_spread"])
            ),
        },
        {
            "id": "no_zero_for_absence",
            "text": (
                "A breakdown cell with no rounds is omitted rather than emitted as zero, and the "
                "view renders that absence. A synergy pair is the exception: it keeps its row "
                "with a null rate, because two players never sharing a round is the finding."
            ),
        },
        {
            "id": "duel_tags_incomplete",
            "text": (
                "Duel tags cover %s of %s earned rows; the missing %s, %.1f%%, are %s across %s "
                "rounds. They have no round-player row to attach to, because the ledger scores "
                "nobody who was alive and produced no kill, death, plant, defuse or clock share — "
                "a clutch lost without firing is the modal case."
                % (format(facts["duel_tag_attached"], ","),
                   format(facts["duel_tag_rows"], ","),
                   format(facts["duel_tag_missing"], ","),
                   facts["duel_tag_missing_share"],
                   facts["duel_tag_missing_breakdown"],
                   format(facts["duel_tag_missing_rounds"], ","))
            ),
        },
        {
            "id": "single_match_interval",
            "text": (
                "The bootstrap resamples whole matches, so a cell whose rounds all come from one "
                "match has a zero-width interval that reads as excluding zero and does not: one "
                "cluster, nothing for the resample to vary. Check `matches` before `covers_zero`."
            ),
        },
        {
            "id": "measured_zero_at_display_precision",
            "text": (
                # The literal `<0.0001` used to be quoted here.  It is wrong now that mwpa
                # prints as +.2%, and it was always the field's own format talking rather than
                # this caveat's, so the rule is stated and the number is left to the format.
                "A magnitude that rounds to zero at its own format is MEASURED, not missing: it "
                "prints as less than the smallest number that format can write, with no sign and "
                "no direction colour. The em dash stays reserved for the unmeasured, the middot "
                "for an exact zero."
            ),
        },
        {
            "id": "the_null_is_the_loudest_mark",
            "text": (
                "The heaviest ink on every figure is the line at the value that means no claim, "
                "%s on the match win probability curve, drawn as one unbroken element through a "
                "whole block rather than a tick per row. On the curve it sits UNDER the line, "
                "because a rule that heavy would otherwise erase the data wherever the match sat "
                "near even."
                % format(0.5, PROBABILITY_FORMAT)
            ),
        },
        {
            "id": "the_duel_is_one_row",
            "text": (
                "Kill credit and death debit are drawn as one signed row, the duel credit, and "
                "the two are still printed underneath it in words. The reason is legibility and "
                "it is arithmetic: the two are an order of magnitude longer than every other "
                "component and pointed opposite ways, so drawn apart they set an axis on which "
                "plant, defuse and the alive clock are a pixel each. They are also the two ends "
                "of one event — a duel resolves, somebody is paid, somebody is debited — so "
                "their sum is a quantity rather than a convenience. Its interval is resampled "
                "on the summed column and is not the two intervals added: within a round the "
                "two are strongly negatively correlated, so their widths do not add."
            ),
        },
        {
            "id": "classic_is_the_free_pistol",
            "text": (
                "The most-used guns on a player card exclude the %s. Every player starts every "
                "pistol round holding it, whatever they meant to buy, so a Classic count "
                "measures how many pistol rounds the act contained and not what this player "
                "chooses to hold. Nothing else is excluded, and the guns are counted in rounds "
                "rather than matches because a gun is a per-round choice."
                % FREE_PISTOL
            ),
        },
        {
            "id": "the_card_is_counts_not_estimates",
            "text": (
                "The block at the top of a player page carries two registers and they are drawn "
                "apart. The impact per match is an estimate and it keeps its interval and its "
                "verdict against the null. The kills, deaths, assists, rounds, agents and guns "
                "beside it are counts: they happened, they carry no interval, and no null rule "
                "is drawn through them. A card that put a confidence band on a kill count would "
                "be claiming uncertainty about something nobody is uncertain about."
            ),
        },
        {
            "id": "components_include_the_lobby_adjustment",
            "text": (
                "The five credit types decompose the raw ledger before the lobby centering, so a "
                "further row carries that centering and the rows sum to the headline exactly. "
                "Across the four the raw five sum to %+.4f against a headline sum of %+.4f, and "
                "the lobby adjustment is the %+.4f between them."
                % (
                    facts["component_sum"],
                    facts["headline_sum"],
                    facts["headline_sum"] - facts["component_sum"],
                )
            ),
        },
        {
            "id": "wp_curve_boundary_seam",
            "text": (
                "The curve steps at a round boundary and the step is real: the match model runs "
                "every future round at a constant win probability of %.1f, so a boundary is the "
                "score talking, and the round-start node then moves it to the model's price on "
                "the round about to be played. Across the %s rounds of this act the median step "
                "is %.1f match win probability points and the largest is %.1f; neither end of it "
                "is a player."
                % (facts["neutral_round_p"], format(facts["boundary_step_rounds"], ","),
                   100.0 * facts["boundary_step_median"], 100.0 * facts["boundary_step_max"])
            ),
        },
        {
            "id": "leverage_widens",
            "text": (
                "Weighting each round by its marginal match value widens every interval rather "
                "than narrowing it: the rounds needed to exclude zero rise from about 546 to "
                "about %s. %s"
                % (format(ROUNDS_TO_EXCLUDE_ZERO, ","), facts["above_threshold_text"])
            ),
        },
        {
            "id": "buy_bands_local",
            "text": (
                "The buy classes are cut from this corpus's own team-loadout distribution, not "
                "from Counter-Strike convention. Eco rounds are won %s of the time in this act, "
                "against roughly one in thirty in professional Counter-Strike, which is direct "
                "evidence that the imported cut points describe a different game."
                % format(facts["eco_win_rate"], PROBABILITY_FORMAT)
            ),
        },
        {
            "id": "synergy_is_ordered",
            "text": (
                "Synergy is ordered: each row is the subject's own MWPA over the rounds a given "
                "partner also played, not a joint estimate, so the two directions of a pairing "
                "are different numbers. %s"
                % facts["synergy_text"]
            ),
        },
        {
            "id": "descriptive_not_causal",
            "text": (
                "MWPA is a descriptive allocation of modelled probability movement, not a causal "
                "player effect. The model behind it carries no player, team or lobby term, so "
                "every credit is a residual against a baseline pooled across ranks."
            ),
        },
        {
            "id": "tier_placement_window",
            "text": (
                "A player's first %s act matches are played before the platform has issued a "
                "rank: not a missing value and not a zero, but the measured answer that no "
                "division existed yet. Verified rather than assumed — %s of the %s act players "
                "who have such a match carry it as a strict prefix, with no counterexamples."
                % (facts["placement_matches"], format(facts["placement_holders"], ","),
                   format(facts["players"], ","))
            ),
        },
        {
            "id": "tier_is_not_mwpa",
            "text": (
                "The ladder is a second instrument and it is not measuring this: over the %s "
                "focal player-matches with at least %s ranked others in the lobby, the lobby's "
                "mean division correlates with that match's MWPA at r = %s, with the lobby "
                "adjustment at r = %s, and with that adjustment as a rate at r = %s. Lobbies are "
                "not division-homogeneous either — the median spread inside one is %s divisions "
                "and the widest is %s."
                % (format(facts["tier_n"], ","), facts["tier_minimum_ranked"],
                   format(facts["r_tier_mwpa"], "+.3f"),
                   format(facts["r_tier_lobby_adjustment"], "+.3f"),
                   format(facts["r_tier_lobby_adjustment_rate"], "+.3f"),
                   format(facts["lobby_spread_median"], ".0f"), facts["lobby_spread_max"])
            ),
        },
        {
            "id": "imagery_is_not_a_mark",
            "text": (
                "No picture here is a measurement, because of where they are put: three families "
                "ship — %s agent portraits, %s division badges, %s weapon silhouettes — each "
                "beside a word that is always rendered, and the header control removes all %s "
                "files at once, so flipping it costs recognition and not one fact. What clears "
                "the 3:1 mark floor is the 1-pixel box around each picture, at %s:1 worst, not "
                "the picture inside it — of the %s portraits only %s clear that floor on every "
                "surface they land on."
                % (facts["agent_files"], facts["rank_files"], facts["weapon_files"],
                   facts["agent_files"] + facts["rank_files"] + facts["weapon_files"],
                   format(min(facts["agent_slot_ratio"], facts["rank_slot_ratio"],
                              facts["weapon_slot_ratio"]), ".2f"),
                   facts["agent_files"], facts["agent_mark_grade"])
            ),
        },
        {
            "id": "where_imagery_is_allowed",
            "text": (
                # The full argument -- confusability at the render box, the per-round panel
                # spread, the 4-pages-versus-68-pages cost -- was four sentences of it.  One
                # number decides it: the modal weapon takes a double-digit share of every named
                # cell in the ledger, which is what makes an icon column there texture.
                "The round ledger stays words: across %s named cells %s alone is %s%%, so an "
                "icon column there repeats and is texture rather than navigation. The "
                "silhouettes ship in the `by weapon` breakdown, where every row is a distinct "
                "weapon; a division badge ships only beside the division word and never in a "
                "cell carrying a player hue, because Riot's gold sits within OKLab ΔE 3.5 of one "
                "player's own hue; map art is refused. The player card is the one place the art "
                "is not eighteen pixels tall — everywhere else it rides inside a table row and "
                "the row's line box is the constraint, and a card is not a row, so the agents "
                "and the guns on it are drawn at the size the files actually are. Nothing else "
                "about them changes: the word is beside every picture, the weapon plate comes "
                "with the weapon art, and the header control still takes all of it away without "
                "losing a fact."
                % (format(facts["weapon_ledger_cells"], ","), facts["weapon_top_name"],
                   format(facts["weapon_top_share"], ".1f"))
            ),
        },
        {
            "id": "riot_assets",
            "text": (
                "All three families are Riot Games' own artwork, fetched once from "
                "valorant-api.com and served from this directory: %s agent portraits at %s "
                "pixels square, %s division badges at %s square, and %s weapon silhouettes %s "
                "pixels wide, used under Riot's fan content policy. This site is not endorsed by "
                "or affiliated with Riot Games."
                % (facts["agent_files"], facts["agent_intrinsic_px"],
                   facts["rank_files"], facts["rank_intrinsic_px"],
                   facts["weapon_files"], facts["weapon_intrinsic_px"])
            ),
        },
        {
            "id": "unrated_is_not_a_division",
            "text": (
                "%s%% of this act's player-matches carry no division, and no badge ships for that "
                "state: Riot's enum puts `Unrated` at id 0 on the ladder that has Iron 2 at 4, "
                "which would draw the absence of a rank as a rung below the lowest one, and "
                "`Unrated` is also the name of a queue while all %s of these matches are "
                "Competitive. It is the word `placement` everywhere it appears — not an em dash, "
                "which on this site means NOT MEASURED — and on the ladder it gets an empty slot "
                "in a dashed hairline."
                % (facts["placement_share_text"], format(facts["matches"], ","))
            ),
        },
    ]


# --------------------------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------------------------

def match_index(frame: pd.DataFrame, context: Dict[str, Any]) -> pd.DataFrame:
    """One row per match: focal team, final score, result, and which of the four played."""
    focal_shorts = {puuid: short for puuid, _, short in FOCAL}
    rows = []
    for match_id, part in frame.groupby("match_id", sort=False):
        played = part.loc[part["puuid"].isin(focal_shorts)]
        teams = sorted(played["team"].unique().tolist())
        if len(teams) != 1:
            raise ValueError("match %s has focal players on %d teams" % (match_id, len(teams)))
        team = teams[0]
        result = context["teams"].loc[(match_id, team)]
        rounds = int(part["round_id"].nunique())
        if rounds != int(result["rounds_won"]) + int(result["rounds_lost"]):
            raise ValueError("match %s: %d scored rounds against a %d-%d scoreline"
                             % (match_id, rounds, result["rounds_won"], result["rounds_lost"]))
        meta = context["matches"].loc[match_id]
        rows.append({
            "match_id": match_id,
            "started_at": str(meta["started_at"]),
            "map": str(meta["map"]),
            "rounds": rounds,
            "score": [int(result["rounds_won"]), int(result["rounds_lost"])],
            "won": bool(int(result["won"])),
            "focal": sorted(focal_shorts[p] for p in played["puuid"].unique()),
        })
    index = pd.DataFrame(rows).sort_values(["started_at", "match_id"]).reset_index(drop=True)
    return index


def build_site(
    frame: pd.DataFrame,
    bootstrapper: Bootstrapper,
    context: Dict[str, Any],
    index: pd.DataFrame,
    players: List[Dict[str, Any]],
    facts: Dict[str, Any],
    ladder: Dict[str, Any],
) -> Dict[str, Any]:
    # Sorted on the headline the site prints, which is now impact per match.  Rounds per match
    # runs 19.5 to 21.2 across the four, so the rescale is nearly common and the order comes out
    # identical to the old rate order -- asserted below rather than assumed, because a ranking
    # that quietly reshuffled would reopen every argument on the site.
    by_rate = [row["short"] for row in sorted(players, key=lambda r: (-(r["rate"] or 0.0),
                                                                     r["short"]))]
    players = sorted(players, key=lambda row: (-(row["impact"] or 0.0), row["short"]))
    if [row["short"] for row in players] != by_rate:
        raise ValueError("impact reorders the four against rate: %s vs %s"
                         % ([row["short"] for row in players], by_rate))
    for rank, row in enumerate(players, start=1):
        row["rank"] = rank
        # The one thing about these four that measurably moved, as eight characters the front
        # page can print at the end of a sub-line.  A fact, never a trend.
        row["ladder"] = ladder["summaries"][row["short"]]

    won_by_match = dict(zip(index["match_id"], index["won"]))
    tracker = {}
    for puuid, _, short in FOCAL:
        part = frame.loc[frame["puuid"] == puuid]
        per_match = part.groupby("match_id").agg(mwpa=("mwpa", "sum"), rounds=("mwpa", "size"))
        ordered = [m for m in index["match_id"] if m in per_match.index]
        running = 0.0
        series = []
        for i, match_id in enumerate(ordered):
            row = per_match.loc[match_id]
            running += float(row["mwpa"])
            meta = context["matches"].loc[match_id]
            series.append({
                "i": i,
                "match_id": match_id,
                "started_at": str(meta["started_at"]),
                "map": str(meta["map"]),
                "mwpa": round(float(row["mwpa"]), 6),
                "cumulative": round(running, 6),
                "rounds": int(row["rounds"]),
                "won": bool(won_by_match[match_id]),
            })
        tracker[short] = series

    matches = [
        {
            "match_id": row["match_id"], "started_at": row["started_at"], "map": row["map"],
            "rounds": int(row["rounds"]), "score": list(row["score"]), "won": bool(row["won"]),
            "focal": list(row["focal"]),
        }
        for _, row in index.iterrows()
    ]

    return {
        "meta": {
            "act": facts["act"],
            "release": RELEASE,
            "matches": facts["matches"],
            "rounds": facts["rounds"],
            "round_players": facts["round_players"],
            "players": facts["players"],
            "bootstrap": facts["bootstrap"],
            "seed": facts["seed"],
            "confidence": facts["confidence"],
            "mean_leverage": facts["mean_leverage"],
            "generated_at": date.today().isoformat(),
            "gate": {
                "rank_players": True,
                "rate_floor_rounds": RATE_FLOOR_ROUNDS,
                "rate_floor_marker_rounds": THIN_ROUNDS,
                # The two research thresholds the view draws against.  They were quoted only
                # inside caveat prose before, which meant the exposure rail on the front page
                # would have had to carry a literal.  A rule the view draws is a gate value.
                "exposure_threshold_rounds": ROUNDS_TO_EXCLUDE_ZERO,
                "side_split_rounds": ROUNDS_FOR_SIDE_SPLIT,
                # The null: the value that means no claim, in each of the two units the site
                # draws it in.  Nothing in the view decides where the heavy rule goes.
                "null_rate": 0.0,
                "null_probability": 0.5,
                # The ladder, its axis floor and its placement window.  Nothing in the view
                # decides what beats what, how tall an axis has to be, or how long a player
                # goes unranked.
                "tier_order": ladder["order"],
                "tier_axis_min_span": TIER_AXIS_MIN_SPAN,
                "tier_placement_matches": ladder["placement"]["matches"],
                # The card's two lists.  The name of the gun that does not count and the length
                # of a list are both decisions, so neither is typed in the view.
                "free_pistol": FREE_PISTOL,
                "card_top_n": CARD_TOP_N,
                # The two credit types the component rail draws as one signed row, and the key
                # that row arrives under, named here so the view never chooses either.
                "duel_parts": list(DUEL_PARTS),
                "duel_key": DUEL_CREDIT,
            },
            # The ladder measured against the rating, as numbers rather than only as prose,
            # because the front page draws the sentence that quotes them and a view may not
            # retype a measurement.
            "ladder": ladder["correlation"],
            # Three families, declared identically.  build.py's guard reads the folder name off
            # every path in here and refuses to run against a folder on disk that no family
            # claims, so this dict is the whole list of imagery this site is allowed to have.
            "assets": ladder["assets"],
            "dict": build_dict(facts),
            "cav": build_cav(facts),
        },
        "players": players,
        "tracker": tracker,
        "matches": matches,
    }


def build_player(
    frame: pd.DataFrame,
    bootstrapper: Bootstrapper,
    context: Dict[str, Any],
    index: pd.DataFrame,
    puuid: str,
    name: str,
    short: str,
    ladder: Dict[str, Any],
) -> Dict[str, Any]:
    part = frame.loc[frame["puuid"] == puuid]
    won_by_match = dict(zip(index["match_id"], index["won"]))
    track = ladder["tracks"][short]
    track_by_match = {row["match_id"]: row for row in track}

    matches = []
    for match_id in index["match_id"]:
        slice_ = part.loc[part["match_id"] == match_id]
        if slice_.empty:
            continue
        agents = slice_["agent"].value_counts()
        meta = context["matches"].loc[match_id]
        step = track_by_match[match_id]
        matches.append({
            "match_id": match_id,
            "started_at": str(meta["started_at"]),
            "map": str(meta["map"]),
            "agent": str(agents.index[0]),
            # null means placement: no rank had been issued yet.  Never a zero, never an em
            # dash (which on this site means NOT MEASURED), never the platform's queue name.
            "tier": step["tier"],
            "mwpa": round(float(slice_["mwpa"].sum()), 6),
            "rounds": int(len(slice_)),
            "won": bool(won_by_match[match_id]),
            "attack_mwpa": round(float(slice_.loc[slice_["side"] == "attack", "mwpa"].sum()), 6),
            "defense_mwpa": round(float(slice_.loc[slice_["side"] == "defense", "mwpa"].sum()), 6),
        })
    if len(matches) != len(track):
        raise ValueError("%s: %d matches against a %d-step rank track"
                         % (short, len(matches), len(track)))

    sides = breakdown(bootstrapper, part, part["side"], order=SIDES)
    if len(sides) != len(SIDES):
        raise ValueError("%s has %d side cells, expected %d" % (short, len(sides), len(SIDES)))

    partners = [(p, n, s) for p, n, s in FOCAL if p != puuid]
    return {
        "puuid": puuid,
        "name": name,
        "short": short,
        "headline": headline(bootstrapper, part),
        "card": card(part, context["box"], puuid),
        "components": components(bootstrapper, part),
        "duel_parts": duel_parts(bootstrapper, part),
        "rank_track": track,
        "ladder": ladder["summaries"][short],
        "matches": matches,
        "breakdowns": {
            "agent": breakdown(bootstrapper, part, part["agent"]),
            "map": breakdown(bootstrapper, part, part["map"]),
            "side": sides,
            "buy_class": breakdown(bootstrapper, part, part["buy_class"], order=BUY_ORDER),
            "weapon": breakdown(bootstrapper, part, weapon_keys(part, WEAPON_MIN_ROUNDS)),
        },
        "synergy": synergy(bootstrapper, frame, puuid, partners),
    }


def scoring_provenance(work: Path) -> Dict[str, Any]:
    """Which model priced each match, counted off the ledger's own provenance columns.

    Not every match on this site was priced the same way, and the ledger has always said so in
    band. A match inside the release carries a ``crossfit_fold`` and was scored by a fold model
    that was fit WITHOUT it -- roughly four fifths of the corpus. A match collected after the
    release was cut has no fold: cross-fitting keeps its held-out predictions and discards the
    models, so there is no fold model left to score anything new, and the release ships none.
    Those matches are priced by a model refit on the release's own core at the release's own
    parameters -- all five folds chose ``max_leaf_nodes=21, l2_regularization=20.0``, so nothing
    was retuned -- and they were never in its training data either, so both kinds are honestly
    out of sample. What differs is the training fraction, and the difference that makes is
    measured rather than characterised: ``data/model_v15_scoring/seam.json``.
    """
    ledger = pd.read_csv(work / "rwpa_crossfit_ledger.csv",
                         usecols=["match_id", "crossfit_fold"], low_memory=False)
    by_match = ledger.groupby("match_id")["crossfit_fold"].apply(lambda s: s.notna().any())
    after = int((~by_match).sum())
    seam_path = LAB / "data" / "model_v15_scoring" / "seam.json"
    if after and not seam_path.exists():
        raise ValueError(
            "%d matches were scored outside the release but %s does not exist, so the size of "
            "that difference is unmeasured and the caveat would be prose" % (after, seam_path))
    measured = json.loads(seam_path.read_text()) if seam_path.exists() else {}
    return {
        "scored_in_release": int(by_match.sum()),
        "scored_after_release": after,
        "scoring_seam_mean_abs": float(measured.get("mean_abs_diff", 0.0)),
        "scoring_seam_states": int(measured.get("states_compared", 0)),
    }


def boundary_seam(work: Path, frame: pd.DataFrame) -> Dict[str, float]:
    """How far the curve jumps when a round is priced, measured over every round in the act.

    The match model runs every *future* round at ``NEUTRAL_ROUND_P``, so ``W(a, b)`` is exactly
    the continuous curve evaluated at a round-win probability of that same value::

        W(a, b) = W(a, b+1) + NEUTRAL_ROUND_P * L(a, b)

    which is asserted below rather than assumed.  A round boundary is therefore a context-neutral
    point, and the round-start node moves it to the model's price on *this* round: the step is
    exactly ``(q0 - NEUTRAL_ROUND_P) * L``.  That seam is the subject of one caveat, so its size
    is measured here instead of being characterised in prose.
    """
    for own in range(0, 14):
        for other in range(0, 14):
            if own >= 13 or other >= 13:
                continue
            here = match_win_probability(own, other)
            projected = (match_win_probability(own, other + 1)
                         + NEUTRAL_ROUND_P * round_leverage(own, other))
            if abs(here - projected) > 1e-12:
                raise ValueError(
                    "the round boundary is not the curve at p=%r at %d-%d: %r vs %r"
                    % (NEUTRAL_ROUND_P, own, other, here, projected))

    rounds = pd.read_csv(work / "rwpa_crossfit_rounds.csv", low_memory=False,
                         usecols=["match_id", "round_id", "start_probability"])
    leverage = frame.drop_duplicates(["match_id", "round_id"])[
        ["match_id", "round_id", "leverage"]]
    merged = rounds.merge(leverage, on=["match_id", "round_id"], how="inner")
    if len(merged) != len(rounds):
        raise ValueError("%d of %d rounds have no leverage to pair with a start probability"
                         % (len(rounds) - len(merged), len(rounds)))
    # |q0 - p| is unchanged by the attack/focal flip, so the step is the same number whichever
    # side the curve is drawn from.
    step = (merged["start_probability"] - NEUTRAL_ROUND_P).abs() * merged["leverage"]
    return {
        "neutral_round_p": NEUTRAL_ROUND_P,
        "round_start_sd": float(rounds["start_probability"].std()),
        "boundary_step_median": float(step.median()),
        "boundary_step_max": float(step.max()),
        "boundary_step_rounds": int(len(step)),
    }


def duel_tag_coverage(work: Path, frame: pd.DataFrame) -> Dict[str, Any]:
    """How much of the duel-tag stream lands on a credited round-player.

    ``duel_roles.py`` partitions the kill feed, so it can earn a tag for a player the ledger
    credits nothing to in that round -- a clutch lost without firing is the modal case.  Those rows
    have no round-player row to attach to and the match payload drops them.  The caveat quotes the
    size of that drop, so it is counted here off the same two files the payload is built from
    rather than written down once and left to go stale when the slice grows.
    """
    duels = pd.read_csv(work / "out" / "duel_roles.csv", low_memory=False)
    credited = set(
        (str(match), int(rnd), str(puuid))
        for match, rnd, puuid in zip(frame["match_id"], frame["round_id"], frame["puuid"])
    )
    attached = [
        (str(match), int(rnd), str(puuid)) in credited
        for match, rnd, puuid in zip(duels["match_id"], duels["round_id"], duels["puuid"])
    ]
    missing = duels.loc[[not ok for ok in attached]]
    counts: Counter = Counter()
    for value in missing["tags"].astype(str):
        counts.update(tag for tag in value.split(";") if tag)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    parts = ["%s %s" % (format(count, ","), tag) for tag, count in ordered]
    if len(parts) > 1:
        breakdown = "%s and %s" % (", ".join(parts[:-1]), parts[-1])
    else:
        breakdown = parts[0] if parts else "none"
    return {
        "duel_tag_rows": int(len(duels)),
        "duel_tag_attached": int(sum(attached)),
        "duel_tag_missing": int(len(missing)),
        "duel_tag_missing_share": (100.0 * len(missing) / len(duels)) if len(duels) else 0.0,
        "duel_tag_missing_breakdown": breakdown,
        "duel_tag_missing_rounds": int(
            missing.drop_duplicates(["match_id", "round_id"]).shape[0]),
    }


def weapon_column_shape(frame: pd.DataFrame) -> Dict[str, Any]:
    """What a weapon ICON column would actually look like in each of the two places it could go.

    The two places are not the same object and the measurement says so.

    In a ``by weapon`` breakdown every row is a DISTINCT weapon -- that is what a breakdown is --
    so an icon column there is n shapes for n rows and the icon is a direct handle on the row.

    In the round ledger the column is ten seats in one round, and this counts what that column
    repeats: the share of a round's named weapon cells taken by that round's most common weapon,
    and by its two most common.  A column that is half one glyph is texture, and the two weapons
    that make it up are also the two that recur across the whole act, so the shape they share at
    render size (measured in ``image_facts``) decides whether the repeat is even readable.
    """
    named = frame.loc[frame["weapon"].notna(), ["match_id", "round_id", "weapon"]]
    overall = named["weapon"].value_counts()
    # The other column, counted the same way: how many icons the breakdown decision actually
    # creates.  ``Other`` is a grouping and has no file, so it is not counted as one.
    breakdown_cells = 0
    for puuid, _, _ in FOCAL:
        keys = weapon_keys(frame.loc[frame["puuid"] == puuid], WEAPON_MIN_ROUNDS)
        breakdown_cells += int(keys.loc[keys != "Other"].nunique())
    shares, distinct = [], []
    for _, part in named.groupby(["match_id", "round_id"], sort=False):
        counts = part["weapon"].value_counts()
        distinct.append(len(counts))
        shares.append((counts.iloc[0] / counts.sum(),
                       counts.iloc[:2].sum() / counts.sum()))
    return {
        "weapon_pair": [str(name) for name in overall.index[:2]],
        "weapon_top_name": str(overall.index[0]),
        "weapon_top_share": float(100.0 * overall.iloc[0] / overall.sum()),
        "weapon_pair_share": float(100.0 * overall.iloc[:2].sum() / overall.sum()),
        "weapon_distinct": int(len(overall)),
        "weapon_ledger_cells": int(len(named)),
        "weapon_breakdown_cells": breakdown_cells,
        "weapon_panel_distinct_median": float(np.median(distinct)),
        "weapon_panel_modal_median": float(100.0 * np.median([a for a, _ in shares])),
        "weapon_panel_top2_median": float(100.0 * np.median([b for _, b in shares])),
    }


def image_facts(assets: Dict[str, Any], confusable: Sequence[str]) -> Dict[str, Any]:
    """Every family's measurement, taken from the harness that guards it rather than retyped.

    ``contrast.py`` is the file that fails the build when artwork stops being legible, so it is
    also the file the caveats quote.  One measurement, two consumers: nothing on the page can
    drift away from what the checker actually measured.  Every fact below is keyed by family, so
    a caveat naming a number for a family that stopped shipping is a KeyError and not a stale
    sentence.
    """
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import contrast  # noqa: E402  (a sibling script, not a package)

    contrast.image_report(quiet=True)
    facts: Dict[str, Any] = {
        "image_floor": contrast.IMAGE_FLOOR,
        "mark_floor": contrast.MARK_FLOOR,
        "image_alpha": contrast.IMAGE_ALPHA,
    }
    # THE MEASUREMENT THAT KEPT THE ROUND LEDGER AS WORDS.  Two silhouettes that cover the same
    # pixels of the same slot do not discriminate, whatever they depict.  Measured at the size
    # the stylesheet ships them at, on the two weapons that are half of every ledger column.
    if len(confusable) == 2:
        folder = Path(__file__).resolve().parent / "assets" / "weapon"
        box = contrast.render_box(
            Path(__file__).resolve().parent / "quad-site.css", "--weapon-art-w", "--icon-art")
        facts["weapon_render_box"] = "%d×%d" % box
        facts["weapon_confusable_iou"] = contrast.silhouette_overlap(
            folder, re.sub(r"[^a-z0-9]+", "-", confusable[0].lower()).strip("-"),
            re.sub(r"[^a-z0-9]+", "-", confusable[1].lower()).strip("-"), box)
    for family in assets:
        summary = contrast.image_report.summary.get(family)
        if not summary:
            raise ValueError("contrast.py measured no %s artwork; the folder is missing"
                             % family)
        clear = summary["clear_share"]
        # The surface labels differ per family -- agent and rank land on the page, weapon lands
        # on the plate -- so the worst and best labelled surfaces are found rather than named.
        worst = min(clear, key=lambda label: clear[label])
        best = max(clear, key=lambda label: clear[label])
        facts.update({
            "%s_files" % family: summary["files"],
            "%s_mark_grade" % family: summary["mark_grade"],
            "%s_worst_surface" % family: worst.replace("--", ""),
            "%s_best_surface" % family: best.replace("--", ""),
            "%s_clear_worst" % family: clear[worst],
            "%s_clear_best" % family: clear[best],
            "%s_family_worst" % family: summary["family_worst"],
            "%s_slot_ratio" % family: summary["slot"],
            "%s_intrinsic_px" % family: assets[family]["intrinsic_px"],
            "%s_faintest" % family: summary["faintest"][0][1],
            "%s_faintest_ratio" % family: summary["faintest"][0][0],
        })
    return facts


def collect_facts(
    frame: pd.DataFrame,
    context: Dict[str, Any],
    players: Sequence[Dict[str, Any]],
    arguments: argparse.Namespace,
    ladder: Dict[str, Any],
) -> Dict[str, Any]:
    """Everything the dictionary and the caveats quote, measured off the frame."""
    focal = frame.loc[frame["is_focal"]]
    rates = [row["rate"] for row in players if row["rate"] is not None]
    sd = float(frame["mwpa"].std())
    above = [row["short"] for row in players if row["rounds"] >= ROUNDS_TO_EXCLUDE_ZERO]
    if above:
        above_text = ("Of the four, %s clear%s that threshold; the rest do not."
                      % (" and ".join(above), "" if len(above) > 1 else "s"))
    else:
        above_text = "None of the four clears that threshold in this act."

    key = ["match_id", "round_id"]
    pairs = {}
    for puuid, _, short in FOCAL:
        mine = set(map(tuple, focal.loc[focal["puuid"] == puuid, key].values))
        pairs[short] = mine
    shared = {}
    for a in pairs:
        for b in pairs:
            if a < b:
                shared[(a, b)] = len(pairs[a] & pairs[b])
    busiest = max(shared, key=lambda k: shared[k])
    empty = sorted(k for k in shared if shared[k] == 0)
    synergy_text = (
        "%s and %s are the only pairing with real shared exposure, at %s shared rounds"
        % (busiest[0], busiest[1], format(shared[busiest], ","))
    )
    if empty:
        synergy_text += "; %s never shared a round in this act, and that cell is null, not zero." \
            % ", ".join("%s and %s" % pair for pair in empty)
    else:
        synergy_text += ", and every other pairing is thin enough that its interval says so."

    rounds = frame.drop_duplicates(["match_id", "round_id", "side"])
    eco = rounds.loc[rounds["buy_class"] == BUY_ORDER[0], "round_won"]

    covering = sum(1 for row in players if row["covers_zero"])
    if covering == len(players):
        covers_zero_text = "All four intervals cover zero."
    elif covering == 1:
        covers_zero_text = "One of the four intervals covers zero."
    else:
        covers_zero_text = "%d of the four intervals cover zero." % covering

    seam = boundary_seam(arguments.work, frame)

    # How many of the names in a match row are not a handle a reader can hold. It is the whole
    # reason one folder of artwork ships, so it is counted rather than assumed.
    seats = frame.drop_duplicates(["match_id", "puuid"])
    anonymous = seats.groupby("match_id")["is_focal"].agg(lambda flags: int((~flags).sum()))
    roster = int(seats.groupby("match_id").size().max())
    low, high = int(anonymous.min()), int(anonymous.max())
    anonymous_text = ("%d of the %d" % (low, roster) if low == high
                      else "%d to %d of the %d" % (low, high, roster))

    ledger = weapon_column_shape(frame)

    return {
        **ledger,
        "act": context["act"],
        "matches": int(frame["match_id"].nunique()),
        "rounds": int(frame[["match_id", "round_id"]].drop_duplicates().shape[0]),
        "round_players": int(len(frame)),
        "players": int(frame["puuid"].nunique()),
        "bootstrap": arguments.bootstrap,
        "seed": arguments.seed,
        "confidence": arguments.confidence,
        "mean_leverage": float(frame["leverage"].mean()),
        "rate_floor_marker_rounds": THIN_ROUNDS,
        "weapon_min_rounds": WEAPON_MIN_ROUNDS,
        "covers_zero_text": covers_zero_text,
        "mwpa_sd": sd,
        "thin_noise_se": 100.0 * sd / np.sqrt(THIN_ROUNDS),
        "player_rate_spread": (max(rates) - min(rates)) if rates else float("nan"),
        "component_sum": float(
            sum(focal["mwpa_" + credit].sum() for credit in CREDIT_TYPES)),
        "headline_sum": float(focal["mwpa"].sum()),
        "above_threshold_text": above_text,
        "synergy_text": synergy_text,
        "eco_win_rate": float(eco.mean()),
        # The ladder, and the imagery. Both are measurements the caveats quote verbatim.
        "placement_matches": ladder["placement"]["matches"],
        "placement_holders": ladder["placement"]["holders"],
        "placement_share_text": format(100.0 * ladder["placement"]["share_of_act"], ".1f"),
        "act_player_matches": ladder["placement"]["act_player_matches"],
        "tier_n": ladder["correlation"]["n"],
        "tier_minimum_ranked": ladder["correlation"]["minimum_ranked"],
        "r_tier_mwpa": ladder["correlation"]["r_mwpa"],
        "r_tier_lobby_adjustment": ladder["correlation"]["r_lobby_adjustment"],
        "r_tier_lobby_adjustment_rate": ladder["correlation"]["r_lobby_adjustment_rate"],
        "lobby_spread_median": ladder["correlation"]["lobby_spread_median"],
        "lobby_spread_max": ladder["correlation"]["lobby_spread_max"],
        "anonymous_per_match_text": anonymous_text,
        **image_facts(ladder["assets"], ledger["weapon_pair"]),
        **seam,
        "surrendered_rounds": context["surrendered_rounds"],
        **scoring_provenance(arguments.work),
        **duel_tag_coverage(arguments.work, frame),
    }


def write_json(path: Path, payload: Dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return len(text) + 1


# --------------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Emit site.json and the four player payloads")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "payload")
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--confidence", type=float, default=CONFIDENCE)
    arguments = parser.parse_args()

    if not (LAB / "data" / RELEASE).is_dir():
        raise ValueError("pinned release %s is not on disk" % RELEASE)

    frame = load_frame(arguments.work / "out" / "mwpa_round_players.csv")
    match_ids = sorted(frame["match_id"].unique().tolist())
    context = load_match_context(arguments.database, match_ids)
    index = match_index(frame, context)
    bootstrapper = Bootstrapper(match_ids, arguments.bootstrap, arguments.seed,
                                arguments.confidence)

    ladder = build_ladder(frame, index, arguments.database, match_ids, ASSET_DIR)
    for family, assets in sorted(ladder["assets"].items()):
        print("%-7s artwork  %d files, %d names mapped"
              % (family, len(assets["files"]) + len(assets["unused"]), len(assets["files"])))
        if assets["missing"]:
            # Not fatal, and deliberately so: this is the property that makes a broken image
            # impossible.  A name with no file renders the word alone, which is the same thing
            # the identity control does to every name at once.
            print("        no file for %s — those cells render the word alone"
                  % ", ".join(assets["missing"]))
        if assets["unused"]:
            # Fatal, and deliberately so: art on disk that nothing in the act can reach is the
            # first form of the folder that reappears, and build.py refuses that too.
            raise ValueError("%s artwork on disk that nothing in the act uses: %s"
                             % (family, ", ".join(assets["unused"])))

    players = [
        {"puuid": puuid, "name": name, "short": short, "rank": 0,
         **headline(bootstrapper, frame.loc[frame["puuid"] == puuid])}
        for puuid, name, short in FOCAL
    ]
    facts = collect_facts(frame, context, players, arguments, ladder)

    site = build_site(frame, bootstrapper, context, index, players, facts, ladder)
    written = [(arguments.output_dir / "site.json",
                write_json(arguments.output_dir / "site.json", site))]

    print("headline (impact per match with its interval, then the estimator's own rate)")
    for row in site["players"]:
        print("  %d %-10s %-24s %+7.1f%% [%+7.1f%%, %+7.1f%%]  rate %8s  %6d rounds %4d matches"
              "  covers_zero=%s"
              % (row["rank"], row["short"], row["name"],
                 100.0 * row["impact"], 100.0 * row["impact_lo"], 100.0 * row["impact_hi"],
                 row["rate"], row["rounds"], row["matches"], row["covers_zero"]))

    print("\nladder (placement window %d matches, ladder %d divisions)"
          % (ladder["placement"]["matches"], len(ladder["order"])))
    for _, _, short in FOCAL:
        summary = ladder["summaries"][short]
        print("  %-10s %s -> %s  (%d in placement, %d up, %d down)"
              % (short, summary["first"], summary["last"], summary["placement"],
                 summary["steps_up"], summary["steps_down"]))
    print("  r(lobby division, match MWPA) = %+.3f over n=%d"
          % (ladder["correlation"]["r_mwpa"], ladder["correlation"]["n"]))

    print("\nbreakdown cells (thin in brackets)")
    for puuid, name, short in FOCAL:
        payload = build_player(frame, bootstrapper, context, index, puuid, name, short, ladder)
        path = arguments.output_dir / "player" / ("%s.json" % short)
        written.append((path, write_json(path, payload)))
        parts = []
        for dimension, cells in payload["breakdowns"].items():
            thin = sum(1 for cell in cells if cell["thin"])
            parts.append("%s %d[%d]" % (dimension, len(cells), thin))
        synergy_thin = sum(1 for row in payload["synergy"] if row["thin"])
        parts.append("synergy %d[%d]" % (len(payload["synergy"]), synergy_thin))
        print("  %-10s matches %2d  %s" % (short, len(payload["matches"]), "  ".join(parts)))

    print("\nwritten")
    for path, size in written:
        print("  %-72s %s bytes" % (path, format(size, ",")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
