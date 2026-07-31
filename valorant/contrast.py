"""Contrast and colour-vision checks for the RWPA dashboard palette.

The rule stated in style.css: every token that carries TEXT clears 4.5:1
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

    python3 contrast.py
"""


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


DARK = {
    "bg": "#0a0f16", "panel": "#101923", "panel-2": "#0d151e", "panel-3": "#182430",
    "line": "#243444", "text": "#ece8e1", "muted": "#9dabb9", "faint": "#8695a4",
    "accent": "#ff5a67", "martin": "#eaa947", "snorlax": "#3fb9c9",
    "win": "#4fc48a", "loss": "#f0757f", "pos": "#66c77e", "neg": "#ef7560",
}
LIGHT = {
    "bg": "#f4f2ed", "panel": "#fbfaf7", "panel-2": "#edeae3", "panel-3": "#e2ded4",
    "line": "#d3cdc1", "text": "#16202b", "muted": "#4c5763", "faint": "#515c69",
    "accent": "#c31229", "martin": "#7c5007", "snorlax": "#0a6070",
    "win": "#136a41", "loss": "#bb2731", "pos": "#106a32", "neg": "#ad3424",
}

TEXT_TOKENS = ["text", "muted", "faint", "accent", "martin", "snorlax",
               "win", "loss", "pos", "neg"]
SURFACES = ["bg", "panel", "panel-2", "panel-3"]

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
MARKS = [
    ("pos", 1.0, ["panel-2", "panel-3"]),     # round-sheet magnitude fill
    ("neg", 1.0, ["panel-2", "panel-3"]),
    # .ci-range, and the round sheet's win-probability event marks on --panel-2
    ("martin", 1.0, ["panel", "panel-2", "panel-3"]),
    ("snorlax", 1.0, ["panel", "panel-2", "panel-3"]),
    # The walk's null corridor: two dashed curves, drawn at full strength for
    # the reason in the paragraph above -- the alternative, a translucent plate
    # behind the two lines, is the failure this file already made once.
    ("muted", 1.0, ["panel"]),
]

TEXT_FLOOR, MARK_FLOOR = 4.5, 3.0


def report(name, pal):
    ok = True
    print(f"\n=== {name} — text floor {TEXT_FLOOR}, mark floor {MARK_FLOOR} ===")
    for t in TEXT_TOKENS:
        vals = {s: ratio(pal[t], pal[s]) for s in SURFACES}
        low = min(vals, key=vals.get)
        flag = "" if vals[low] >= TEXT_FLOOR else "   <-- BELOW TEXT FLOOR"
        ok &= vals[low] >= TEXT_FLOOR
        print(f"  --{t:<8} {pal[t]}  worst {vals[low]:5.2f} on --{low}{flag}")

    print("  -- marks (composited) --")
    for token, alpha, surfaces in MARKS:
        for s in surfaces:
            eff = blend(pal[token], pal[s], alpha) if alpha < 1 else pal[token]
            r = ratio(eff, pal[s])
            flag = "" if r >= MARK_FLOOR else "   <-- BELOW MARK FLOOR"
            ok &= r >= MARK_FLOOR
            a = f"@{alpha:.2f}" if alpha < 1 else "     "
            print(f"  --{token:<8}{a} on --{s:<8} {r:5.2f}{flag}")
    return ok


def dichromacy(name, pal):
    print(f"\n=== {name} — sign pair under colour blindness ===")
    for kind in ("deuteranope", "protanope"):
        p, n = dichromat(pal["pos"], kind), dichromat(pal["neg"], kind)
        print(f"  {kind:<12} pos {p} vs neg {n}   luminance separation {ratio(p, n):4.2f}")
    print("  -> the +/- glyph and direction-from-zero are why this is survivable.")
    print("     Do not remove either as redundant.")


if __name__ == "__main__":
    a = report("DARK", DARK)
    b = report("LIGHT", LIGHT)
    dichromacy("DARK", DARK)
    dichromacy("LIGHT", LIGHT)
    print("\nPASS" if a and b else "\nFAIL — lift the flagged tokens")
    raise SystemExit(0 if a and b else 1)
