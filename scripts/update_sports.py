#!/usr/bin/env python3
"""Fetch team data from ESPN's public site API and write data/sports.json.

Runs on a schedule via GitHub Actions (stdlib only — no pip install).
Each team gets: record, standing, last 10 results, next 3 games.
A failed fetch for one team never breaks the others; the page just
keeps that team's previous data missing for the cycle.
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://site.api.espn.com/apis/site/v2/sports"
OUT = Path(__file__).resolve().parent.parent / "data" / "sports.json"

TEAMS = [
    {"key": "duke-mbb", "label": "Duke MBB", "tier": 1, "league": "NCAA MBB", "path": "basketball/mens-college-basketball", "slug": "150"},
    {"key": "duke-fb",  "label": "Duke FB",  "tier": 1, "league": "NCAA FB",  "path": "football/college-football",         "slug": "150"},
    {"key": "mavs",     "label": "Mavs",     "tier": 1, "league": "NBA",      "path": "basketball/nba",                    "slug": "dal"},
    {"key": "mets",     "label": "Mets",     "tier": 2, "league": "MLB",      "path": "baseball/mlb",                      "slug": "nym"},
    {"key": "spurs",    "label": "Spurs",    "tier": 2, "league": "Premier League", "path": "soccer/eng.1",                "slug": "367"},
    {"key": "colts",    "label": "Colts",    "tier": 3, "league": "NFL",      "path": "football/nfl",                      "slug": "ind"},
    {"key": "canes",    "label": "Canes",    "tier": 3, "league": "NHL",      "path": "hockey/nhl",                        "slug": "car"},
    {"key": "lafc",     "label": "LAFC",     "tier": 3, "league": "MLS",      "path": "soccer/usa.1",                      "slug": "18966"},
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "andrewparkus.github.io sports tracker"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def fetch_team_info(cfg):
    team = get(f"{BASE}/{cfg['path']}/teams/{cfg['slug']}")["team"]
    records = team.get("record", {}).get("items", [])
    record = next((r["summary"] for r in records if r.get("type") == "total"),
                  records[0]["summary"] if records else "")
    logos = team.get("logos", [])
    return {
        "id": team["id"],
        "name": team["displayName"],
        "abbr": team.get("abbreviation", ""),
        "record": record,
        "standing": team.get("standingSummary", ""),
        "logo": logos[0]["href"] if logos else "",
        "color": team.get("color", ""),
    }


def fetch_events(cfg):
    """Schedule events across regular season and postseason, deduped, date-sorted.

    The bare schedule endpoint defaults to whatever ESPN considers the current
    season *phase* (in the off-season that can be an empty postseason), so
    regular season (2) and postseason (3) are requested explicitly. If that
    yields no completed games — e.g. college football in June, where the
    default year is the upcoming season — the previous season is fetched too,
    so the form strip always reflects the last games actually played.
    """
    base = f"{BASE}/{cfg['path']}/teams/{cfg['slug']}/schedule"
    is_soccer = cfg["path"].startswith("soccer/")
    urls = [base] if is_soccer else [f"{base}?seasontype=2", f"{base}?seasontype=3"]

    seen, events = set(), []
    def collect(url):
        try:
            data = get(url)
        except Exception:
            return
        for e in data.get("events", []):
            if e["id"] not in seen:
                seen.add(e["id"])
                events.append(e)

    for url in urls:
        collect(url)

    def completed(e):
        return e["competitions"][0]["status"]["type"].get("completed")

    if not is_soccer and not any(completed(e) for e in events):
        # Off-season: the current-year schedule is all upcoming games. The most
        # recently *played* season is the one before the earliest scheduled
        # event (the API's own season.year label is unreliable for the NFL).
        if events:
            prev = int(min(e["date"] for e in events)[:4]) - 1
        else:
            prev = datetime.now(timezone.utc).year - 1
        collect(f"{base}?season={prev}&seasontype=2")
        collect(f"{base}?season={prev}&seasontype=3")

    events.sort(key=lambda e: e["date"])
    return events


def summarize(cfg, info, events):
    team_id = info["id"]
    form, upcoming = [], []
    for e in events:
        comp = e["competitions"][0]
        status = comp.get("status", {}).get("type", {})
        sides = comp.get("competitors", [])
        us = next((c for c in sides if c["team"]["id"] == team_id), None)
        them = next((c for c in sides if c["team"]["id"] != team_id), None)
        if not us or not them:
            continue
        if cfg["path"].startswith("soccer/"):
            game_url = f"https://www.espn.com/soccer/match/_/gameId/{e['id']}"
        else:
            game_url = f"https://www.espn.com/{cfg['path'].split('/')[1]}/game/_/gameId/{e['id']}"
        entry = {
            "date": e["date"],
            "opp": them["team"].get("shortDisplayName") or them["team"].get("displayName", ""),
            "oppAbbr": them["team"].get("abbreviation", ""),
            "home": us.get("homeAway") == "home",
            "url": game_url,
        }
        if status.get("completed"):
            us_score = (us.get("score") or {}).get("displayValue", "")
            them_score = (them.get("score") or {}).get("displayValue", "")
            if not us_score:
                continue
            if us.get("winner"):
                entry["res"] = "W"
            elif them.get("winner"):
                entry["res"] = "L"
            else:
                entry["res"] = "D"
            entry["score"] = f"{us_score}-{them_score}"
            form.append(entry)
        elif status.get("name") not in ("STATUS_CANCELED", "STATUS_POSTPONED") \
                and e["date"] >= datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"):
            if not e.get("timeValid", True):
                entry["tbd"] = True
            upcoming.append(entry)
    return {
        "key": cfg["key"],
        "label": cfg["label"],
        "tier": cfg["tier"],
        "league": cfg["league"],
        "path": cfg["path"],
        **info,
        "form": form[-10:],
        "next": upcoming[:10],
    }


def archive_history(teams):
    """Append completed games to data/history/<year>.json, deduped.

    Builds a personal results archive over time; a year-in-review page can
    read these files directly.
    """
    hist_dir = OUT.parent / "history"
    hist_dir.mkdir(exist_ok=True)
    by_year = {}
    for t in teams:
        for g in t["form"]:
            year = g["date"][:4]
            by_year.setdefault(year, []).append({
                "team": t["key"],
                "label": t["label"],
                "league": t["league"],
                **{k: g[k] for k in ("date", "opp", "home", "res", "score")},
            })
    for year, games in by_year.items():
        path = hist_dir / f"{year}.json"
        existing = json.loads(path.read_text())["games"] if path.exists() else []
        seen = {(g["team"], g["date"]) for g in existing}
        fresh = [g for g in games if (g["team"], g["date"]) not in seen]
        if not fresh:
            continue
        merged = sorted(existing + fresh, key=lambda g: g["date"])
        path.write_text(json.dumps({"games": merged}, indent=1) + "\n")
        print(f"history: +{len(fresh)} games -> {path.name}")


def attach_odds(teams):
    """Moneylines for today's games from each league's scoreboard endpoint."""
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    paths = {t["path"] for t in teams
             for g in t["next"] if g["date"][:10] >= today[:10]}
    boards = {}
    for path in paths:
        try:
            boards[path] = get(f"{BASE}/{path}/scoreboard")
        except Exception:
            pass
    odds_by_event = {}
    for board in boards.values():
        for e in board.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            odds = (comp.get("odds") or [{}])[0]
            line = odds.get("details") or ""
            if odds.get("overUnder"):
                line = f"{line} · O/U {odds['overUnder']}".strip(" ·")
            if line:
                odds_by_event[e["id"]] = line
    n = 0
    for t in teams:
        for g in t["next"]:
            eid = (g.get("url") or "").rsplit("/", 1)[-1]
            if eid in odds_by_event:
                g["odds"] = odds_by_event[eid]
                n += 1
    if n:
        print(f"odds: attached to {n} upcoming games")


def main():
    teams, errors = [], []
    for cfg in TEAMS:
        try:
            info = fetch_team_info(cfg)
            events = fetch_events(cfg)
            teams.append(summarize(cfg, info, events))
            print(f"ok   {cfg['key']:10s} {info['record'] or '—':10s} {info['standing']}")
        except Exception as exc:
            errors.append(cfg["key"])
            print(f"FAIL {cfg['key']:10s} {exc}", file=sys.stderr)
    if not teams:
        sys.exit("every fetch failed — keeping previous sports.json")
    try:
        attach_odds(teams)
    except Exception as exc:
        print(f"odds: skipped ({exc})", file=sys.stderr)
    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "errors": errors,
        "teams": teams,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    archive_history(teams)
    print(f"wrote {OUT} ({len(teams)}/{len(TEAMS)} teams)")


if __name__ == "__main__":
    main()
