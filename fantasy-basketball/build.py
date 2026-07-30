#!/usr/bin/env python3
"""Static-site generator: renders the 2026-27 Fantasy Basketball Encyclopedia vault
(Obsidian markdown) into a self-contained HTML wiki.

Run:  python3 build.py        (from this directory; output lands at repo root)

Design contract: every page is pre-generated (no framework), token-based CSS with a
paper/lamplight theme, sticky nav with client-side search — the same architecture as
andrewjparkus.github.io and chronicaria.github.io, in an antique-serif register.
"""
import csv
import html as html_mod
import json
import re
import shutil
import unicodedata
import urllib.parse
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify

VAULT = Path("/Users/andrewpark/Desktop/Rome/Basketball/Fantasy Basketball/2026-27 Fantasy Basketball Encyclopedia")
OUT = Path(__file__).resolve().parent
AS_OF = "July 19, 2026"

TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BKN": "Brooklyn Nets", "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
    "FA": "Free Agents",
}
DIVISIONS = [
    ("Atlantic", ["BOS", "BKN", "NYK", "PHI", "TOR"]),
    ("Central", ["CHI", "CLE", "DET", "IND", "MIL"]),
    ("Southeast", ["ATL", "CHA", "MIA", "ORL", "WAS"]),
    ("Northwest", ["DEN", "MIN", "OKC", "POR", "UTA"]),
    ("Pacific", ["GSW", "LAC", "LAL", "PHX", "SAC"]),
    ("Southwest", ["DAL", "HOU", "MEM", "NOP", "SAS"]),
]
SECTION_DIR = {
    "Players": "players", "Teams": "teams", "Rankings": "rankings",
    "Projections": "projections", "Strategy": "strategy", "Sources": "library",
    "Research Inbox": "research",
}
SECTION_LABEL = {
    "players": "Players", "teams": "Teams", "rankings": "Draft Room",
    "projections": "Projections", "strategy": "Strategy", "library": "Library",
    "research": "Research Desks", "meta": "Operations",
}


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "page"


def esc(s: str) -> str:
    return html_mod.escape(s, quote=True)


# ---------------------------------------------------------------- scan the vault
class Note:
    def __init__(self, path: Path):
        self.path = path
        rel = path.relative_to(VAULT)
        self.section = rel.parts[0] if len(rel.parts) > 1 else ""
        self.team = rel.parts[1] if self.section == "Players" and len(rel.parts) > 2 else None
        self.basename = path.stem
        text = path.read_text(encoding="utf-8")
        self.meta, self.body = {}, text
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                for line in text[3:end].splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        self.meta[k.strip()] = v.strip()
                self.body = text[end + 4:].lstrip("\n")
        self.title = self.meta.get("title", self.basename)
        # first non-empty, non-link-line paragraph = the one-line summary
        self.summary, self.summary_raw = "", ""
        for para in self.body.split("\n\n"):
            p = para.strip()
            if not p or p.startswith(("#", "Up:", "Related:", "|", ">", "Team:")):
                continue
            self.summary_raw = p
            self.summary = re.sub(r"\[\[([^\]|]*\|)?([^\]]+)\]\]", r"\2", p)
            self.summary = re.sub(r"\*\*?", "", self.summary).split("\n")[0]
            self.summary = re.sub(r"\$([^$\n]+)\$", r"\1", self.summary)
            break

    def body_sans_summary(self):
        """Body with the lede paragraph removed (the hero displays it instead)."""
        return self.body.replace(self.summary_raw, "", 1) if self.summary_raw else self.body

    @property
    def url(self) -> str:
        if self.section == "Players":
            if self.basename.startswith("2026-27"):
                return "players/index.html"
            return f"players/{self.team.lower()}/{slug(self.basename)}.html"
        if self.section in SECTION_DIR:
            return f"{SECTION_DIR[self.section]}/{slug(self.basename)}.html"
        if self.basename == "2026-27 Fantasy Basketball Encyclopedia":
            return "index.html"
        return f"meta/{slug(self.basename)}.html"


notes = [Note(p) for p in sorted(VAULT.rglob("*.md")) if p.parts[len(VAULT.parts)] != "Data"]
by_url = {n.url: n for n in notes}

# resolver: every reasonable wikilink target -> url
resolve: dict[str, str] = {}
for n in notes:
    rel_no_ext = str(n.path.relative_to(VAULT))[:-3]
    for key in {rel_no_ext, n.basename, n.title}:
        if key in resolve and resolve[key] != n.url:
            continue  # first wins; vault audit says no true duplicates
        resolve[key] = n.url
# data files are wikilinked from two notes
for f in (VAULT / "Data").glob("*.csv"):
    resolve[f"Data/{f.name}"] = f"data/{f.name}"

# ------------------------------------------------------- player enrichment (CSVs)
def read_csv(name):
    p = VAULT / "Data" / name
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []

cat = {r["player"]: r for r in read_csv("player-projections-corrected.csv")}
espn = {r["player"]: r for r in read_csv("espn-points-board.csv")}

# ------------------------------------------------------------- markdown pipeline
MD = markdown.Markdown(extensions=["tables", "toc", "footnotes"],
                       extension_configs={"toc": {"slugify": slugify}})

SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def normalize_tables(text):
    """Obsidian renders tables whose separator row has the wrong cell count; python-markdown
    refuses them. Rebuild every separator row to exactly match its header's cell count."""
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        if lines[i].lstrip().startswith("|") and SEP_RE.match(lines[i + 1] or ""):
            n = len(lines[i].strip().strip("|").split("|"))
            cells = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            if len(cells) != n:
                cells = (cells + ["---"] * n)[:n]
                lines[i + 1] = "| " + " | ".join(c or "---" for c in cells) + " |"
    return "\n".join(lines)
MATH_TOKEN = "MATH{}"


def protect_math(text):
    store = []
    def keep(m, display):
        store.append((m.group(1), display))
        return MATH_TOKEN.format(len(store) - 1)
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: keep(m, True), text, flags=re.S)
    def inline(m):
        body = m.group(1)
        # math if it carries TeX structure ($9 \times 10$, $r=+0.79$, $0.42\mu$) or is a bare
        # signed number ($+1$); money ($212M, $49 million) has none of these
        has_math_char = re.search(r"[\\_^{}=]", body)
        signed_number = re.fullmatch(r"[+-]?\d+(\.\d+)?", body)
        single_symbol = re.fullmatch(r"[a-zA-Z]", body)  # $n$, $k$ — variables, never money
        if has_math_char or signed_number or single_symbol:
            return keep(m, False)
        return m.group(0)
    text = re.sub(r"\$([^$\n]+)\$", inline, text)
    return text, store


def restore_math(html, store):
    for i, (body, display) in enumerate(store):
        b = esc(body)
        rep = f'<span class="math display">\\[{b}\\]</span>' if display else f'<span class="math">\\({b}\\)</span>'
        html = html.replace(MATH_TOKEN.format(i), rep)
    return html


def link_wikis(text, depth):
    rel = "../" * depth
    def sub(m):
        inner = m.group(1)
        target, _, alias = inner.replace("\\|", "|").partition("|")
        target, _, anchor = target.partition("#")
        target, anchor = target.strip(), anchor.strip()
        label = (alias or anchor or target).strip()
        # [[#Heading]] — same-page anchor
        if not target and anchor:
            return f'<a href="#{slugify(anchor, "-")}">{esc(label)}</a>'
        url = resolve.get(target) or resolve.get(target.split("/")[-1])
        if url is None:
            return f'<span class="redlink" title="Not in this encyclopedia">{esc(label)}</span>'
        frag = f'#{slugify(anchor, "-")}' if anchor else ""
        return f'<a href="{rel}{url}{frag}">{esc(label)}</a>'
    return re.sub(r"\[\[([^\]]+)\]\]", sub, text)


def fix_callouts(text):
    return re.sub(r"^> \[!(\w+)\][+-]?\s*(.*)$",
                  lambda m: f"> **{(m.group(2) or m.group(1).title()).strip()}**",
                  text, flags=re.M)


def fix_md_links(text, depth):
    """A few notes use standard markdown links to .md files; resolve them like wikilinks."""
    rel = "../" * depth
    def sub(m):
        label, target = m.group(1), urllib.parse.unquote(m.group(2))
        base = target.split("/")[-1][:-3]
        url = resolve.get(base)
        return f"[{label}]({rel}{url})" if url else label
    return re.sub(r"\[([^\]]+)\]\(([^)]+\.md)\)", sub, text)


def render_md(text, depth, drop_h1=None):
    text = normalize_tables(text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text, flags=re.S)
    text = fix_callouts(text)
    text = fix_md_links(text, depth)
    text, store = protect_math(text)
    text = link_wikis(text, depth)
    MD.reset()
    out = MD.convert(text)
    out = restore_math(out, store)
    if drop_h1:
        out = re.sub(r"<h1[^>]*>" + re.escape(esc(drop_h1)) + r"</h1>\s*", "", out, count=1)
    return out


def jump_bar(html):
    h2s = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', html)
    if len(h2s) < 4:
        return ""
    items = "".join(f'<a href="#{i}">{re.sub("<[^>]+>", "", t)}</a>' for i, t in h2s)
    return f'<nav class="jumpbar" aria-label="On this page">{items}</nav>'


# ------------------------------------------------------------------- page shell
def nav_group(label, pairs, rel):
    items = "".join(f'<a href="{rel}{u}">{esc(t)}</a>' for t, u in pairs)
    return (f'<details class="navdrop"><summary>{label}</summary>'
            f'<div class="navmenu">{items}</div></details>')


def shell(title, body, depth, crumb=None, desc=""):
    rel = "../" * depth
    boards = [
        ("ESPN points + 9-cat boards", "rankings/2026-27-draft-boards-espn-points-and-nine-category.html"),
        ("Tiers — both formats", "rankings/2026-27-tiers-espn-points-and-nine-category.html"),
        ("Volume-corrected 9-cat board", "rankings/2026-27-volume-corrected-nine-category-board.html"),
        ("Editorial top 200", "rankings/2026-27-fantasy-basketball-rankings.html"),
        ("Editorial tiers (pre-repair)", "rankings/2026-27-fantasy-basketball-tiers.html"),
        ("Rookies", "rankings/2026-27-rookies.html"),
        ("Sleepers & fades", "rankings/2026-27-sleepers-breakouts-and-fades.html"),
        ("Dynasty", "rankings/2026-27-dynasty-rankings.html"),
        ("Draft-day checklist", "strategy/draft-day-checklist-and-decision-rules.html"),
    ]
    teams = [("All teams (index)", "teams/2026-27-nba-fantasy-team-index.html")]
    teams += [(TEAM_NAMES[a], f"teams/{slug(TEAM_NAMES[a])}.html")
              for _, abbrs in DIVISIONS for a in abbrs]
    strat = [(n.title.replace("2026-27 ", ""), n.url) for n in notes if n.section == "Strategy"]
    proj = [(n.title.replace("2026-27 ", ""), n.url) for n in notes if n.section == "Projections"]
    lib = [(n.title.replace("2026-27 fantasy basketball ", "").capitalize(), n.url)
           for n in notes if n.section == "Sources"]
    lib += [("Evidence policy", "meta/2026-27-fantasy-basketball-evidence-and-confidence-policy.html"),
            ("Build progress", "meta/progress.html"), ("Audit", "meta/audit.html")]
    crumb_html = ""
    if crumb:
        parts = [f'<a href="{rel}index.html">Encyclopedia</a>']
        parts += [f'<a href="{rel}{u}">{esc(t)}</a>' if u else f"<span>{esc(t)}</span>" for t, u in crumb]
        crumb_html = f'<nav class="crumbs" aria-label="Breadcrumb">{" · ".join(parts)}</nav>'
    return f"""<!doctype html>
<html lang="en">
<head>
<script>(function(){{var t=null;try{{t=localStorage.getItem("fbe-theme")}}catch(e){{}}
document.documentElement.dataset.theme=(t==="lamp"||t==="paper")?t:(matchMedia("(prefers-color-scheme: dark)").matches?"lamp":"paper");}})();</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — 2026-27 Fantasy Basketball Encyclopedia</title>
<meta name="description" content="{esc(desc or title)}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏀</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<link rel="stylesheet" href="{rel}assets/style.css">
</head>
<body data-rel="{rel}">
<header class="topnav">
  <a class="brand" href="{rel}index.html">The Fantasy Basketball <b>Encyclopedia</b></a>
  <div class="navsearch"><input type="search" id="q" placeholder="Search players, teams, notes…"
    autocomplete="off" role="combobox" aria-expanded="false" aria-label="Search the encyclopedia">
    <div class="searchresults" id="qr" role="listbox" hidden></div></div>
  <nav class="navlinks">
    {nav_group("Draft Room", boards, rel)}
    {nav_group("Teams", teams, rel)}
    {nav_group("Projections", proj, rel)}
    {nav_group("Strategy", strat, rel)}
    {nav_group("Library", lib, rel)}
    <a class="navflat" href="{rel}players/index.html">Players</a>
  </nav>
  <button class="themebtn" id="themebtn" type="button" aria-label="Toggle theme">☾</button>
</header>
<main class="page">
{crumb_html}
{body}
</main>
<footer class="foot">
  <div class="rule"></div>
  <p>The 2026-27 Fantasy Basketball Encyclopedia · research cutoff {AS_OF} · built from the Rome vault.
  Early-offseason projections, not camp-final depth charts. Every ranking names its format; never average boards across formats.</p>
</footer>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script defer src="{rel}assets/site.js"></script>
</body>
</html>"""


def write(url, html):
    p = OUT / url
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")


# --------------------------------------------------------------- player pages
def fmt_pct(v):
    try:
        return f"{float(v):.3f}".lstrip("0")
    except (TypeError, ValueError):
        return "—"


def player_card(n: Note):
    c, e = cat.get(n.basename) or cat.get(n.title), espn.get(n.basename) or espn.get(n.title)
    team_full = TEAM_NAMES.get(n.team, n.team)
    team_link = (f'<a href="../../teams/{slug(team_full)}.html">{esc(team_full)}</a>'
                 if n.team != "FA" else "Unsigned free agent")
    cells = [("Team", team_link)]
    if c:
        cells += [
            ("9-cat rank", f'<b>#{c["corrected_rank"]}</b> <small>per game</small>'),
            ("9-cat totals", f'#{c["corrected_total_rank"]}'),
            ("Proj. GP / MPG", f'{float(c["gp"]):.0f} / {float(c["mpg"]):.1f}'),
            ("FG", f'{fmt_pct(c["fg_pct"])} on {c["fga_proj"]}'),
            ("FT", f'{fmt_pct(c["ft_pct"])} on {c["fta_proj"]}'),
        ]
    if e:
        cells += [("ESPN points", f'<b>#{e["espn_rank"]}</b> <small>{e["espn_fp_per_game"]} FP/g</small>'),
                  ("ESPN totals", f'#{e["espn_total_rank"]}')]
    dl = "".join(f"<div class='fact'><dt>{k}</dt><dd>{v}</dd></div>" for k, v in cells)
    tag = "" if (c or e) else "<p class='cardnote'>Outside the 262-player projection pool — see the dossier for status.</p>"
    return f'<aside class="factcard" aria-label="Projection summary"><dl>{dl}</dl>{tag}</aside>'


def build_players():
    roster: dict[str, list[Note]] = {}
    for n in notes:
        if n.section != "Players" or n.basename.startswith("2026-27"):
            continue
        roster.setdefault(n.team, []).append(n)
        player_body = re.sub(r'^Up: \[\[[^\n]*$', '', n.body_sans_summary(), flags=re.M)
        body_html = render_md(player_body, 2, drop_h1=n.title)
        team_full = TEAM_NAMES.get(n.team, n.team)
        hero = (f'<div class="hero"><p class="kicker">Player Dossier · {esc(team_full)}</p>'
                f"<h1>{esc(n.basename)}</h1>"
                f'<p class="lede">{esc(n.summary)}</p></div>')
        page = hero + player_card(n) + jump_bar(body_html) + f'<article class="prose">{body_html}</article>'
        team_crumb = (team_full, f"teams/{slug(team_full)}.html" if n.team != "FA" else None)
        write(n.url, shell(n.basename, page, 2,
                           crumb=[("Players", "players/index.html"),
                                  team_crumb, (n.basename, None)],
                           desc=n.summary))
    return roster


def player_sort_key(n: Note):
    c = cat.get(n.basename)
    return (int(c["corrected_rank"]) if c else 9999, n.basename)


def rank_of(row, key):
    return "#" + row[key] if row else "—"


def num_of(row, key, fmt):
    return format(float(row[key]), fmt) if row else "—"


def build_player_index(roster):
    rows = []
    for team, players in roster.items():
        for n in players:
            c, e = cat.get(n.basename), espn.get(n.basename)
            rows.append((n, team, c, e))
    rows.sort(key=lambda r: (int(r[2]["corrected_rank"]) if r[2] else 9999, r[0].basename))
    parts = []
    for r, t, c, e in rows:
        href = r.url.replace("players/", "")
        if t == "FA":
            team_cell = "<td>FA</td>"
        else:
            team_cell = "<td><a href='../teams/" + slug(TEAM_NAMES.get(t, t)) + ".html'>" + t + "</a></td>"
        parts.append(
            "<tr><td>" + rank_of(c, "corrected_rank") + "</td>"
            + "<td><a href='" + href + "'>" + esc(r.basename) + "</a></td>"
            + team_cell
            + "<td>" + rank_of(e, "espn_rank") + "</td>"
            + "<td>" + num_of(c, "gp", ".0f") + "</td>"
            + "<td>" + num_of(c, "mpg", ".1f") + "</td></tr>")
    tr = "".join(parts)
    body = f"""<div class="hero"><p class="kicker">The Player Encyclopedia</p>
<h1>All Players</h1>
<p class="lede">{len(rows)} dossiers across 30 teams and the free-agent pool, ranked by the repaired
nine-category board. Type to filter; click a column head to sort.</p></div>
<input class="tablefilter" id="pfilter" type="search" placeholder="Filter by name or team…" aria-label="Filter players">
<div class="tablewrap"><table class="sortable" id="ptable">
<thead><tr><th data-n>9-cat</th><th>Player</th><th>Team</th><th data-n>ESPN</th><th data-n>GP</th><th data-n>MPG</th></tr></thead>
<tbody>{tr}</tbody></table></div>"""
    write("players/index.html", shell("All Players", body, 1, crumb=[("Players", None)]))


def build_teams(roster):
    for n in notes:
        if n.section != "Teams" or n.basename.startswith("2026-27"):
            continue
        abbr = next((a for a, name in TEAM_NAMES.items() if name == n.basename), None)
        players = sorted(roster.get(abbr, []), key=player_sort_key)
        card_parts = []
        for p in players:
            c = cat.get(p.basename)
            rank = "#" + c["corrected_rank"] if c else "·"
            card_parts.append(
                "<a class='rostercard' href='../players/" + abbr.lower() + "/" + slug(p.basename)
                + ".html'><span class='rc-rank'>" + rank + "</span>"
                + "<span class='rc-name'>" + esc(p.basename) + "</span></a>")
        cards = "".join(card_parts)
        division = next((d for d, abbrs in DIVISIONS if abbr in abbrs), "")
        body_html = render_md(n.body_sans_summary(), 1, drop_h1=n.title)
        hero = (f'<div class="hero"><p class="kicker">Team Desk · {division} Division</p>'
                f"<h1>{esc(n.title)}</h1><p class='lede'>{esc(n.summary)}</p></div>")
        rosterblock = (f'<section class="rosterblock"><h2 class="smallcaps">Roster — {len(players)} dossiers</h2>'
                       f'<div class="rostergrid">{cards}</div></section>') if players else ""
        page = hero + rosterblock + jump_bar(body_html) + f'<article class="prose">{body_html}</article>'
        write(n.url, shell(n.title, page, 1, crumb=[("Teams", "teams/2026-27-nba-fantasy-team-index.html"), (n.title, None)], desc=n.summary))


def build_generic():
    """Every note except player dossiers, team desks, the hub, and the player index."""
    for n in notes:
        if n.url in ("index.html", "players/index.html"):
            continue
        if n.section == "Players":
            continue  # dossiers built in build_players
        if n.section == "Teams" and not n.basename.startswith("2026-27"):
            continue  # team desks built in build_teams (the team index note renders here)
        depth = n.url.count("/")
        sect = n.url.split("/")[0]
        body_html = render_md(n.body_sans_summary(), depth, drop_h1=n.title)
        hero = (f'<div class="hero"><p class="kicker">{SECTION_LABEL.get(sect, sect.title())}</p>'
                f"<h1>{esc(n.title)}</h1><p class='lede'>{esc(n.summary)}</p></div>")
        page = hero + jump_bar(body_html) + f'<article class="prose">{body_html}</article>'
        write(n.url, shell(n.title, page, depth,
                           crumb=[(SECTION_LABEL.get(sect, sect.title()), None), (n.title, None)],
                           desc=n.summary))


def build_index():
    hub = by_url["index.html"]
    body = hub.body
    body = re.sub(r"^Up: \[\[.*$", "", body, flags=re.M)
    body_html = render_md(body, 0, drop_h1=hub.title)
    n_players = sum(1 for n in notes if n.section == "Players" and not n.basename.startswith("2026-27"))
    n_notes = len(notes)
    teamgrid = "".join(
        f"<section class='divblock'><h3 class='smallcaps'>{d}</h3>" + "".join(
            f"<a class='teamlink' href='teams/{slug(TEAM_NAMES[a])}.html'>{esc(TEAM_NAMES[a])}</a>"
            for a in abbrs) + "</section>"
        for d, abbrs in DIVISIONS)
    masthead = f"""<div class="masthead">
  <p class="mh-date">Research cutoff · {AS_OF} · Volume I</p>
  <h1 class="mh-title">The Fantasy Basketball Encyclopedia</h1>
  <p class="mh-sub">2026–27 Season · {n_players} player dossiers · 30 team desks · {n_notes} linked entries</p>
  <div class="mh-rule"></div>
  <p class="mh-note">Built for ESPN-points and nine-category leagues of ten or twelve teams.
  The factual record is verified against primary sources; the projection engine has been repaired and
  its <a href="projections/projection-engine-defects-and-corrections.html">defects documented</a>.
  A July board is not a draft board — re-verify in October.</p>
</div>"""
    page = masthead + f'<article class="prose homeprose">{body_html}</article>' + \
        f'<section class="teamdirectory"><h2 class="smallcaps">The Thirty Teams</h2><div class="divgrid">{teamgrid}</div></section>'
    write("index.html", shell("Home", page, 0, desc="The 2026-27 Fantasy Basketball Encyclopedia"))


def build_search_index():
    idx = []
    for n in notes:
        if n.url == "index.html":
            continue
        kind = ("player" if n.section == "Players" and not n.basename.startswith("2026-27")
                else "team" if n.section == "Teams" and not n.basename.startswith("2026-27")
                else SECTION_LABEL.get(n.url.split("/")[0], "note").lower())
        extra = ""
        if kind == "player":
            c = cat.get(n.basename)
            extra = f"{n.team}" + (f" · 9-cat #{c['corrected_rank']}" if c else "")
        idx.append({"t": n.basename, "u": n.url, "k": kind, "x": extra})
    write("assets/search-index.json", json.dumps(idx, ensure_ascii=False, separators=(",", ":")))


def copy_data():
    (OUT / "data").mkdir(exist_ok=True)
    for f in (VAULT / "Data").glob("*.csv"):
        shutil.copy(f, OUT / "data" / f.name)


def rename_meta():
    # friendlier URLs for the two operational notes
    for old, new in [("meta/2026-27-fantasy-basketball-encyclopedia-audit.html", "meta/audit.html"),
                     ("meta/2026-27-fantasy-basketball-encyclopedia-progress.html", "meta/progress.html")]:
        p = OUT / old
        if p.exists():
            p.rename(OUT / new)


def clean_orphans():
    """Delete generated pages whose source note no longer exists (players change teams)."""
    expected = {n.url for n in notes} | {"index.html", "players/index.html", "meta/audit.html", "meta/progress.html"}
    removed = 0
    for d in ("players", "teams", "rankings", "projections", "strategy", "library", "research", "meta"):
        for p in (OUT / d).rglob("*.html"):
            if str(p.relative_to(OUT)) not in expected:
                p.unlink()
                removed += 1
    if removed:
        print(f"removed {removed} orphaned pages")


if __name__ == "__main__":
    roster = build_players()
    build_player_index(roster)
    build_teams(roster)
    build_generic()
    build_index()
    build_search_index()
    copy_data()
    rename_meta()
    clean_orphans()
    pages = len(list(OUT.rglob("*.html")))
    print(f"built {pages} pages from {len(notes)} notes")
