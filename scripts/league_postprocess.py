#!/usr/bin/env python3
"""Post-process the generated SMP league pages for life inside andrewparkus.github.io.

The league generator (scripts/league_generator.py) emits a standalone site into
league/. This script stitches it into the parent site: a "← andrewpark.us" link
at the end of every page's primary nav, resolved through each page's data-root
so it works at any directory depth, plus the main site's theme-init snippet
right after <head> so league pages honor the saved light/dark preference. Run
after every regeneration (the build-league workflow does this automatically).
"""

import re
import sys
from pathlib import Path

LEAGUE = Path(__file__).resolve().parent.parent / "league"
ROOT_RE = re.compile(r'data-root="([^"]*)"')
NAV_CLOSE_RE = re.compile(r"</nav>", re.I)
HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.I)
BACKLINK_MARK = "back-main"
THEME_MARK = "dataset.theme"
THEME_SNIPPET = (
    '<script>document.documentElement.dataset.theme = '
    'localStorage.getItem("theme") || '
    '(matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");'
    "</script>"
)


def main():
    changed = skipped = 0
    for page in LEAGUE.rglob("*.html"):
        text = page.read_text()
        dirty = False

        if THEME_MARK not in text:
            new, n = HEAD_OPEN_RE.subn(lambda m: m.group(0) + THEME_SNIPPET, text, count=1)
            if n:
                text = new
                dirty = True

        if BACKLINK_MARK not in text:
            m = ROOT_RE.search(text)
            root = m.group(1) if m else ""
            backlink = f'<a class="{BACKLINK_MARK}" href="{root}../index.html" title="Back to the main site">← andrewpark</a>'
            new, n = NAV_CLOSE_RE.subn(backlink + "</nav>", text, count=1)
            if n:
                text = new
                dirty = True

        if dirty:
            page.write_text(text)
            changed += 1
        else:
            skipped += 1
    print(f"league postprocess: {changed} pages stitched, {skipped} already done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
