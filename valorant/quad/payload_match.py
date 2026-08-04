"""Emit ``payload/match/<match_id>.json``, one file per match, per ``CONTRACT.md``.

Everything in a match file is written from the focal side's point of view -- the team the focal
player or players are on.  The two probability sources on disk are attack-perspective, so
``match_wp``, ``events`` and ``top_plays`` all pass through :func:`focal_probability` on the way
out.  Doing the flip here rather than in the view is the point: a page that has to know which team
was attacking in round 14 before it can draw a line will eventually draw it upside down.

The three quantities on a round player are not interchangeable and the contract names all three.
``rwpa`` is the player's own credit in round-win-probability points; ``rwpa_centered`` subtracts
the mean credit of the other players in that round, which is what makes the round sum to zero;
``mwpa`` is that centered credit times the round's leverage, in match-win-probability points.  The
five named components are the leverage-weighted *uncentered* parts, so they sum to ``rwpa`` times
leverage and not to ``mwpa``.  They are in match units on purpose: a ``top_plays`` entry is a
single ledger row measured the same way, and it has to sit inside the component it belongs to.

``match_wp`` is a reconciliation and not an identity.  The last round's ``wp_after`` is a structural
probability from the score, not the result, and the two differ often enough that asserting equality
would fail on this corpus.  Nothing here asserts it.

Abilities are absent at every grain in this data, so no key is emitted for them; ``meta.cav``
carries the reason on the site side.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd

LAB = Path("/Users/andrewpark/Desktop/Rome/Sports/Esports/Valorant/valorant-impact-lab")
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from valorant_impact.match_leverage import (  # noqa: E402
    match_win_probability,
    round_leverage,
    score_before_round,
)
from valorant_impact.mwpa import buy_class  # noqa: E402

# Same two pins as payload_site.py, and they move together — see the note there on why the work
# set is no longer a /private/tmp session scratchdir, and on what the leverage literal guards.
WORK = LAB / "data" / "quad_work_2026-08-04"
DATABASE = LAB / "data" / "valorant_matches_v16.sqlite3"
MEAN_LEVERAGE = 0.16178885296288456
TOP_PLAYS = 3

FOCAL = {
    "ab8bf38e-c2c4-5408-9a96-90ee3eb01af9": "martin",
    "7b17dc93-bba8-50f3-ba4f-7e753d901a65": "snorlax",
    "82d91329-7a9d-5d30-ac3f-5cd2e4764d15": "themarias",
    "bafecb36-4e90-5f84-adc7-04d6acb22dfa": "trzzcko",
}

CREDIT_TYPES = ("kill_credit", "death_debit", "plant", "defuse", "alive_clock")

ROUND_PLAYER_COLUMNS = (
    "match_id", "round_id", "puuid", "player", "team", "agent", "is_focal", "side",
    "rwpa", "rwpa_centered", "mwpa", "leverage", "weapon", "player_loadout",
    "remaining_credits", "round_kills", "round_damage", "round_player_count",
    "active_player_count",
) + tuple("mwpa_" + credit for credit in CREDIT_TYPES)

ROUND_COLUMNS = (
    "match_id", "round_id", "round_number", "score_diff", "attack_team", "winning_team",
    "terminal_type", "attack_loadout_k", "defense_loadout_k", "active_player_count",
    # The continuous curve needs where the round started and when it ended: `start_probability`
    # is the model's price on the round before anybody acts, and `terminal_time_ms` is the
    # horizon each round's x axis is normalised against so every round gets equal width.
    "start_probability", "terminal_time_ms",
)

EVENT_COLUMNS = (
    "match_id", "round_id", "event_index", "event_type", "time_ms", "actor_puuid",
    "victim_puuid", "probability_before_action", "probability_after_action",
)

LEDGER_COLUMNS = (
    "match_id", "round_id", "event_index", "puuid", "player", "team", "credit_type",
    "rwpa", "probability_before", "probability_after", "headline_eligible",
)


# --------------------------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------------------------

def _require(frame: pd.DataFrame, columns: Sequence[str], name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError("%s is missing columns: %s" % (name, ", ".join(missing)))


def load_round_players(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    _require(frame, ROUND_PLAYER_COLUMNS, "round-player artifact")
    frame["is_focal"] = frame["is_focal"].astype(bool)

    residual = frame.groupby(["match_id", "round_id"])["rwpa_centered"].sum().abs().max()
    if residual > 1e-9:
        raise ValueError("centered credit does not sum to zero within a round: %s" % residual)
    mean_leverage = float(frame["leverage"].mean())
    if abs(mean_leverage - MEAN_LEVERAGE) > 1e-12:
        raise ValueError("mean leverage %r is not the frozen %r" % (mean_leverage, MEAN_LEVERAGE))
    return frame


def load_rounds(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=list(ROUND_COLUMNS), low_memory=False)
    _require(frame, ROUND_COLUMNS, "round table")
    scores = frame.apply(
        lambda row: score_before_round(int(row["round_number"]), int(row["score_diff"])),
        axis=1, result_type="expand",
    )
    frame["attack_score_before"] = scores[0].astype(int)
    frame["defense_score_before"] = scores[1].astype(int)
    if frame["winning_team"].isna().any():
        raise ValueError("a round has no winning team")
    return frame


def load_events(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=list(EVENT_COLUMNS), low_memory=False)
    _require(frame, EVENT_COLUMNS, "event values")
    return frame.sort_values(["match_id", "round_id", "event_index"])


def load_ledger(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=list(LEDGER_COLUMNS), low_memory=False)
    _require(frame, LEDGER_COLUMNS, "ledger")
    # The round-player artifact is built from the headline-eligible slice; top plays rank rows of
    # that same slice, so a play can never be larger than the component it is drawn from.
    return frame.loc[frame["headline_eligible"].astype(bool)].copy()


def load_duels(path: Path) -> Dict[Tuple[str, int, str], List[str]]:
    frame = pd.read_csv(path)
    _require(frame, ("match_id", "round_id", "puuid", "tags"), "duel roles")
    return {
        (row.match_id, int(row.round_id), row.puuid): row.tags.split(";")
        for row in frame.itertuples()
    }


def load_context(database: Path, match_ids: Sequence[str]) -> Dict[str, Any]:
    placeholders = ",".join("?" * len(match_ids))
    with sqlite3.connect(str(database)) as connection:
        # `round_count` counts every round the match record has, including any that were AWARDED
        # by a surrender rather than played.  The scored slice only ever contains played rounds,
        # so the number the check below has to agree with is the difference, not the raw count.
        matches = pd.read_sql(
            "select m.match_id, m.started_at, m.map, m.round_count,"
            " m.round_count - (select count(*) from rounds r where r.match_id = m.match_id"
            "   and r.result = 'Surrendered') as played_round_count"
            " from matches m where m.match_id in (%s)"
            % placeholders, connection, params=list(match_ids))
        teams = pd.read_sql(
            "select match_id, team_id, rounds_won, won from team_results where match_id in (%s)"
            % placeholders, connection, params=list(match_ids))
        box = pd.read_sql(
            "select match_id, puuid, kills, deaths, assists, damage_dealt, tier"
            " from player_matches where match_id in (%s)" % placeholders,
            connection, params=list(match_ids))
    if len(matches) != len(match_ids):
        raise ValueError("the database is missing %d of the matches"
                         % (len(match_ids) - len(matches)))
    return {
        "matches": matches.set_index("match_id"),
        "teams": teams,
        "box": box.set_index(["match_id", "puuid"]),
        "ladder": load_ladder(),
    }


def load_ladder() -> Dict[str, int]:
    """The division ladder, read from the payload that owns it.

    ``payload_site.py`` reads Riot's own enum off the corpus and emits it as
    ``meta.gate.tier_order``.  Reading it back here rather than re-deriving it means there is
    exactly one ladder in the payload and no way for the two halves to disagree about what beats
    what.  It also means the match half is built after the site half, which it already was.
    """
    path = Path(__file__).resolve().parent / "payload" / "site.json"
    if not path.exists():
        raise ValueError("run payload_site.py first: %s carries the ladder" % path)
    order = json.loads(path.read_text(encoding="utf-8"))["meta"]["gate"]["tier_order"]
    return {entry["name"]: index + 1 for index, entry in enumerate(order)}


# --------------------------------------------------------------------------------------------
# the focal frame
# --------------------------------------------------------------------------------------------

def focal_team_of(players: pd.DataFrame) -> str:
    """The team the focal player or players are on. Never ambiguous in this act slice."""
    teams = sorted(players.loc[players["is_focal"], "team"].unique().tolist())
    if len(teams) != 1:
        raise ValueError("expected the focal players on one team, found %r" % (teams,))
    return teams[0]


def focal_probability(probability: float, focal_is_attack: bool) -> float:
    """Attack-perspective probability, restated for the focal side."""
    return float(probability) if focal_is_attack else 1.0 - float(probability)


# --------------------------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------------------------

def build_teams(teams: pd.DataFrame, focal_team: str) -> List[Dict[str, Any]]:
    rows = [
        {
            "team_id": row.team_id,
            "rounds_won": int(row.rounds_won),
            "won": bool(row.won),
            "focal": row.team_id == focal_team,
        }
        for row in teams.itertuples()
    ]
    rows.sort(key=lambda team: (not team["focal"], team["team_id"]))
    return rows


def build_players(
    players: pd.DataFrame,
    box: pd.DataFrame,
    focal_team: str,
) -> List[Dict[str, Any]]:
    grouped = players.groupby("puuid", sort=False)
    rows = []
    for puuid, part in grouped:
        first = part.iloc[0]
        score = box.loc[(first["match_id"], puuid)]
        rows.append({
            "puuid": puuid,
            "name": first["player"],
            "short": FOCAL.get(puuid),
            "team": first["team"],
            "agent": first["agent"],
            "is_focal": bool(first["is_focal"]),
            "mwpa": float(part["mwpa"].sum()),
            "rwpa": float(part["rwpa"].sum()),
            "rounds": int(part["round_id"].nunique()),
            "kills": int(score["kills"]),
            "deaths": int(score["deaths"]),
            "assists": int(score["assists"]),
            "damage": int(score["damage_dealt"]),
        })
    # The focal side first, then by match MWPA within a side. Every round below reuses this
    # order, so line n of one round tab is the same player as line n of the next.
    rows.sort(key=lambda player: (player["team"] != focal_team, -player["mwpa"]))
    return rows


def build_lobby_tiers(
    match_id: str,
    match_players: Sequence[Dict[str, Any]],
    box: pd.DataFrame,
    ladder: Dict[str, int],
) -> Dict[str, Any]:
    """The range of divisions in this lobby, and how many of it had no rank issued yet.

    This is the ONLY division fact a match page gets, and it is deliberate. A per-player tier
    column would put a rank beside an MWPA on 68 pages, which is exactly the misreading
    ``meta.cav.tier_is_not_mwpa`` exists to prevent. The range answers the one question the page
    does ask -- *who was this match against* -- in one line, and the answer is that a lobby is not
    division-homogeneous.
    """
    ranked, placement = [], 0
    for player in match_players:
        name = box.loc[(match_id, player["puuid"]), "tier"]
        position = ladder.get(str(name))
        if position is None:
            placement += 1
        else:
            ranked.append((position, str(name)))
    if not ranked:
        return {"low": None, "high": None, "ranked": 0, "placement": placement}
    ranked.sort()
    # No `spread` field: the two division names ARE the spread, and a number nothing renders is
    # an invitation to a later contributor to find it a column.
    return {
        "low": ranked[0][1],
        "high": ranked[-1][1],
        "ranked": len(ranked),
        "placement": placement,
    }


def build_match_wp(rounds: pd.DataFrame, focal_team: str) -> List[Dict[str, Any]]:
    series = []
    for row in rounds.itertuples():
        focal_is_attack = row.attack_team == focal_team
        own = int(row.attack_score_before if focal_is_attack else row.defense_score_before)
        other = int(row.defense_score_before if focal_is_attack else row.attack_score_before)
        won = row.winning_team == focal_team
        leverage = round_leverage(own, other)
        series.append({
            "round_number": int(row.round_number),
            "own": own,
            "other": other,
            "wp_before": match_win_probability(own, other),
            "wp_after": match_win_probability(own + int(won), other + int(not won)),
            "won": bool(won),
            "leverage": leverage,
            "li": leverage / MEAN_LEVERAGE,
        })
    return series


def build_wp_series(
    round_table: pd.DataFrame,
    events: pd.DataFrame,
    focal_team: str,
) -> List[Dict[str, Any]]:
    """One continuous match win probability curve that moves *inside* rounds.

    Conditioning on how the current round ends gives the whole curve in one line.  With the score
    at ``(a, b)`` and the focal side holding round-win probability ``q``::

        P(match) = (1 - q) * W(a, b+1) + q * W(a+1, b)
                 = W(a, b+1) + q * L(a, b)

    so the curve is the round-win probability the RWPA model already produces, affinely mapped onto
    the match by the round's own leverage.  Three properties come free and each is asserted below:

    * ``q = 1`` lands exactly on ``W(a+1, b)`` and ``q = 0`` on ``W(a, b+1)``, so the curve meets the
      round boundary at the same value the discrete per-round series had.  Nothing is approximated.
    * ``dP/dq = L(a, b)``.  The slope of this curve *is* the leverage, which means a credited
      action's vertical movement here is exactly its raw MWPA.  The chart and the metric are the
      same object seen two ways -- a kill that moves the line two points moved the match two points.
    * Summing every node's ``dp`` over the match telescopes to ``W(final) - W(0, 0)``.

    Four node kinds, because they are four different claims:

    ``round_start``  the buy is known and the model prices the round.  This is a real move and it is
                     usually the largest one nobody did: round-start q has sd 0.153 across the act,
                     so an eco round opens with the match already leaning away.  It is attributable
                     to the economy, never to a player, and it carries no MWPA.
    ``clock``        probability drifting between credited actions, from the alive-clock component.
    ``action``       a kill, plant or defuse.  ``dp`` here is the event's raw match impact.
    ``terminal``     the round resolves.  The gap from the last action to here is the model's own
                     calibration error at the terminal, which the ledger books to a team side rather
                     than to a player.  It is drawn, not smoothed away.
    """
    by_round = dict(list(events.groupby("round_id", sort=False)))
    nodes: List[Dict[str, Any]] = []
    for row in round_table.itertuples():
        focal_is_attack = row.attack_team == focal_team
        own = int(row.attack_score_before if focal_is_attack else row.defense_score_before)
        other = int(row.defense_score_before if focal_is_attack else row.attack_score_before)
        won = row.winning_team == focal_team
        number = int(row.round_number)
        lose = match_win_probability(own, other + 1)
        win = match_win_probability(own + 1, other)
        span = float(lose)
        reach = float(win) - span

        def project(q: float) -> float:
            return span + q * reach

        frame = by_round.get(int(row.round_id))
        times = [int(t) for t in frame["time_ms"]] if frame is not None else []
        horizon = float(max(times + [int(row.terminal_time_ms or 0), 1]))

        def place(t: float) -> float:
            return (number - 1) + min(1.0, max(0.0, t / horizon))

        previous = nodes[-1]["p"] if nodes else match_win_probability(0, 0)

        def emit(kind, t, q, **extra):
            nonlocal previous
            p = project(q)
            node = {
                "r": number, "t": int(t), "x": place(t), "q": q, "p": p,
                "kind": kind, "dp": p - previous,
            }
            node.update(extra)
            nodes.append(node)
            previous = p

        emit("round_start", 0, focal_probability(row.start_probability, focal_is_attack),
             own=own, other=other, leverage=reach)
        if frame is not None:
            for event in frame.itertuples():
                before = focal_probability(event.probability_before_action, focal_is_attack)
                after = focal_probability(event.probability_after_action, focal_is_attack)
                emit("clock", event.time_ms, before, ei=int(event.event_index))
                emit("action", event.time_ms, after,
                     ei=int(event.event_index),
                     type=event.event_type,
                     actor=None if pd.isna(event.actor_puuid) else event.actor_puuid,
                     victim=None if pd.isna(event.victim_puuid) else event.victim_puuid)
        emit("terminal", horizon, 1.0 if won else 0.0,
             terminal_type=row.terminal_type, won=bool(won))

        landing = nodes[-1]["p"]
        expected = win if won else lose
        if abs(landing - expected) > 1e-12:
            raise ValueError(
                "round %d does not land on its resolved match probability: %r vs %r"
                % (number, landing, expected))
    return nodes


def build_buy(row: Any, teams: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Both sides' round-start loadout, from the round table rather than from credited players.

    A round where a player earned no eligible ledger row still has a full economy, so the buy
    block is read from the side totals that are recorded for every round.
    """
    buy = []
    for team in teams:
        attacking = team["team_id"] == row.attack_team
        loadout = float(row.attack_loadout_k if attacking else row.defense_loadout_k) * 1000.0
        buy.append({
            "team_id": team["team_id"],
            "side": "attack" if attacking else "defense",
            "loadout": loadout,
            "class": buy_class(loadout),
        })
    return buy


def build_events(events: pd.DataFrame, focal_is_attack: bool) -> List[Dict[str, Any]]:
    rows = []
    for event in events.itertuples():
        before = focal_probability(event.probability_before_action, focal_is_attack)
        after = focal_probability(event.probability_after_action, focal_is_attack)
        rows.append({
            "i": int(event.event_index),
            "t": int(event.time_ms),
            "type": event.event_type,
            "actor": None if pd.isna(event.actor_puuid) else event.actor_puuid,
            "victim": None if pd.isna(event.victim_puuid) else event.victim_puuid,
            "p_before": before,
            "p_after": after,
            "delta": after - before,
        })
    return rows


def build_round_players(
    players: pd.DataFrame,
    order: Dict[str, int],
    duels: Dict[Tuple[str, int, str], List[str]],
) -> List[Dict[str, Any]]:
    rows = []
    for player in players.itertuples():
        key = (player.match_id, int(player.round_id), player.puuid)
        rows.append({
            "puuid": player.puuid,
            "team": player.team,
            "agent": player.agent,
            "side": player.side,
            "rwpa": float(player.rwpa),
            "rwpa_centered": float(player.rwpa_centered),
            "mwpa": float(player.mwpa),
            "kill_credit": float(player.mwpa_kill_credit),
            "death_debit": float(player.mwpa_death_debit),
            "plant": float(player.mwpa_plant),
            "defuse": float(player.mwpa_defuse),
            "alive_clock": float(player.mwpa_alive_clock),
            "duel": duels.get(key, []),
            "weapon": None if pd.isna(player.weapon) else player.weapon,
            "loadout": int(player.player_loadout),
            "credits": int(player.remaining_credits),
            "kills": int(player.round_kills),
            "damage": int(player.round_damage),
        })
    rows.sort(key=lambda row: order[row["puuid"]])
    return rows


def build_rounds(
    round_table: pd.DataFrame,
    players: pd.DataFrame,
    events: pd.DataFrame,
    duels: Dict[Tuple[str, int, str], List[str]],
    teams: Sequence[Dict[str, Any]],
    order: Dict[str, int],
    focal_team: str,
) -> List[Dict[str, Any]]:
    by_round_players = dict(list(players.groupby("round_id", sort=False)))
    by_round_events = dict(list(events.groupby("round_id", sort=False)))
    rounds = []
    for row in round_table.itertuples():
        focal_is_attack = row.attack_team == focal_team
        own = int(row.attack_score_before if focal_is_attack else row.defense_score_before)
        other = int(row.defense_score_before if focal_is_attack else row.attack_score_before)
        round_id = int(row.round_id)
        leverage = round_leverage(own, other)
        rounds.append({
            "round_id": round_id,
            "round_number": int(row.round_number),
            "terminal_type": row.terminal_type,
            "winning_team": row.winning_team,
            "own": own,
            "other": other,
            "leverage": leverage,
            "li": leverage / MEAN_LEVERAGE,
            "buy": build_buy(row, teams),
            "events": build_events(
                by_round_events.get(round_id, events.iloc[0:0]), focal_is_attack),
            "players": build_round_players(
                by_round_players[round_id], order, duels),
        })
    return rounds


def build_top_plays(
    ledger: pd.DataFrame,
    round_table: pd.DataFrame,
    focal_team: str,
) -> List[Dict[str, Any]]:
    """The three largest single ledger rows by absolute match impact, signed.

    A row's match impact is its own credit times the round's leverage, which is why a duel at
    12-12 outranks the same duel at 12-3.  Deaths are ranked alongside kills: the death debit is
    most of a player's absolute ledger and filtering it out would rank a highlight reel.  A kill
    and the death it caused are two rows and can both make the three, which is what ranking rows
    rather than events means.

    ``mwpa`` is the credited player's own, so it is positive when the play helped that player's
    team.  ``p_before`` and ``p_after`` stay on the focal-side axis the round panel is drawn on,
    so an opponent's good play reads as a positive ``mwpa`` against a falling probability.
    """
    context = round_table.set_index("round_id")
    plays = []
    for row in ledger.itertuples():
        round_id = int(row.round_id)
        meta = context.loc[round_id]
        focal_is_attack = meta["attack_team"] == focal_team
        own = int(meta["attack_score_before"] if focal_is_attack
                  else meta["defense_score_before"])
        other = int(meta["defense_score_before"] if focal_is_attack
                    else meta["attack_score_before"])
        leverage = round_leverage(own, other)
        plays.append({
            "round_number": int(meta["round_number"]),
            "puuid": row.puuid,
            "name": row.player,
            "type": row.credit_type,
            "mwpa": float(row.rwpa) * leverage,
            "leverage": leverage,
            "p_before": focal_probability(row.probability_before, focal_is_attack),
            "p_after": focal_probability(row.probability_after, focal_is_attack),
            "round_own": own,
            "round_other": other,
            "_key": (round_id, int(row.event_index), row.puuid, row.credit_type),
        })
    plays.sort(key=lambda play: (-abs(play["mwpa"]), play["_key"]))
    for play in plays[:TOP_PLAYS]:
        del play["_key"]
    return plays[:TOP_PLAYS]


def build_match(
    match_id: str,
    players: pd.DataFrame,
    round_table: pd.DataFrame,
    events: pd.DataFrame,
    ledger: pd.DataFrame,
    duels: Dict[Tuple[str, int, str], List[str]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """One match file. ``rounds`` is the round array.

    The contract sketch writes ``rounds`` twice, once as a count and once as the array of round
    objects.  A JSON object holds one of them, and the array is the one that cannot be recovered
    from the other: the count is ``rounds.length`` and ``site.json`` carries it in the index.
    """
    header = context["matches"].loc[match_id]
    focal_team = focal_team_of(players)

    if int(header["played_round_count"]) != len(round_table):
        raise ValueError(
            "%s: %d played rounds on the match row (%d total, %d surrendered) against %d in the "
            "round table" % (match_id, header["played_round_count"], header["round_count"],
                             int(header["round_count"]) - int(header["played_round_count"]),
                             len(round_table)))

    teams = build_teams(
        context["teams"].loc[context["teams"]["match_id"] == match_id], focal_team)
    match_players = build_players(players, context["box"], focal_team)
    order = {player["puuid"]: index for index, player in enumerate(match_players)}

    return {
        "match_id": match_id,
        "started_at": header["started_at"],
        "map": header["map"],
        "teams": teams,
        "players": match_players,
        "lobby_tiers": build_lobby_tiers(
            match_id, match_players, context["box"], context["ladder"]),
        "match_wp": build_match_wp(round_table, focal_team),
        "wp_series": build_wp_series(round_table, events, focal_team),
        "rounds": build_rounds(
            round_table, players, events, duels, teams, order, focal_team),
        "top_plays": build_top_plays(ledger, round_table, focal_team),
    }


# --------------------------------------------------------------------------------------------

def write_json(path: Path, payload: Dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return len(text) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit the per-match payload files")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "payload" / "match")
    arguments = parser.parse_args()

    frame = load_round_players(arguments.work / "out" / "mwpa_round_players.csv")
    rounds = load_rounds(arguments.work / "rwpa_crossfit_rounds.csv")
    events = load_events(arguments.work / "rwpa_crossfit_event_values.csv")
    ledger = load_ledger(arguments.work / "rwpa_crossfit_ledger.csv")
    duels = load_duels(arguments.work / "out" / "duel_roles.csv")

    match_ids = sorted(frame["match_id"].unique().tolist())
    context = load_context(arguments.database, match_ids)

    players_by_match = dict(list(frame.groupby("match_id", sort=False)))
    rounds_by_match = dict(list(rounds.groupby("match_id", sort=False)))
    events_by_match = dict(list(events.groupby("match_id", sort=False)))
    ledger_by_match = dict(list(ledger.groupby("match_id", sort=False)))

    written = total_rounds = total_round_players = total_events = total_bytes = 0
    uncredited = []
    for match_id in match_ids:
        round_table = rounds_by_match[match_id].sort_values("round_id")
        payload = build_match(
            match_id,
            players_by_match[match_id],
            round_table,
            events_by_match[match_id],
            ledger_by_match[match_id],
            duels,
            context,
        )
        total_bytes += write_json(arguments.output_dir / ("%s.json" % match_id), payload)
        written += 1
        total_rounds += len(payload["rounds"])
        for entry, row in zip(payload["rounds"], round_table.itertuples()):
            total_round_players += len(entry["players"])
            total_events += len(entry["events"])
            active = int(row.active_player_count)
            if len(entry["players"]) != active:
                uncredited.append((match_id, entry["round_id"], len(entry["players"]), active))

    # Fail closed on a silent drop: everything the inputs carry has to reach a file.
    if (written, total_rounds, total_round_players, total_events) != (
            len(match_ids), len(rounds), len(frame), len(events)):
        raise ValueError(
            "wrote %d matches / %d rounds / %d round players / %d events against"
            " %d / %d / %d / %d on the inputs"
            % (written, total_rounds, total_round_players, total_events,
               len(match_ids), len(rounds), len(frame), len(events)))

    credited = set(zip(frame["match_id"], frame["round_id"].astype(int), frame["puuid"]))
    attached = sum(1 for key in duels if key in credited)

    print("matches written      %d" % written)
    print("rounds               %d" % total_rounds)
    print("round players        %d" % total_round_players)
    print("events               %d" % total_events)
    print("duel tag rows        %d of %d attached" % (attached, len(duels)))
    print("bytes                %d  (mean %.1f KB per match)"
          % (total_bytes, total_bytes / written / 1024.0))
    if uncredited:
        # Not a defect to fix here: these players hold only out-of-support ledger rows, so the
        # MWPA artifact does not credit them and there is no measured row to render.
        print("rounds crediting fewer than the active set: %d" % len(uncredited))
        for match_id, round_id, players, active in uncredited:
            print("  %s round %d: %d credited of %d active"
                  % (match_id, round_id, players, active))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
