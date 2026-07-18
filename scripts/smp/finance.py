from __future__ import annotations

import argparse
import html
import json
import random
import math
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .core import (
    ALL_PLAYERS_BY_PID,
    esc,
    fmt_money,
    fmt_number,
    latest_rating,
    latest_team_season,
    phase_value,
    player_link,
    player_name,
    safe_float,
    safe_int,
    table_html,
    td,
    team_payroll,
)


def team_finances_table(roster: list[dict[str, Any]], season: int, data: dict[str, Any] | None = None, tid: int | None = None) -> str:
    highlight_season = season + 1
    seasons = list(range(season + 1, season + 6))  # upcoming five seasons (drop the finished one)
    players = sorted(
        roster,
        key=lambda p: (-safe_float((p.get("contract") or {}).get("amount"), 0.0), player_name(p)),
    )
    headers = ["Pos", "Name"] + [(str(s), "cur-season" if s == highlight_season else "") for s in seasons]
    rows = []
    totals = {s: 0.0 for s in seasons}
    under_contract = {s: 0 for s in seasons}

    def salary_for(player: dict[str, Any], salary_season: int) -> float:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        if salary_season > exp:
            return 0.0
        exact = [
            salary for salary in player.get("salaries", [])
            if isinstance(salary, dict) and safe_int(salary.get("season"), -1) == salary_season
        ]
        if exact:
            return safe_float(exact[-1].get("amount"), 0.0)
        return safe_float(contract.get("amount"), 0.0)

    for player in players:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        rating = latest_rating(player, season)
        cells = [
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(player_link(player, "../"), sort=player_name(player), cls="name-cell"),
        ]
        for s in seasons:
            season_amount = salary_for(player, s)
            if s <= exp and season_amount > 0:
                totals[s] += season_amount
                under_contract[s] += 1
                cells.append(td(fmt_money(season_amount), sort=season_amount, cls="cur-season" if s == highlight_season else ""))
            else:
                cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
        rows.append("".join(cells))

    # Dead money: released players whose contracts are still owed.
    if data is not None and tid is not None:
        for released in data.get("releasedPlayers", []):
            if safe_int(released.get("tid"), -10) != tid:
                continue
            contract = released.get("contract") or {}
            amount = safe_float(contract.get("amount"), 0.0)
            exp = safe_int(contract.get("exp"), season)
            ghost = ALL_PLAYERS_BY_PID.get(safe_int(released.get("pid"), -10))
            name = player_name(ghost) if ghost else f"Released player {released.get('pid')}"
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Waived; contract still owed">{esc(name)} <span class="muted small-copy">(dead money)</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and amount > 0:
                    totals[s] += amount
                    cells.append(td(fmt_money(amount), sort=amount, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    # Retained salary from trades: the payer keeps its share (+); the roster team gets a credit (−).
    if tid is not None:
        for pid, r in FIN_RETENTION.items():
            retained_player = ALL_PLAYERS_BY_PID.get(pid)
            if retained_player is None:
                continue
            held_by = safe_int(r.get("held_by"), -10)
            roster_tid = safe_int(retained_player.get("tid"), -11)
            if tid not in (held_by, roster_tid):
                continue
            signed = safe_float(r.get("amount"), 0.0) * (1 if tid == held_by else -1)
            exp = safe_int((retained_player.get("contract") or {}).get("exp"), season)
            name = player_name(retained_player)
            tag = "retained salary" if tid == held_by else f'retained by {r.get("note", "another team")}'
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Salary retained in a trade">{esc(name)} <span class="muted small-copy">({tag})</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and abs(signed) > 1e-9:
                    totals[s] += signed
                    cells.append(td(fmt_money(signed), sort=signed, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    counts_cells = [td(""), td("Under Contract", cls="name-cell total-label")]
    totals_cells = [td(""), td("Committed Salary", cls="name-cell total-label")]
    for s in seasons:
        cur = " cur-season" if s == highlight_season else ""
        counts_cells.append(td(fmt_number(under_contract[s], 0), sort=under_contract[s], cls=cur.strip()))
        totals_cells.append(td(fmt_money(totals[s]), sort=totals[s], cls=cur.strip()))
    rows.append(f'<tr class="total-row">{"".join(counts_cells)}</tr>')
    rows.append(f'<tr class="total-row">{"".join(totals_cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Salaries</h2>
        <span class="muted small-copy">Salary commitments through {seasons[-1]}</span>
      </div>
      {table_html(headers, rows, table_id="team-finances", empty_message="No contracts found.", wrap_cls="fit-table")}
    </section>
    """


# ---------- league finance model ----------
# All amounts in Basketball GM "thousands" units (300000 == $300M). No hard cap.
FIN_START = 75000       # every team starts the season with $75M
FIN_BASE = 160000       # base league payout: +$160M
FIN_PER_WIN = 2000      # +$2M per regular-season win
FIN_PLAYOFF = 15000     # +$15M for a playoff appearance
FIN_FINALS = 15000      # +$15M for a finals appearance
FIN_CHAMP = 15000       # +$15M for a championship (bonuses stack: champion earns 15+15+15=$45M)
FIN_SOFT_CAP = 300000   # soft cap: $1 luxury tax per $1 of payroll over $300M

# Manual cash adjustments outside the auto-computed ledger (thousands), keyed by tid.
# Cash that changes hands in a trade, since BBGM exports don't record it. Signed:
# negative = cash out, positive = cash in. ponytail: hand-maintained; add rows as trades happen.
FIN_ADJUSTMENTS: dict[int, dict[str, Any]] = {
    2: {"amount": -1000, "note": "Cash to Waltham (trade)"},    # Cambridge Platypuses
    6: {"amount":  1000, "note": "Cash from Cambridge (trade)"},  # Waltham Bears
}

# Salary retained in a trade: the original team keeps paying part of a traded player's
# salary while the player sits on the new roster at full contract. BBGM exports don't
# record retention, so we move the retained share (thousands/yr) off the roster team's
# books onto the payer's — for payroll, luxury tax, and the salaries table — every season
# through the contract's exp. Keyed by pid. ponytail: hand-maintained; add rows as trades happen.
FIN_RETENTION: dict[int, dict[str, Any]] = {
    # (Cody Williams pid 1789 was waived to free agency in the 2031 offseason, so Waltham's
    # old $17M retention no longer applies — that entry was removed.)
    # 2031 trade: Ajay Mitchell + Trae Young to the Gooners with Waltham paying them in FULL,
    # so the retained share equals each contract and the Gooners carry $0 for both.
    1765: {"held_by": 6, "amount": 21000, "note": "Waltham (trade)"},  # Ajay Mitchell (roster tid 5)
    1325: {"held_by": 6, "amount": 18000, "note": "Waltham (trade)"},  # Trae Young (roster tid 5)
}

# Cumulative bankroll each team carries into next season (thousands), keyed by tid.
# The auto ledger resets to FIN_START each year, so in the offseason (phase >= 8) we show
# this hand-kept balance instead. ponytail: hand-maintained; refresh once per offseason.
FIN_NEXT_BALANCE: dict[int, int] = {
    7: 396000,  # Stony Brook Stingrays
    4: 365000,  # Toronto Jays
    2: 345000,  # Cambridge Platypuses
    3: 336000,  # Queens Pigeons
    0: 331000,  # Durham Destroyers
    6: 290000,  # Waltham Bears      (310 − 20 sent to the Gooners in the 2031 Mitchell/Young trade)
    1: 308000,  # Rochester Dragons
    8: 287000,  # Manhattan Elephants
    9: 245000,  # Ithaca Thunder
    5: 98000,   # Gooning Gooners    (78 + 20 received from Waltham in that trade)
}

# The 2031 waivers, rookie repricing, and trades are now materialized in the
# canonical export. Site generation treats that file as authoritative.


def team_retention_delta(tid: int, season: int) -> float:
    """Net salary-retention adjustment to a team's payroll for ``season`` (thousands).

    The payer (``held_by``) carries its retained share; the roster team is relieved of it.
    Only counts while the player is still under contract (``season <= exp``).
    """
    delta = 0.0
    for pid, r in FIN_RETENTION.items():
        player = ALL_PLAYERS_BY_PID.get(pid)
        if not player:
            continue
        exp = safe_int((player.get("contract") or {}).get("exp"), season)
        if season > exp:
            continue
        amount = safe_float(r.get("amount"), 0.0)
        if safe_int(r.get("held_by"), -10) == tid:
            delta += amount                       # payer keeps this on their books
        if safe_int(player.get("tid"), -10) == tid:
            delta -= amount                       # roster team is relieved of it
    return delta


FIN_FINALS_GAMES_TO_WIN = 4  # ponytail: best-of-7 finals (this league); read games-to-win if the format changes


def playoff_status(data: dict[str, Any], tid: int, season: int) -> tuple[bool, bool, bool]:
    """(made_playoffs, made_finals, won_championship) for a team in a season.

    Read from ``playoffSeries``; during the regular season there is no series yet,
    so this returns all-False and the playoff bonuses stay $0 until earned.

    ``playoffSeries.series`` GROWS one round at a time, so ``rounds[-1]`` is only the
    Finals once the bracket reaches its last round. The Finals is round index
    ``expected_rounds - 1`` (= log2(first-round matchups) + 1 total rounds); until that
    round exists no team has "made the finals", and the title is awarded only once the
    Finals series is clinched. This keeps the bonuses honest mid-playoff.
    """
    series_by_season = {safe_int(ps.get("season")): ps for ps in (data.get("playoffSeries") or []) if isinstance(ps, dict)}
    rounds = [rnd for rnd in ((series_by_season.get(season) or {}).get("series") or []) if rnd]
    if not rounds:
        return (False, False, False)

    matchups = lambda rnd: [m for m in (rnd or []) if isinstance(m, dict)]

    def in_matchup(m: dict[str, Any]) -> bool:
        return tid in (safe_int((m.get("home") or {}).get("tid"), -91), safe_int((m.get("away") or {}).get("tid"), -92))

    made = any(in_matchup(m) for rnd in rounds for m in matchups(rnd))
    first_round = matchups(rounds[0])
    expected_rounds = (int(round(math.log2(len(first_round)))) + 1) if first_round else len(rounds)

    made_finals = won_champ = False
    if len(rounds) >= expected_rounds:
        finals = matchups(rounds[expected_rounds - 1])
        made_finals = any(in_matchup(m) for m in finals)
        for m in finals:
            home, away = m.get("home") or {}, m.get("away") or {}
            hw, aw = safe_int(home.get("won")), safe_int(away.get("won"))
            if max(hw, aw) < FIN_FINALS_GAMES_TO_WIN:
                continue  # Finals series not clinched yet
            winner = safe_int(home.get("tid")) if hw > aw else safe_int(away.get("tid"))
            if winner == tid:
                won_champ = True
    return (made, made_finals, won_champ)


def team_dead_money(data: dict[str, Any] | None, tid: int, season: int) -> float:
    """Salary still owed to this team's waived players in ``season`` (dead money).

    A released player keeps being paid through their contract's ``exp`` year, so it
    counts against payroll/luxury tax even though they're off the roster.
    """
    total = 0.0
    for released in ((data or {}).get("releasedPlayers") or []):
        if safe_int(released.get("tid"), -10) != tid:
            continue
        contract = released.get("contract") or {}
        amount = safe_float(contract.get("amount"), 0.0)
        if amount > 0 and season <= safe_int(contract.get("exp"), season):
            total += amount
    return total


def compute_league_finances(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, odds: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-team cash-flow ledger for the season, recomputed each build from game results.

    Returns ``{"teams": {tid: ledger}, "pool", "share", "n_under", "soft_cap"}``.
    Luxury tax (payroll over the soft cap) is pooled and split equally among the
    teams under the cap. "Projected" figures use the 10k-sim projected wins and the
    expected value of the playoff bonuses (prob-weighted).
    """
    odds = odds or {}
    fin: dict[int, dict[str, Any]] = {}
    for team in teams:
        tid = safe_int(team.get("tid"), -99)
        if tid < 0 or team.get("disabled"):
            continue
        roster = [p for p in players if safe_int(p.get("tid"), -98) == tid]
        dead = team_dead_money(data, tid, season)
        retained = team_retention_delta(tid, season)  # traded-away salary kept on the books
        payroll = team_payroll(roster, season) + dead + retained  # waived + retained still get paid
        # Full next-season commitment (roster + dead money + retained) — matches the Owed Payroll
        # table's committed-salary total, so "available to spend" nets out every 2031 obligation.
        payroll_next = (team_payroll(roster, season + 1)
                        + team_dead_money(data, tid, season + 1)
                        + team_retention_delta(tid, season + 1))
        ts = latest_team_season(team, season)
        won, lost = safe_int(ts.get("won"), 0), safe_int(ts.get("lost"), 0)
        luxtax = max(0.0, payroll - FIN_SOFT_CAP)
        made_po, made_finals, won_champ = playoff_status(data, tid, season)
        earned_playoff = (FIN_PLAYOFF if made_po else 0) + (FIN_FINALS if made_finals else 0) + (FIN_CHAMP if won_champ else 0)
        o = odds.get(tid) or {}
        proj_w = safe_float(o.get("proj_w"), float(won))
        po_p, fin_p, champ_p = safe_float(o.get("po")), safe_float(o.get("finals")), safe_float(o.get("champ"))
        proj_playoff = FIN_PLAYOFF * po_p + FIN_FINALS * fin_p + FIN_CHAMP * champ_p
        adj_info = FIN_ADJUSTMENTS.get(tid) or {}
        fin[tid] = {
            "adj": safe_float(adj_info.get("amount"), 0.0), "adj_note": adj_info.get("note", ""),
            "payroll": payroll, "payroll_next": payroll_next, "dead": dead, "retained": retained, "won": won, "lost": lost, "luxtax": luxtax,
            "under_cap": payroll < FIN_SOFT_CAP, "over_cap": payroll > FIN_SOFT_CAP,
            "win_rev_now": FIN_PER_WIN * won, "win_rev_proj": FIN_PER_WIN * proj_w,
            "earned_playoff": earned_playoff, "proj_playoff": proj_playoff,
            "proj_w": proj_w, "po": po_p, "finals": fin_p, "champ": champ_p,
            "rev_now": FIN_BASE + FIN_PER_WIN * won + earned_playoff,
            "rev_proj": FIN_BASE + FIN_PER_WIN * proj_w + proj_playoff,
        }
    pool = sum(f["luxtax"] for f in fin.values())
    under = [t for t, f in fin.items() if f["under_cap"]]
    share = pool / len(under) if under else 0.0
    offseason = phase_value(data) >= 8
    for tid, f in fin.items():
        f["tax_share"] = share if f["under_cap"] else 0.0
        f["cash_now"] = FIN_START + f["rev_now"] - f["payroll"] - f["luxtax"] + f["tax_share"] + f["adj"]
        f["cash_proj"] = FIN_START + f["rev_proj"] - f["payroll"] - f["luxtax"] + f["tax_share"] + f["adj"]
        if offseason and tid in FIN_NEXT_BALANCE:
            # Offseason: the single-season ledger is over, so show the hand-kept cumulative
            # bankroll carried into next season (available to spend in free agency).
            f["cash_now"] = f["cash_proj"] = float(FIN_NEXT_BALANCE[tid])
            f["offseason"] = True
            f["bankroll_year"] = season + 1
        # Cash left after next season's committed roster salaries are paid.
        f["avail"] = f["cash_now"] - f["payroll_next"]
    return {"teams": fin, "pool": pool, "share": share, "n_under": len(under), "soft_cap": FIN_SOFT_CAP}


def fmt_money_pm(amount: Any) -> str:
    """Money with an explicit +/- sign; $0 for zero."""
    a = safe_float(amount, 0.0)
    if abs(a) < 1e-9:
        return "$0"
    return ("+" + fmt_money(a)) if a > 0 else fmt_money(a)
