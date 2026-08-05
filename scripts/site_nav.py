#!/usr/bin/env python3
"""Regenerate every place the list of sections is written down.

There are three of them — the nav block on the top-level pages, the SECTIONS
array inside assets/hub.js, and sitemap.xml — and keeping them in sync by hand
is how a project ends up listed in the dropdown but missing from the band. Edit
PROJECTS below and run this; it rewrites all three.

    python3 scripts/site_nav.py
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOMAIN = "https://chronicaria.github.io"

INTERESTS = [
    ("/sports.html", "Sports"),
    ("/music.html", "Music"),
    ("/literature.html", "Literature"),
    ("/weather.html", "Temperature"),
]

PROJECTS = [
    ("/fantasy/", "Fantasy Encyclopedias"),
    ("/valorant/", "Valorant MWPA"),
    ("/quant-internships/", "Quant Internships"),
    ("/concerto/", "Concerto Ranker"),
    ("/nyc-weather/", "Weather Dashboard"),
    ("/winter-trip/", "Italy, winter 2026–27"),
    ("/equipotential/", "Live Paper"),
]

# Top-level pages, and the href each should mark as the current page.
PAGES = {
    "index.html": "/",
    "sports.html": "/sports.html",
    "music.html": "/music.html",
    "literature.html": "/literature.html",
    "weather.html": "/weather.html",
    "daily/index.html": "/daily/",
    "daily/ai.html": "/daily/",
    "daily/archive.html": "/daily/",
    "daily/elections.html": "/daily/",
    "daily/markets.html": "/daily/",
    "daily/math.html": "/daily/",
    "daily/sports.html": "/daily/",
    "404.html": None,
}

# Extra sitemap entries that aren't in the nav.
SITEMAP_EXTRA = [
    "/daily/sports.html", "/daily/ai.html", "/daily/markets.html",
    "/daily/elections.html", "/daily/math.html", "/daily/archive.html",
]

# In the nav, out of the sitemap. Every page under /valorant/ ships
# `<meta name="robots" content="noindex, nofollow">` on purpose, and a sitemap is a request TO
# index — listing a page in one while forbidding it in the other is a contradiction a crawler
# reports back as an error. The nav entry stays: people navigate there, crawlers do not.
SITEMAP_SKIP = {"/valorant/"}


def drop(title, items, active):
    hit = any(h == active for h, _ in items)
    cls = "nav-drop-btn active" if hit else "nav-drop-btn"
    links = "\n".join(
        f'          <a{" class=\"active\"" if h == active else ""} href="{h}">{l}</a>'
        for h, l in items
    )
    return (
        '      <div class="nav-drop">\n'
        f'        <button type="button" class="{cls}">{title}</button>\n'
        '        <div class="nav-drop-menu">\n'
        f"{links}\n"
        "        </div>\n"
        "      </div>"
    )


def nav_inner(active):
    home = ' class="active"' if active == "/" else ""
    news = ' class="active"' if active == "/daily/" else ""
    return "\n".join([
        f'      <a{home} href="/">Home</a>',
        f'      <a{news} href="/daily/">Newspaper</a>',
        drop("Interests", INTERESTS, active),
        drop("Projects", PROJECTS, active),
        "    ",
    ])


NAV_RE = re.compile(r'(<nav class="primary-nav"[^>]*>)(.*?)(</nav>)', re.S)


def write_nav():
    n = 0
    for rel, active in PAGES.items():
        p = ROOT / rel
        if not p.exists():
            print(f"  skip (missing): {rel}")
            continue
        src = p.read_text(encoding="utf-8")
        if not NAV_RE.search(src):
            print(f"  skip (no nav):  {rel}")
            continue
        new = NAV_RE.sub(lambda m: m.group(1) + "\n" + nav_inner(active) + m.group(3), src, count=1)
        if new != src:
            p.write_text(new, encoding="utf-8")
            n += 1
    print(f"  nav: {n} pages rewritten")


def write_hub():
    p = ROOT / "assets" / "hub.js"
    src = p.read_text(encoding="utf-8")
    body = "\n".join(f'    {{ href: "{h}", label: "{l}" }},' for h, l in PROJECTS)
    new, count = re.subn(
        r"(var SECTIONS = \[\n).*?(\n  \];)",
        lambda m: m.group(1) + body + m.group(2),
        src,
        count=1,
        flags=re.S,
    )
    if not count:
        raise SystemExit("hub.js: could not find the SECTIONS array")
    if new != src:
        p.write_text(new, encoding="utf-8")
        print(f"  hub.js: SECTIONS rewritten ({len(PROJECTS)} entries)")
    else:
        print("  hub.js: already current")


def write_sitemap():
    hrefs = ["/"] + ["/daily/"] + SITEMAP_EXTRA + [h for h, _ in INTERESTS] + [h for h, _ in PROJECTS]
    seen, ordered = set(SITEMAP_SKIP), []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    lines = "\n".join(f"  <url><loc>{DOMAIN}{h}</loc></url>" for h in ordered)
    p = ROOT / "sitemap.xml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{lines}\n"
        "</urlset>\n",
        encoding="utf-8",
    )
    print(f"  sitemap.xml: {len(ordered)} urls")


if __name__ == "__main__":
    write_nav()
    write_hub()
    write_sitemap()
