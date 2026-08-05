"""Contrast and colour-vision checks for the MWPA site's palette.

This guarded two sites until the RWPA dashboard that shared this directory was
retired and the MWPA site moved up into its place. The `SIB_*` tables below are
that dashboard's palette, kept unread for one reason: they are the measurements
the surviving comments quote when they say why a token sits where it does, and
deleting them would leave those numbers unsourced. Nothing runs them.

The rule, first stated in the retired style.css and unchanged since: every token that carries TEXT clears 4.5:1
against the WORST surface it can land on, and that surface is --panel-3 in
both themes (the table row-hover plate). Marks clear 3:1 against whatever
they composite onto -- including at partial opacity, which is why blend()
exists: a fill at .38 alpha is not the colour you wrote down.

The dichromacy report is here because the palette now uses green/red for the
sign of a probability change. Red and green are the one pair the two common
forms of colour blindness cannot separate, so the numbers below are the
evidence for why the +/- glyph and the direction-from-zero are load-bearing
rather than decorative. If a future edit softens either sign token, this
prints the damage.

TWO THINGS THIS FILE USED TO BE BLIND TO, and both are closed below.

1. IT GUARDED A COPY. The token tables below are literals, and nothing ever
   compared them with the stylesheets they claim to describe. A token could
   move in quad-site.css and this file would still print PASS, because it was
   never reading it. `check_stylesheets()` now parses both sheets and fails
   the run when a guarded token here differs from the value that actually
   ships. A checker that cannot detect the change it exists to detect is
   worse than no checker, because it certifies.

2. IT COULD NOT SEE AN IMAGE. The site ships full-colour PNGs, and every pixel
   of one is outside a hex table. `image_report()` decodes each PNG, composites
   every pixel with alpha >= IMAGE_ALPHA onto every surface that family lands
   on, and measures the real distribution. Three families ship and none of them
   is an information mark: each is identification beside a word that is always
   rendered, so each is held to a LEGIBILITY floor and its 1px --rule-strong
   box is what clears the mark floor.

   THE REPORT IS ALSO WHAT FIXES A FAMILY. The weapon silhouettes measured 1.53
   median on the light surface -- under the legibility floor, i.e. fainter than
   a table border -- and the answer was to change the surface, not the floor:
   they now land on --art-plate, which is one colour in both themes, and there
   they measure 6.99 with all nineteen clearing 3:1. A family that fails is a
   slot that is wrong until a slot has been tried and failed too.

    python3 contrast.py
"""
import re
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    r, g, b = rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg, bg, alpha):
    """The colour a partially transparent mark actually composites to."""
    f, b = rgb(fg), rgb(bg)
    return "#%02x%02x%02x" % tuple(round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3))


def dichromat(h, kind):
    """Vienot 1999 linear-RGB simulation. Enough to answer 'do these two still
    separate', which is the only question asked of it here."""
    r, g, b = (lin(c) for c in rgb(h))
    if kind == "deuteranope":
        rr = 0.625 * r + 0.375 * g
        gg = 0.700 * r + 0.300 * g
        bb = 0.300 * g + 0.700 * b
    else:  # protanope
        rr = 0.567 * r + 0.433 * g
        gg = 0.558 * r + 0.442 * g
        bb = 0.242 * g + 0.758 * b

    def enc(v):
        v = max(0.0, min(1.0, v))
        return round(255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))

    return "#%02x%02x%02x" % (enc(rr), enc(gg), enc(bb))


# ---------------------------------------------------------------- style.css
# The sibling RWPA dashboard. These four dicts and three lists were deleted
# when the quad palette was added, which left another agent's stylesheet with
# no checker at all. They are back, unchanged, and reported alongside.
SIB_DARK = {
    "bg": "#0a0f16", "panel": "#101923", "panel-2": "#0d151e", "panel-3": "#182430",
    "line": "#243444", "text": "#ece8e1", "muted": "#9dabb9", "faint": "#8695a4",
    "accent": "#ff5a67", "martin": "#eaa947", "snorlax": "#3fb9c9",
    "win": "#4fc48a", "loss": "#f0757f", "pos": "#66c77e", "neg": "#ef7560",
}
SIB_LIGHT = {
    "bg": "#f4f2ed", "panel": "#fbfaf7", "panel-2": "#edeae3", "panel-3": "#e2ded4",
    "line": "#d3cdc1", "text": "#16202b", "muted": "#4c5763", "faint": "#515c69",
    "accent": "#c31229", "martin": "#7c5007", "snorlax": "#0a6070",
    "win": "#136a41", "loss": "#bb2731", "pos": "#106a32", "neg": "#ad3424",
}
SIB_TEXT_TOKENS = ["text", "muted", "faint", "accent", "martin", "snorlax",
                   "win", "loss", "pos", "neg"]
SIB_SURFACES = ["bg", "panel", "panel-2", "panel-3"]
# .ci-range used to be alpha .38, which drew the interval fainter than the
# point estimate it qualifies -- on a page whose whole argument is that the
# interval swallows the difference. It is now full strength and thin, with the
# point estimate demoted to a notch, so visual weight matches confidence.
# NOT listed: 1px hairlines (--line borders). They are structure, not data.
SIB_MARKS = [
    ("pos", 1.0, ["panel-2", "panel-3"]),     # round-sheet magnitude fill
    ("neg", 1.0, ["panel-2", "panel-3"]),
    # .ci-range, and the round sheet's win-probability event marks on --panel-2
    ("martin", 1.0, ["panel", "panel-2", "panel-3"]),
    ("snorlax", 1.0, ["panel", "panel-2", "panel-3"]),
    # The walk's null corridor: two dashed curves at full strength.
    ("muted", 1.0, ["panel"]),
]

# ----------------------------------------------------------- quad-site.css
DARK = {
    "ground": "#0b1416", "field": "#121d20", "well": "#081011",
    "ink": "#e6ecec", "quiet": "#9aabad",
    "rule": "#334750", "rule-strong": "#5b737b",
    "martin": "#af841a", "snorlax": "#00a1c6",
    "themarias": "#a16dff", "trzzcko": "#e35b8b",
    "pos": "#4ea86e", "neg": "#e2705a",
    # THE ONE SURFACE THAT DOES NOT MOVE WITH THE THEME. Riot's weapon art is a
    # near-white silhouette on transparency: it measures 6.93 median on the dark
    # measurement surface and 1.53 on the light one, which is under the legibility
    # floor -- the family reads perfectly in one theme and is a ghost in the other.
    # A plate fixes that at the slot rather than by dropping the family: the art
    # lands on ONE surface in both themes, so there is one number for it and no
    # theme in which it is worse. It is written into both blocks of the stylesheet
    # with the same value, so check_stylesheets() enforces the invariance rather
    # than a comment asserting it.
    "art-plate": "#111c1f",
    "wash-alpha": 0.105,
}
LIGHT = {
    "ground": "#e7eceb", "field": "#f5f9f8", "well": "#dee4e3",
    "ink": "#0d1719", "quiet": "#4f5c5d",
    "rule": "#a4b2b0", "rule-strong": "#69797c",
    "martin": "#915405", "snorlax": "#006999",
    "themarias": "#7a2cd6", "trzzcko": "#be0b67",
    "pos": "#0f6a37", "neg": "#a83a22",
    "art-plate": "#111c1f",     # the same value as DARK, and that is the point
    "wash-alpha": 0.085,
}

# All four player hues are listed, and they are listed as TEXT. Half the
# palette used to be unguarded here: --themarias and --trzzcko were absent
# from both lists, so nothing checked them. They do double duty -- they stroke
# a line in SVG and they set a player's name and a line-end label as
# characters -- so the binding floor for every one of them is 4.5:1, not 3:1.
TEXT_TOKENS = ["ink", "quiet", "martin", "snorlax", "themarias", "trzzcko",
               "pos", "neg"]
SURFACES = ["ground", "field", "well"]

# Marks that carry INFORMATION: (token, alpha, surfaces).
#
# .ci-range used to be alpha .38, which drew the interval fainter than the
# point estimate it qualifies -- on a page whose whole argument is that the
# interval swallows the difference. It is now full strength and thin, with the
# point estimate demoted to a notch, so visual weight matches confidence.
# Anything under 1.0 here failed the floor in the light theme and was fixed by
# removing the transparency rather than by lowering the floor.
#
# NOT listed: 1px hairlines (--line borders). They are structure, not data --
# no reader ever has to resolve one to read a value -- and holding them to 3:1
# would turn every table rule into a black line. The walk's excluded-round
# spans used to be a --line fill at ~1.05:1, i.e. a mark pretending to be
# structure; that is now a hatch, which reads without shouting.
# Marks that carry INFORMATION. The surface list now includes the composited
# wash -- the one fill in the system, --ink at .105 (dark) / .085 (light)
# between the curve and the null -- because a mark drawn on top of a fill is
# not the colour you wrote down, and every hue disc on the match figure lands
# there.
#
# --rule-strong is here and --rule is not, and that split is the point. A
# gridline, an axis and a round-boundary tick are things a reader has to
# resolve to read a value, so they are information and clear 3:1. A table's
# hairline border is structure -- nobody ever reads a value off it -- and
# holding it to 3:1 would turn every rule on the page into a black line.
MARKS = [
    ("pos", 1.0, ["field", "well"]),
    ("neg", 1.0, ["field", "well"]),
    ("martin", 1.0, ["ground", "field", "well", "wash"]),
    ("snorlax", 1.0, ["ground", "field", "well", "wash"]),
    ("themarias", 1.0, ["ground", "field", "well", "wash"]),
    ("trzzcko", 1.0, ["ground", "field", "well", "wash"]),
    ("quiet", 1.0, ["field", "wash"]),
    ("ink", 1.0, ["field", "wash"]),      # the null rule, and the curve
    ("rule-strong", 1.0, ["ground", "field", "well"]),
]

TEXT_FLOOR, MARK_FLOOR = 4.5, 3.0

# ------------------------------------------------------------- image families
# A picture is not a hex value, so the floor it is held to has to say which job
# it is doing, and the grain it is measured at has to match the decision it
# guards. The decision here is WHETHER A FOLDER SHIPS, so the gate is on the
# family and the per-file distribution is printed underneath it rather than
# hidden behind a pass.
#
#   MARK_FLOOR (3:1) is for anything a reader must RESOLVE to read a value.
#   No image on this site is ever that, and the check that says so is on the
#   SLOT rather than on the art: the 1px --rule-strong box around every
#   portrait is the thing that clears 3:1, on every surface, in both themes.
#   That is asserted below and not merely written in a comment.
#
#   IMAGE_FLOOR is legibility, and it is derived rather than chosen: it is the
#   contrast of --rule, this design's structural hairline, on the worst
#   surface it lands on. A hairline is the faintest thing the system considers
#   visible at all, so artwork that reads worse than a table border is not
#   identifying anything and its folder does not ship.
#
# IMAGE_ALPHA is the cutoff for "this pixel is ink rather than antialiasing".
IMAGE_ALPHA = 0.4
IMAGE_FLOOR = min(ratio(pal["rule"], pal[surface])
                  for pal in (DARK, LIGHT) for surface in SURFACES)
#
# THREE FAMILIES SHIP AND THEY DO NOT SHARE A SURFACE LIST, because the gate is
# per family and the honest answer differed per family:
#
#   agent   transparent portraits, on the page surfaces. 2.67 dark / 5.75 light.
#   rank    Riot's tier emblems, on the page surfaces. 2.35 dark / 3.60 light --
#           over the hairline everywhere, so no plate is needed and adding one
#           would COST it 1.25 on the light surface. Measured, not assumed.
#   weapon  near-white silhouettes. 6.93 dark / 1.53 light on the page surfaces:
#           under the legibility floor in one theme. It lands on --art-plate
#           instead, which does not move with the theme, and there it measures
#           6.99 with all 19 files clearing the mark floor. The family was fixed
#           at the slot; it was not dropped and the floor was not lowered.
IMAGE_FAMILIES = [
    # (folder, what it does, which surfaces it can land on, the slot that is the mark)
    (HERE / "quad" / "assets" / "agent",
     "identification beside a word that is always rendered",
     ["field", "well"], "rule-strong"),
    (HERE / "quad" / "assets" / "rank",
     "recognition beside the division word, which is what encodes",
     ["field", "well"], "rule-strong"),
    (HERE / "quad" / "assets" / "weapon",
     "one distinct silhouette per breakdown row, on a theme-invariant plate",
     ["art-plate"], "rule-strong"),
]


def wash_on(pal, surface):
    """The one fill in the system, composited. It carries no side semantics --
    it means distance from the null -- so there is one of it, not two."""
    return blend(pal["ink"], pal[surface], pal["wash-alpha"])


def report(name, pal, text_tokens=None, surfaces_=None, marks=None):
    text_tokens = TEXT_TOKENS if text_tokens is None else text_tokens
    surfaces_ = SURFACES if surfaces_ is None else surfaces_
    marks = MARKS if marks is None else marks
    ok = True
    print(f"\n=== {name} — text floor {TEXT_FLOOR}, mark floor {MARK_FLOOR} ===")
    for t in text_tokens:
        vals = {s: ratio(pal[t], pal[s]) for s in surfaces_}
        low = min(vals, key=vals.get)
        flag = "" if vals[low] >= TEXT_FLOOR else "   <-- BELOW TEXT FLOOR"
        ok &= vals[low] >= TEXT_FLOOR
        print(f"  --{t:<11} {pal[t]}  worst {vals[low]:5.2f} on --{low}{flag}")

    print("  -- marks (composited) --")
    for token, alpha, surfaces in marks:
        for s in surfaces:
            bg = wash_on(pal, "field") if s == "wash" else pal[s]
            eff = blend(pal[token], bg, alpha) if alpha < 1 else pal[token]
            r = ratio(eff, bg)
            flag = "" if r >= MARK_FLOOR else "   <-- BELOW MARK FLOOR"
            ok &= r >= MARK_FLOOR
            name_s = "wash-on-field" if s == "wash" else s
            print(f"  --{token:<11} on --{name_s:<13} {r:5.2f}{flag}")
    return ok


# --------------------------------------------------------------- PNG pixels

def read_png(path):
    """Every pixel of an 8-bit RGBA PNG, as (r, g, b, a) tuples.

    Hand-rolled because this repository has no image library and must not grow
    one to run its own checker. Only the format the assets are actually in is
    supported -- colour type 6, bit depth 8, no interlace -- and anything else
    raises rather than being guessed at.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path.name)
    width = height = depth = colour = interlace = None
    idat = bytearray()
    i = 8
    while i < len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        kind = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + length]
        if kind == b"IHDR":
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            depth, colour, _, _, interlace = body[8], body[9], body[10], body[11], body[12]
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        i += 12 + length
    if (depth, colour, interlace) != (8, 6, 0):
        raise ValueError("%s is depth %s colour %s interlace %s; expected 8/6/0"
                         % (path.name, depth, colour, interlace))

    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(height * stride)
    previous = bytearray(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - 4] if x >= 4 else 0
            b = previous[x]
            c = previous[x - 4] if x >= 4 else 0
            if filter_type == 0:
                value = line[x]
            elif filter_type == 1:
                value = line[x] + a
            elif filter_type == 2:
                value = line[x] + b
            elif filter_type == 3:
                value = line[x] + (a + b) // 2
            elif filter_type == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                value = line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)
            else:
                raise ValueError("%s row %d: filter %d" % (path.name, row, filter_type))
            line[x] = value & 0xFF
        out[row * stride:(row + 1) * stride] = line
        previous = line
    return [tuple(out[p:p + 4]) for p in range(0, len(out), 4)]


def pixel_ratios(pixels, surface, alpha_floor):
    """Every ink pixel's contrast against one surface, composited onto it.

    A PNG served as an <img> has no plate under it but the page's own surface,
    so the colour a reader sees for a half-transparent pixel is the composite and
    not the stored value. Pixels under the alpha floor are antialiasing and
    are not ink.
    """
    back = rgb(surface)
    out = []
    for r, g, b, a in pixels:
        alpha = a / 255
        if alpha < alpha_floor:
            continue
        composite = "#%02x%02x%02x" % tuple(
            round(v * alpha + back[i] * (1 - alpha)) for i, v in enumerate((r, g, b)))
        out.append(ratio(composite, surface))
    return out


def median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def render_box(sheet, width_token, height_token):
    """The box a family is drawn into, read out of the stylesheet that declares it.

    Same rule as everywhere else in this system: one literal per measurement,
    and it lives in the file that owns the decision. A silhouette measured at
    96px says nothing about a silhouette a reader sees at 42.
    """
    text = sheet.read_text(encoding="utf-8")
    out = []
    for token in (width_token, height_token):
        found = re.search(re.escape(token) + r":\s*(\d+)px", text)
        if not found:
            raise ValueError("%s declares no %s" % (sheet.name, token))
        out.append(int(found.group(1)))
    return tuple(out)


def silhouette(path, box, alpha_floor=None):
    """One file's ink mask AT RENDER SIZE, contain-fitted into the box.

    Nearest-neighbour, because this is a shape question and not a quality one:
    the mask answers "which pixels of the slot does this weapon cover", which
    is what a reader discriminating two icons at a glance is actually using.
    """
    alpha_floor = IMAGE_ALPHA if alpha_floor is None else alpha_floor
    data = path.read_bytes()[:24]
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    pixels = read_png(path)
    box_w, box_h = box
    scale = min(box_w / width, box_h / height)
    draw_w, draw_h = max(1, round(width * scale)), max(1, round(height * scale))
    left, top = (box_w - draw_w) // 2, (box_h - draw_h) // 2
    mask = [0] * (box_w * box_h)
    for y in range(draw_h):
        row = min(height - 1, int(y / scale)) * width
        for x in range(draw_w):
            if pixels[row + min(width - 1, int(x / scale))][3] / 255 >= alpha_floor:
                mask[(y + top) * box_w + (x + left)] = 1
    return mask


def silhouette_overlap(folder, first, second, box):
    """Intersection over union of two files' rendered silhouettes.

    The number that answers "does this icon speed or slow scanning" for a
    column where the SAME icons recur: two shapes that cover mostly the same
    pixels of the same slot do not discriminate, however different the objects
    they depict are. It is a property of the art at the size it ships, so it is
    measured here rather than asserted in prose.
    """
    a = silhouette(folder / ("%s.png" % first), box)
    b = silhouette(folder / ("%s.png" % second), box)
    both = sum(1 for x, y in zip(a, b) if x and y)
    either = sum(1 for x, y in zip(a, b) if x or y)
    return both / either if either else 0.0


def image_family(folder, surfaces=("field", "well")):
    """Per file, per surface: the median ink contrast and the share clearing 3:1."""
    pairs = [("dark --" + s, DARK[s]) for s in surfaces]
    pairs += [("light --" + s, LIGHT[s]) for s in surfaces]
    rows = []
    for path in sorted(folder.glob("*.png")):
        pixels = read_png(path)
        per_surface = {}
        for label, hexed in pairs:
            ratios = pixel_ratios(pixels, hexed, IMAGE_ALPHA)
            per_surface[label] = (median(ratios),
                                  sum(1 for r in ratios if r >= MARK_FLOOR) / max(len(ratios), 1))
        rows.append((path.name, per_surface))
    return rows, [label for label, _ in pairs]


def image_report(families=None, quiet=False):
    """The fourth report: the one that produced this round's deletions.

    Gates, in the order they are printed:
      1. the slot border clears the mark floor on every surface the art lands on;
      2. the family's median file clears the legibility floor on every one of them.
    Everything else is published, including the files that read worst.
    """
    families = IMAGE_FAMILIES if families is None else families
    ok = True
    summary = {}
    if not quiet:
        print("\n=== image families — ink alpha >= %.1f, legibility floor %.2f "
              "(--rule, the structural hairline), mark floor %.1f ==="
              % (IMAGE_ALPHA, IMAGE_FLOOR, MARK_FLOOR))
    for folder, job, surfaces, slot in families:
        if not folder.is_dir():
            if not quiet:
                print("  %-14s ABSENT — nothing on disk, nothing to check" % (folder.name + "/"))
            continue
        rows, labels = image_family(folder, surfaces)
        if not rows:
            if not quiet:
                print("  %-14s EMPTY" % (folder.name + "/"))
            continue

        slot_worst = min(ratio(pal[slot], pal[s]) for pal in (DARK, LIGHT) for s in surfaces)
        ok &= slot_worst >= MARK_FLOOR
        # The gate is at the grain of the decision: a folder ships or it does not.
        per_surface = {label: median([row[label][0] for _, row in rows]) for label in labels}
        family_worst = min(per_surface.values())
        ok &= family_worst >= IMAGE_FLOOR
        # And the two numbers that say what the art is NOT: how many files could be
        # read as a mark, and how many fall under the hairline on some surface.
        mark_grade = sum(1 for _, row in rows if min(m for m, _ in row.values()) >= MARK_FLOOR)
        faint = sorted((min(m for m, _ in row.values()), name) for name, row in rows)
        summary[folder.name] = {
            "files": len(rows), "family_worst": family_worst, "slot": slot_worst,
            "mark_grade": mark_grade, "faintest": faint[:3],
            "clear_share": {label: sum(1 for _, row in rows if row[label][0] >= MARK_FLOOR)
                            for label in labels},
        }
        if quiet:
            continue
        print("  %-14s %d files · %s" % (folder.name + "/", len(rows), job))
        print("     slot --%-12s %5.2f worst of %d surfaces%s"
              % (slot, slot_worst, len(labels),
                 "" if slot_worst >= MARK_FLOOR else "   <-- SLOT BELOW MARK FLOOR"))
        for label in labels:
            print("     %-14s median file %5.2f   %d of %d files clear %.1f"
                  % (label, per_surface[label], summary[folder.name]["clear_share"][label],
                     len(rows), MARK_FLOOR))
        print("     family worst %5.2f against the %.2f hairline%s"
              % (family_worst, IMAGE_FLOOR,
                 "" if family_worst >= IMAGE_FLOOR else "   <-- BELOW LEGIBILITY FLOOR"))
        # The sentence is derived, not typed. A family every one of whose files clears
        # 3:1 everywhere is a family that COULD be misread as a mark, and saying "no
        # border rescues both ends" about it would be this file certifying a fiction.
        print("     %d of %d files clear the mark floor on every surface" % (mark_grade, len(rows)))
        if mark_grade == len(rows):
            print("     — legible everywhere, which is a reason to watch it, not to trust it:")
            print("     the SLOT is the mark, the picture is not, and never may be.")
        else:
            print("     — and the sets that fail run in opposite directions by theme, so no")
            print("     filter or border rescues both ends. The SLOT is the mark; the picture")
            print("     is not, and never may be.")
        print("     faintest: %s" % ", ".join("%s %.2f" % (name, value) for value, name in faint[:3]))
    image_report.summary = summary
    return ok


# ------------------------------------------------------- the sheets themselves

STYLESHEETS = [
    # (path, theme selector -> which literal table this file guards)
    (HERE / "quad-site.css", {":root": DARK, ':root[data-theme="light"]': LIGHT},
     {"ground": "--ground", "field": "--field", "well": "--well", "ink": "--ink",
      "quiet": "--quiet", "rule": "--rule", "rule-strong": "--rule-strong",
      "martin": "--martin", "snorlax": "--snorlax", "themarias": "--themarias",
      "trzzcko": "--trzzcko", "pos": "--up", "neg": "--down",
      # Guarded in BOTH blocks against the SAME literal, which is how the sheet's
      # claim that this surface is theme-invariant becomes a thing that fails.
      "art-plate": "--art-plate"}),
]


def declared_tokens(text, selector):
    """The custom properties declared in one top-level block of a stylesheet."""
    pattern = re.compile(re.escape(selector) + r"\s*\{(.*?)\}", re.S)
    found = {}
    for block in pattern.finditer(text):
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block.group(1)):
            found.setdefault(name, value.strip())
    return found


def check_stylesheets():
    """Fail when a guarded token differs from the value the stylesheet ships.

    This is the check whose absence let a proof move --rule-strong on the light
    theme and still be reported as verified. The tables above are a copy; this
    makes the copy accountable to the original.
    """
    ok = True
    print("\n=== stylesheet tokens — the tables above against what ships ===")
    for path, blocks, mapping in STYLESHEETS:
        text = path.read_text(encoding="utf-8")
        for selector, palette in blocks.items():
            declared = declared_tokens(text, selector)
            for key, custom_property in mapping.items():
                shipped = declared.get(custom_property)
                guarded = palette[key]
                if shipped is None:
                    print("  %s %s  %s is not declared" % (path.name, selector, custom_property))
                    ok = False
                elif shipped.lower() != guarded.lower():
                    print("  %s %s  %s ships %s, guarded as %s   <-- DRIFT"
                          % (path.name, selector, custom_property, shipped, guarded))
                    ok = False
    if ok:
        print("  %d tokens across %d blocks match the shipped stylesheets."
              % (sum(len(m) * len(b) for _, b, m in STYLESHEETS), 2 * len(STYLESHEETS)))
    return ok


def dichromacy(name, pal):
    print(f"\n=== {name} — sign pair under colour blindness ===")
    for kind in ("deuteranope", "protanope"):
        p, n = dichromat(pal["pos"], kind), dichromat(pal["neg"], kind)
        print(f"  {kind:<12} pos {p} vs neg {n}   luminance separation {ratio(p, n):4.2f}")
    print("  -> the +/- glyph and direction-from-zero are why this is survivable.")
    print("     Do not remove either as redundant.")


if __name__ == "__main__":
    results = [
        report("quad-site.css DARK", DARK),
        report("quad-site.css LIGHT", LIGHT),
        check_stylesheets(),
        image_report(),
    ]
    dichromacy("quad-site.css DARK", DARK)
    dichromacy("quad-site.css LIGHT", LIGHT)
    ok = all(results)
    print("\nPASS" if ok else "\nFAIL — lift the flagged tokens")
    raise SystemExit(0 if ok else 1)
