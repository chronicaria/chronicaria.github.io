#!/usr/bin/env python3
"""Generate 1200x630 PNG social cards into assets/og/.

Dark background, accent bar on the left edge, title + subtitle + site footer.
Uses Pillow's bundled DejaVu fonts; falls back to load_default at size.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = "#101317"
ACCENT = "#5b9dff"
MUTED = "#939ca7"
TEXT = "#e6e9ee"

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "og"

CARDS = [
    ("home.png", "Andrew Park",
     "Duke '28 · mathematics · computer science · quant research"),
    ("daily.png", "The Daily",
     "Sports · AI & Models · Markets · The 2026 Midterms — printed every morning at 6:10"),
    ("league.png", "SMP Basketball League",
     "Ten teams · 435 players · every box score"),
]


def find_font(name: str) -> str | None:
    """Locate a font file bundled with Pillow (or common system dirs)."""
    candidates = []
    try:
        import PIL
        pil_dir = Path(PIL.__file__).parent
        candidates.append(pil_dir / "fonts" / name)
        # matplotlib often ships DejaVu too
    except Exception:
        pass
    try:
        import matplotlib
        candidates.append(Path(matplotlib.__file__).parent
                          / "mpl-data" / "fonts" / "ttf" / name)
    except Exception:
        pass
    candidates += [
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/Library/Fonts") / name,
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def load_font(name: str, size: int) -> ImageFont.ImageFont:
    path = find_font(name)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Pillow >= 10 supports sized default fonts
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_card(filename: str, title: str, subtitle: str) -> Path:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Accent bar down the left edge
    draw.rectangle([0, 0, 2, H], fill=ACCENT)

    title_font = load_font("DejaVuSans-Bold.ttf", 88)
    sub_font = load_font("DejaVuSans.ttf", 34)
    foot_font = load_font("DejaVuSans.ttf", 26)

    margin = 80
    max_w = W - margin * 2

    title_lines = wrap(draw, title, title_font, max_w)
    sub_lines = wrap(draw, subtitle, sub_font, max_w)

    y = 200
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill=TEXT)
        y += 104

    y += 24
    for line in sub_lines:
        draw.text((margin, y), line, font=sub_font, fill=MUTED)
        y += 48

    draw.text((margin, H - 80), "chronicaria.github.io",
              font=foot_font, fill=ACCENT)

    out = OUT_DIR / filename
    img.save(out, "PNG")
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, title, subtitle in CARDS:
        out = make_card(filename, title, subtitle)
        print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
