#!/usr/bin/env python3
"""Static-site generator: renders the 2026 Fantasy Football Encyclopedia vault
(Obsidian markdown) into a self-contained HTML wiki.

Run:  python3 build.py        (from this directory; output lands beside this file,
                              i.e. fantasy/football/ — OUT is self-relative, so
                              moving the folder moves the output with it)

Design contract, same as andrewjparkus.github.io / chronicaria.github.io / the
fantasy basketball wiki: every page pre-generated, no framework, token-based CSS with a
paper/lamplight theme, sticky nav with a client-side search index. Register is the same
antique serif, shifted from oxblood to pine so the two encyclopedias are not confusable.

What this build adds over the basketball one: a genuinely interactive Draft Room page
rendered straight from the CSVs (sort, filter, position pills, availability bars) rather
than from prose, and player fact cards that carry the observed age / availability /
injury / usage / contract data.
"""
import csv
import html as html_mod
import json
import re
import shutil
import unicodedata
from datetime import date
from pathlib import Path

import markdown

VAULT = Path("/Users/andrewpark/Desktop/Rome/Sports/NFL/Fantasy Football")
OUT = Path(__file__).resolve().parent
AS_OF = "July 25, 2026"

SECTION_DIR = {
    "Start Here": "start-here", "Draft": "draft", "Season": "season",
    "Concepts": "concepts", "Sources": "library", "Teams": "teams",
    "Players": "players",
}
SECTION_LABEL = {
    "start-here": "Start Here", "draft": "The Draft", "season": "The Season",
    "concepts": "Concepts", "library": "Library", "teams": "Teams",
    "players": "Players", "meta": "Operations",
}
SECTION_ORDER = ["start-here", "draft", "season", "concepts", "teams", "players",
                 "library", "meta"]

READING_ORDER = [
    "How an NFL offense makes fantasy points",
    "What each fantasy position actually does",
    "Player archetypes",
    "Reading an NFL depth chart",
    "What basketball teaches you wrong about football",
    "Fantasy football glossary",
    "The 2026 season calendar",
    "How the league is won",
    "The four players you already know",
    "Your league, in one page",
]

TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAC": "Jacksonville Jaguars",
    "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}
PICKS = [1, 24, 25, 48, 49, 72, 73, 96, 97, 120, 121, 144, 145, 168, 169, 192]


VAULT_ROOT = Path("/Users/andrewpark/Desktop/Rome")
VAULT_STEMS = {p.stem.lower() for p in VAULT_ROOT.rglob("*.md")
               if ".obsidian" not in p.parts}


def slug(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "page"


def esc(s):
    return html_mod.escape(str(s), quote=True)


# ---------------------------------------------------------------- scan the vault
class Note:
    def __init__(self, path):
        self.path = path
        rel = path.relative_to(VAULT)
        self.section = rel.parts[0] if len(rel.parts) > 1 else ""
        self.basename = path.stem
        text = path.read_text(encoding="utf-8")
        self.meta = {}
        m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    self.meta[k.strip()] = v.strip()
            text = text[m.end():]
        self.body = text.strip()
        self.title = self.meta.get("title", self.basename)
        self.dirname = SECTION_DIR.get(self.section, "meta")
        self.slug = slug(self.basename)
        self.href = f"{self.dirname}/{self.slug}.html"
        # lede = first non-empty, non-link line
        self.lede = ""
        for line in self.body.splitlines():
            t = line.strip()
            if t and not t.startswith(("#", "Up:", ">", "|", "*Rendered", "*Built")):
                self.lede = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2",
                                   re.sub(r"\[\[([^\]|]+)\]\]", r"\1", t))
                self.lede = re.sub(r"\*\*|\*|`", "", self.lede)
                break


def scan():
    notes, index = [], {}
    for p in sorted(VAULT.rglob("*.md")):
        if any(part in ("Data", ".obsidian") for part in p.parts):
            continue
        if p.name == "_PLAN.md":
            continue
        n = Note(p)
        notes.append(n)
        index.setdefault(n.basename.lower(), n)
        index.setdefault(n.title.lower(), n)
        rel = p.relative_to(VAULT.parents[2]).as_posix()[:-3]
        index.setdefault(rel.lower(), n)
    return notes, index


# ---------------------------------------------------------------- markdown
CALLOUT = re.compile(r"^> \[!(\w+)\]([+-]?)\s*(.*)$")


def preprocess(body, index, here):
    """Wikilinks, Obsidian callouts, and the `Up:` link row."""
    def link(m):
        target, alias = m.group(1), m.group(2)
        target = target.split("#")[0].strip()
        label = (alias or target.split("/")[-1]).strip()
        hit = index.get(target.lower()) or index.get(target.split("/")[-1].lower())
        if hit is None:
            stem = target.split("/")[-1].lower()
            if stem in VAULT_STEMS:
                # It exists in Obsidian, it is just not part of this site. Saying
                # "not written yet" would be a lie the reader cannot check.
                return (f'<span class="vaultlink" title="lives in the Obsidian vault, '
                        f'not on this site">{esc(label)}</span>')
            return (f'<span class="redlink" title="not written yet">'
                    f'{esc(label)}</span>')
        depth = here.count("/")
        prefix = "../" * depth
        return f'<a href="{prefix}{hit.href}">{esc(label)}</a>'

    # `\|` is how Obsidian escapes an alias pipe inside a table cell — accept both.
    body = re.sub(r"!?\[\[([^\[\]|]+?)(?:\\?\|([^\[\]]+?))?\]\]", link, body)

    out, i, lines = [], 0, body.split("\n")
    while i < len(lines):
        m = CALLOUT.match(lines[i])
        if m:
            kind, fold, title = m.group(1).lower(), m.group(2), m.group(3)
            i += 1
            inner = []
            while i < len(lines) and lines[i].startswith(">"):
                inner.append(lines[i][1:].lstrip() if lines[i] != ">" else "")
                i += 1
            tag = "details" if fold else "div"
            openattr = " open" if fold == "+" else ""
            head = (f"<summary>{title or kind.title()}</summary>" if fold
                    else f'<p class="co-title">{title or kind.title()}</p>')
            out.append(f'<{tag} class="callout co-{esc(kind)}"{openattr}>{head}')
            out.append("")
            out.extend(inner)
            out.append("")
            out.append(f"</{tag}>")
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


MD = markdown.Markdown(extensions=["tables", "toc", "attr_list", "md_in_html"])


def render_md(body, index, here):
    MD.reset()
    return MD.convert(preprocess(body, index, here))


# ---------------------------------------------------------------- data
def load_csv(name):
    p = VAULT / "Data" / name
    if not p.exists():
        raise SystemExit(f"FATAL: {p} missing — the site cannot be built without it.")
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def fnum(v, spec="{:.0f}"):
    try:
        return spec.format(float(v))
    except (TypeError, ValueError):
        return "—"


def build_board_rows(players, ctx):
    """Recompute the board the same way Data/build_board.py does, so the interactive
    table and the markdown note can never disagree."""
    BASE_RANK = {"RB": 29, "WR": 31, "TE": 12, "QB": 12, "K": 3, "DST": 3}
    rows = []
    for p in players:
        try:
            pts = float(p["proj_points"])
        except ValueError:
            continue
        c = ctx.get(p["player"], {})
        rows.append({
            "player": p["player"], "team": p["team"], "pos": p["pos"],
            "bye": int(p["bye"]), "adp": float(p["adp"]) if p["adp"] else None,
            "pts": pts, "note": p["note"], "risk": p["risk"],
            "archetype": p["archetype"],
            "age": float(c["age"]) if c.get("age") else None,
            "avail": float(c["avail"]) if c.get("avail") else None,
            "ctx": c,
        })
    means = {}
    for pos in BASE_RANK:
        v = [r["avail"] for r in rows if r["pos"] == pos and r["avail"]]
        means[pos] = sum(v) / len(v) if v else None
    for r in rows:
        m = means.get(r["pos"])
        r["adj_pts"] = round(r["pts"] * (r["avail"] / m), 1) if (r["avail"] and m) else r["pts"]
    for pos, rank in BASE_RANK.items():
        pool = sorted((r for r in rows if r["pos"] == pos), key=lambda r: -r["pts"])
        base = pool[rank - 1]["pts"]
        for i, r in enumerate(pool):
            r["pos_rank"] = i + 1
            r["vor"] = round(r["pts"] - base, 1)
        apool = sorted((r for r in rows if r["pos"] == pos), key=lambda r: -r["adj_pts"])
        abase = apool[rank - 1]["adj_pts"]
        for r in apool:
            r["adj_vor"] = round(r["adj_pts"] - abase, 1)
    rows.sort(key=lambda r: -r["vor"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------- page shell
def nav(notes, depth):
    up = "../" * depth
    groups = {}
    for n in notes:
        groups.setdefault(n.dirname, []).append(n)
    parts = [f'<a class="brand" href="{up}index.html">The Fantasy Football '
             f'<b>Encyclopedia</b></a>',
             f'<div class="navsearch"><input id="q" type="search" placeholder="Search '
             f'(press /)" autocomplete="off" aria-label="Search"><div id="qr" '
             f'class="searchresults" hidden></div></div>',
             '<nav class="navlinks">',
             f'<a class="navflat" href="{up}draft-room.html">Draft Room</a>']
    for d in SECTION_ORDER:
        if d not in groups:
            continue
        items = sorted(groups[d], key=lambda n: n.title)
        links = "".join(f'<a href="{up}{n.href}">{esc(n.title)}</a>' for n in items)
        parts.append(f'<details class="navdrop"><summary>{SECTION_LABEL[d]}</summary>'
                     f'<div class="navmenu">{links}</div></details>')
    parts.append('<button class="themebtn" id="theme" type="button" '
                 'aria-label="Toggle theme">◐</button></nav>')
    return f'<header class="topnav">{"".join(parts)}</header>'


def shell(title, body, notes, depth=0, desc="", crumbs=""):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en" data-theme="paper">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title if title != "The Fantasy Football Encyclopedia" else "Home")} — The Fantasy Football Encyclopedia</title>
<meta name="description" content="{esc(desc)}">
<script>(function(){{try{{var t=localStorage.getItem('ff-theme');
if(!t)t=matchMedia('(prefers-color-scheme:dark)').matches?'lamp':'paper';
document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}}})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
{nav(notes, depth)}
<main class="page">
{crumbs}
{body}
</main>
<footer class="foot"><div class="rule"></div>
Rendered from the Rome vault on {AS_OF}. Projections and ADP are dated inputs, not
forecasts — every perishable page carries its own expiry. Built by
<code>build.py</code>; nothing on this site is hand-typed HTML.</footer>
<script src="{up}assets/site.js"></script>
</body>
</html>
"""


def write(rel, text):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- pages
def note_page(n, notes, index):
    body = n.body
    # strip the H1 if the note has one; the hero carries the title
    body = re.sub(r"\A#\s+.*?\n", "", body)
    # the first "Up:" line becomes the jumpbar
    jump = ""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("Up:"):
            jump = render_md(line, index, n.href)
            jump = f'<div class="jumpbar">{jump}</div>'
            del lines[i]
            break
    body = "\n".join(lines)
    # drop the lede paragraph from the prose since the hero shows it
    if n.lede:
        body = body.replace(n.lede, "", 1)
    html = render_md(body, index, n.href)
    meta_bits = []
    for k, label in (("as_of", "as of"), ("expires", "expires"),
                     ("status", "status"), ("format", "format")):
        if n.meta.get(k):
            meta_bits.append(f'<span class="mb"><i>{label}</i> {esc(n.meta[k])}</span>')
    stale = ""
    if n.meta.get("expires"):
        try:
            if date.fromisoformat(n.meta["expires"]) < date(2026, 8, 31):
                stale = ('<p class="staleflag">Perishable — this page is built on '
                         'July inputs and must be regenerated within 48 hours of the '
                         'draft.</p>')
        except ValueError:
            pass
    crumbs = (f'<div class="crumbs"><a href="../index.html">Encyclopedia</a> · '
              f'<a href="../{n.dirname}/index.html">{SECTION_LABEL[n.dirname]}</a> · '
              f'<span>{esc(n.title)}</span></div>')
    hero = (f'<div class="hero"><p class="kicker">{SECTION_LABEL[n.dirname]}</p>'
            f'<h1>{esc(n.title)}</h1>'
            + (f'<p class="lede">{esc(n.lede)}</p>' if n.lede else "")
            + (f'<p class="metaline">{" · ".join(meta_bits)}</p>' if meta_bits else "")
            + "</div>" + stale)
    return shell(n.title, hero + jump + f'<article class="prose">{html}</article>',
                 notes, depth=1, desc=n.lede, crumbs=crumbs)


def section_index(dirname, items, notes):
    rows = "".join(
        f'<li><a href="{n.slug}.html">{esc(n.title)}</a>'
        f'<span class="si-lede">{esc(n.lede)}</span></li>'
        for n in sorted(items, key=lambda n: n.title))
    crumbs = ('<div class="crumbs"><a href="../index.html">Encyclopedia</a> · '
              f'<span>{SECTION_LABEL[dirname]}</span></div>')
    body = (f'<div class="hero"><p class="kicker">Section</p>'
            f'<h1>{SECTION_LABEL[dirname]}</h1>'
            f'<p class="lede">{len(items)} pages.</p></div>'
            f'<ul class="sectionindex">{rows}</ul>')
    return shell(SECTION_LABEL[dirname], body, notes, depth=1, crumbs=crumbs)


def factcard(row):
    c = row["ctx"]
    def fact(label, value, sub=""):
        if value in (None, "", "—"):
            return ""
        return (f'<div class="fact"><dt>{label}</dt><dd>{value}'
                + (f" <small>{sub}</small>" if sub else "") + "</dd></div>")
    inj = c.get("inj_parts_3yr") or ""
    games = " · ".join(x for x in (c.get("g_2023"), c.get("g_2024"), c.get("g_2025")) if x)
    bits = [
        fact("Board", f'<b>#{row["rank"]}</b>', f'{row["pos"]}{row["pos_rank"]}'),
        fact("Proj pts", fnum(row["pts"]), "this league's scoring"),
        fact("VOR", f'{row["vor"]:+.0f}'),
        fact("Adj VOR", f'{row["adj_vor"]:+.0f}', "availability-adjusted"),
        fact("ADP", row["adp"] if row["adp"] else "—", "FFCalc proxy"),
        fact("Team", esc(TEAM_NAMES.get(row["team"], row["team"]))),
        fact("Bye", row["bye"]),
        fact("Age", fnum(row["age"], "{:.1f}")),
        fact("Availability", fnum(row["avail"], "{:.2f}"), "3yr, modelled"),
        fact("Games played", games, "2023 · 2024 · 2025"),
        fact("Missed", c.get("games_missed_3yr"), "last 3 seasons"),
        fact("Weeks Out", c.get("inj_weeks_out_3yr"), "official report"),
        fact("Snap share", (c.get("snap_pct_2025") + "%") if c.get("snap_pct_2025") else "",
             "2025"),
        fact("Targets", c.get("targets_2025"), "2025"),
        fact("Carries", c.get("carries_2025"), "2025"),
        fact("Drafted", (f'{c.get("draft_year")} · #{c.get("draft_overall")}'
                         if c.get("draft_overall") else c.get("draft_year", "")),
             esc(c.get("college", ""))),
        fact("Contract", esc(c.get("contract_value", "")),
             esc(f'FA {c.get("contract_free_agent","")}' if c.get("contract_free_agent") else "")),
    ]
    note = (f'<p class="cardnote">{esc(inj)}</p>' if inj else "")
    return (f'<div class="factcard"><dl>{"".join(b for b in bits if b)}</dl>{note}'
            f'<p class="cardnote">Age, games played, injury-report weeks, usage and '
            f'contract terms are <b>observed</b>. Availability and Adj VOR are '
            f'<b>models</b>. Projections and ADP are dated 2026-07-23 and 2026-07-25.</p>'
            f'</div>')


# ---------------------------------------------------------------- draft room
def draft_room(rows, notes):
    def cell(r):
        pill = f'<span class="pos p-{r["pos"]}">{r["pos"]}</span>'
        av = r["avail"]
        bar = ""
        if av:
            pct = max(0, min(100, (av - 0.55) / 0.45 * 100))
            tone = "hi" if av >= 0.90 else ("lo" if av < 0.78 else "mid")
            bar = (f'<span class="availbar {tone}"><i style="width:{pct:.0f}%"></i>'
                   f'</span><span class="availnum">{av:.2f}</span>')
        d = ""
        if r["adp"]:
            gap = round(r["adp"] - r["rank"])
            if abs(gap) >= 15:
                d = f'<b class="{"good" if gap > 0 else "bad"}">{gap:+d}</b>'
        pslug = slug(r["player"])
        name = (f'<a href="players/{pslug}.html">{esc(r["player"])}</a>'
                if r.get("haspage") else esc(r["player"]))
        return (f'<tr data-pos="{r["pos"]}" data-name="{esc(r["player"]).lower()}">'
                f'<td class="num">{r["rank"]}</td>'
                f'<td class="nm">{name}<span class="why">{esc(r["note"])}</span></td>'
                f'<td>{pill}<span class="posrk">{r["pos"]}{r["pos_rank"]}</span></td>'
                f'<td>{esc(r["team"])}</td>'
                f'<td class="num">{fnum(r["age"], "{:.0f}")}</td>'
                f'<td class="num">{r["bye"]}</td>'
                f'<td class="num">{fnum(r["pts"])}</td>'
                f'<td class="num">{r["vor"]:+.0f}</td>'
                f'<td class="num availcell">{bar}</td>'
                f'<td class="num">{r["adj_vor"]:+.0f}</td>'
                f'<td class="num">{r["adp"] if r["adp"] else "—"}</td>'
                f'<td class="num">{d}</td>'
                f'<td><span class="risk r-{r["risk"]}">{r["risk"]}</span></td></tr>')

    head = ("Rk|Player|Pos|Tm|Age|Bye|Proj|VOR|Avail|Adj VOR|ADP|Δ|Risk").split("|")
    ths = "".join(f'<th data-k="{i}">{h}</th>' for i, h in enumerate(head))
    body = "".join(cell(r) for r in rows)
    pills = "".join(f'<button class="posfilter" data-pos="{p}">{p}</button>'
                    for p in ("ALL", "QB", "RB", "WR", "TE", "K", "DST"))
    turn = "".join(f'<span class="pick">{p}</span>' for p in PICKS)
    crumbs = '<div class="crumbs"><a href="index.html">Encyclopedia</a> · <span>Draft Room</span></div>'
    hero = (f'<div class="hero"><p class="kicker">Live board</p><h1>Draft Room</h1>'
            f'<p class="lede">Every player in the file — {len(rows)} of them — sortable '
            f'and filterable. '
            f'Nothing here was typed by hand — it is rendered from '
            f'<code>players.csv</code> and <code>player_context.csv</code> by the same '
            f'arithmetic that builds the vault note.</p></div>')
    controls = (f'<div class="boardbar"><input class="tablefilter" id="bf" '
                f'placeholder="Filter by name, team or archetype…" '
                f'aria-label="Filter board"><div class="posfilters">{pills}</div>'
                f'<span id="boardcount" class="boardcount"></span></div>'
                f'<p class="picknote"><b>Your picks:</b> {turn}</p>')
    legend = ('<p class="legend"><b>VOR</b> value over replacement · '
              '<b>Avail</b> three-year availability, shrunk toward the position mean '
              '(a model) · <b>Adj VOR</b> value after scaling for availability (a model) · '
              '<b>ADP</b> Fantasy Football Calculator PPR proxy, not ESPN · '
              '<b>Δ</b> shown only at 15 slots or more · '
              '<b>Risk</b> role contest, not durability.</p>')
    table = (f'<div class="tablewrap"><table class="sortable board" id="board">'
             f'<thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>')
    return shell("Draft Room", hero + controls + legend + table, notes, depth=0,
                 crumbs=crumbs,
                 desc="The 2026 full-PPR draft board, sortable and filterable.")


# ---------------------------------------------------------------- home
def home(notes, rows, index):
    moc = next((n for n in notes if n.basename == "Fantasy Football"), None)
    order = []
    for i, title in enumerate(READING_ORDER, 1):
        n = index.get(title.lower())
        if n:
            order.append(f'<li><span class="n">{i}</span>'
                         f'<a href="{n.href}">{esc(n.title)}</a>'
                         f'<span class="si-lede">{esc(n.lede)}</span></li>')
    top = "".join(
        f'<tr><td class="num">{r["rank"]}</td>'
        f'<td><a href="draft-room.html">{esc(r["player"])}</a></td>'
        f'<td><span class="pos p-{r["pos"]}">{r["pos"]}</span></td>'
        f'<td class="num">{fnum(r["pts"])}</td><td class="num">{r["vor"]:+.0f}</td>'
        f'<td class="num">{fnum(r["avail"], "{:.2f}")}</td></tr>'
        for r in rows[:10])
    counts = {}
    for n in notes:
        counts[n.dirname] = counts.get(n.dirname, 0) + 1
    cards = "".join(
        f'<a class="seccard" href="{d}/index.html"><b>{SECTION_LABEL[d]}</b>'
        f'<span>{counts[d]} pages</span></a>'
        for d in SECTION_ORDER if d in counts)
    body = f"""
<div class="masthead">
  <p class="mh-date">Full PPR · 12 teams · ESPN · the 1.01 is locked</p>
  <h1 class="mh-title">The Fantasy Football Encyclopedia</h1>
  <p class="mh-sub">2026 season · built for someone who does not watch football</p>
  <div class="mh-rule"></div>
  <p class="mh-note">{esc(moc.lede) if moc else ""}</p>
</div>

<div class="quickgrid">
  <a class="quick" href="draft-room.html"><b>Draft Room</b>
    <span>The whole board, sortable</span></a>
  <a class="quick" href="{index['your league, in one page'].href}"><b>Your league</b>
    <span>The page to reread on draft day</span></a>
  <a class="quick" href="{index['drafting from the 1.01'].href}"><b>From the 1.01</b>
    <span>A written script for picks 1, 24, 25</span></a>
  <a class="quick" href="{index['player archetypes'].href}"><b>Archetypes</b>
    <span>The twelve labels everything resolves to</span></a>
</div>

<h2 class="homeh">Read in this order</h2>
<p class="homesub">Never watched a game? Start at the top and stop after Start Here.
That is enough to draft.</p>
<ol class="readorder">{"".join(order)}</ol>

<h2 class="homeh">The top of the board</h2>
<div class="tablewrap"><table>
<thead><tr><th>Rk</th><th>Player</th><th>Pos</th><th>Proj</th><th>VOR</th><th>Avail</th></tr></thead>
<tbody>{top}</tbody></table></div>
<p class="legend">Rendered from <code>players.csv</code> on {AS_OF}.
<a href="draft-room.html">Open the full board →</a></p>

<h2 class="homeh">Sections</h2>
<div class="seccards">{cards}</div>
"""
    return shell("The Fantasy Football Encyclopedia", body, notes, depth=0,
                 desc=(moc.lede if moc else "2026 fantasy football encyclopedia"))


# ---------------------------------------------------------------- main
def main():
    notes, index = scan()
    players = load_csv("players.csv")
    ctx = {r["player"]: r for r in load_csv("player_context.csv")}
    rows = build_board_rows(players, ctx)
    by_name = {r["player"]: r for r in rows}
    player_notes = {n.basename: n for n in notes if n.dirname == "players"}
    for r in rows:
        r["haspage"] = r["player"] in player_notes

    for n in notes:
        page = note_page(n, notes, index)
        if n.dirname == "players" and n.basename in by_name:
            row = by_name[n.basename]
            page = page.replace('<article class="prose">',
                                factcard(row) + '<article class="prose">', 1)
        write(n.href, page)

    groups = {}
    for n in notes:
        groups.setdefault(n.dirname, []).append(n)
    for d, items in groups.items():
        write(f"{d}/index.html", section_index(d, items, notes))

    write("draft-room.html", draft_room(rows, notes))
    write("index.html", home(notes, rows, index))

    # search index
    si = [{"t": n.title, "u": n.href, "s": SECTION_LABEL[n.dirname], "d": n.lede[:120]}
          for n in notes]
    # Players with their own page are already in the index above; adding the board row
    # too would show the same name twice pointing at the same place.
    si += [{"t": r["player"], "u": "draft-room.html",
            "s": f'{r["pos"]} · board #{r["rank"]}', "d": r["note"][:120]}
           for r in rows[:200] if not r["haspage"]]
    write("assets/search-index.json", json.dumps(si, ensure_ascii=False))

    for f in ("players.csv", "player_context.csv"):
        shutil.copy(VAULT / "Data" / f, OUT / "data" / f)

    print(f"built {len(notes)} note pages + {len(groups)} section indexes "
          f"+ draft room + home")
    print(f"board rows: {len(rows)}; player pages with fact cards: "
          f"{sum(1 for r in rows if r['haspage'])}")
    missing = [n.title for n in notes if not (OUT / n.href).exists()]
    if missing:
        raise SystemExit(f"FATAL: pages not written: {missing}")


if __name__ == "__main__":
    main()
