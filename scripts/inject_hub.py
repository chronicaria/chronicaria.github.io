#!/usr/bin/env python3
"""Add the shared hub band to every page of every sub-project.

Idempotent: pages that already carry the tag are skipped, so re-run it after
rebuilding any sub-project. Run from anywhere: python3 scripts/inject_hub.py

One <script> before </head>. The projects keep their own markup and styles;
hub.js renders in a shadow root so nothing collides.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = [
    "concerto",
    "fantasy-basketball",
    "fantasy-football",
    "winter-trip",
    "nyc-weather",
    "valorant",
    "paper",
    "rome-wiki",
]

TAG = '<script defer src="/assets/hub.js"></script>'

added = skipped = 0
per_dir = {}

for d in DIRS:
    base = ROOT / d
    if not base.is_dir():
        print(f"  MISSING: {d}", file=sys.stderr)
        continue
    n = 0
    for p in base.rglob("*.html"):
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "assets/hub.js" in src:
            skipped += 1
            continue
        low = src.lower()
        i = low.rfind("</head>")
        if i == -1:
            # No head (fragment or oddly-built page) — fall back to end of body.
            i = low.rfind("</body>")
            if i == -1:
                skipped += 1
                continue
        p.write_text(src[:i] + TAG + src[i:], encoding="utf-8")
        n += 1
        added += 1
    per_dir[d] = n

for d, n in per_dir.items():
    print(f"  {n:>5} pages  {d}")
print(f"\ninjected: {added}   skipped: {skipped}")
