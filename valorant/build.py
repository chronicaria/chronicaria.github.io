#!/usr/bin/env python3
"""Static-site generator for the four-player MWPA dashboard.

Run:  python3 build.py        (from anywhere; paths are self-relative)

Reads valorant/payload/ and writes, beside this file:

    index.html            the season tracker, the offense/defense figure, the match index
    m/<match_id>.html     one per match, with that match's payload inlined
    p/<short>.html        one per focal player
    robots.txt

THERE IS NO METHODS PAGE. It was deleted on 2026-08-06 because this site is public and the
model behind these numbers is not, and `main()` unlinks the stale file. Every caveat a page
depends on is now printed on that page, from `meta.cav` through `CAV_ON_PAGE`, in the
payload's own words — a paraphrase written here would be this file inventing a caveat.

Every page inlines its own JSON as `window.QUAD` in a script tag, so every page opens
off file:// with no fetch. On the front page `window.QUAD` is site.json, with its own
keys at the root plus `od`, both halves of every player-match; a player page adds that
player's block beside them. A match page carries only its own match payload, under `match`.
No page carries a second match.

Nothing here hardcodes a definition, a threshold or a count. Labels, formats, definitions,
the thin-cell floor and the caveat texts all come from `meta.dict`, `meta.gate` and
`meta.cav`. Four things this file does decide, and they are stated where they are made:
which fields go in which column, the percentile a fixed mark axis fills against
(`BAR_PERCENTILE`), the display precision of the two fields written at one decimal in the
payload and two everywhere on this site (`DECIMALS`), and how a person's name is written
(`SHORT_NAME`).

The presentation layer is split: this file emits semantic HTML and the data-driven
inline widths, `quad-site.css` styles it, and `quad-app.js` fills `[data-tracker]`,
`[data-offdef]` and `[data-match-figure]`. Both of those live beside this file and belong
to another build. The class vocabulary they can rely on:

    .ival .ival-span .ival-point .ival-zero      interval bar on a fixed axis
    .pos .neg .zero .under .none                 sign classes, on numbers and on marks
    .num                        any figure; monospace, right aligned
    .tbl .bt .scroll            data table, the player page's own table, and the scroller
    .fig .fig-wf .fig-track     a figure this file draws in SVG
    .rl-*                       the round ledger and its stacked bar
    .facts                      definition list
    .round-strip .round-index .round-tab .round-panel   round index; panels visible without JS
    .marker .tag .fallback .note .cav            inline markers and prose

The match figure is one continuous win probability curve inside `[data-match-figure]`,
and it is also the round selector: it announces a selection by dispatching `quad:round`
with `{round_number}` on `document`. The round panels below it are not its tabs and this
file does not draw it. Every panel is rendered open, with a plain index of anchors above
them, so the page is whole with no script at all; a small inline controller listens for
`quad:round`, sets `js-tabs` on `<html>` and switches `[data-round-panel]`.
"""
import html as html_mod
import json
import math
import re
import string
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"
TEMPLATES = HERE / "templates"

EM = "—"
MIDDOT = "·"
NDASH = "–"
# Direction on the lateral rail, as characters rather than as an icon: they are read aloud, they
# scale with the type, and they cost nothing to load.
ARROWS = {"prev": "←", "next": "→"}
# Up and down arrows came off. They were a fourth channel that said what the printed sign already
# says: every format `signed()` is ever handed carries a `+` flag — `signed()` refuses the key
# otherwise — so the sign CHARACTER is the non-colour channel, and the bar position is the second.
# The two that stay are the two that are not redundant: a middot is a measured zero and an em dash
# is nothing measured, and neither of those is a sign a format can print.
GLYPH = {"pos": "", "neg": "", "zero": MIDDOT, "none": EM}

# Magnitude bars fill against this percentile of the whole act's own distribution of the
# quantity being drawn, never against the largest row on screen.
BAR_PERCENTILE = 90
# The gate a single action has to clear before it gets a marker of its own on the
# win probability curve, and the axis that marker is sized against. See bar_scales.
MARKER_PERCENTILE = 99

# Fields the payload's own dict does not carry, because they only exist at round grain.
# `rwpa`, `rwpa_centered` and `team` came out with the columns that printed them. The payload
# still carries all three, so a label left here would name a column no page has.
FALLBACK_LABEL = {
    "duel": "Duel", "li": "Leverage index", "centering": "Centering",
    "loadout": "Loadout", "credits": "Credits", "kills": "Kills", "deaths": "Deaths",
    "assists": "Assists", "damage": "Damage", "round_number": "Round",
    "lobby_adjustment": "Lobby adjustment",
}
FALLBACK_FORMAT = {
    "li": ".2f", "loadout": ".0f",
    "credits": ".0f", "kills": ".0f", "deaths": ".0f", "assists": ".0f", "damage": ".0f",
    "round_number": ".0f",
}
# Every probability the payload names carries its own `.1%` format, so nothing here decides how a
# percentage is written. The four node kinds of the win probability curve are named the same way:
# `kind_<kind>` is a dictionary entry, and the standfirst above the figure is assembled from them.
KIND_KEY = "kind_%s"
KINDS = ["round_start", "clock", "action", "terminal"]

BREAKDOWN_ORDER = ["agent", "map", "side", "buy_class", "weapon"]
# The two payload caveats that used to print under `by side` and `by buy class` are off the
# player page and are printed nowhere now: what a breakdown needs beside it is the one number
# that explains its own width, and that number is in meta.gate. A caveat repeated above every
# figure is a caveat nobody finishes.
#
# WHICH CAVEATS A PAGE PRINTS, and after the methods page was deleted this map is the only
# thing standing between the payload's twenty-nine and none of them reaching a reader. Each of
# these travels with the figure it is about, in the payload's own words rather than a paraphrase
# — the abilities one because the round timeline prints a revive that no ledger credits, the
# curve one because the step at a round boundary is a real move nobody made, the noindex one
# because it is the disclosure, and the assets one because it is Riot's attribution.
CAV_ON_PAGE = {
    "opponents": "pseudonymous_opponents",
    "abilities": "no_abilities",
    "curve": "wp_curve_boundary_seam",
    "noindex": "noindex_is_not_access_control",
    "causal": "descriptive_not_causal",
    "assets": "riot_assets",
}

META = {}
DICT = {}
GATE = {}
CAV = {}
SCALE = {}
ASSETS = {}
ART = {}
RESULT = {}
NAME = {}
# Where each player stands on each row of the ledger, filled once in main(). See `rank_word`.
COMPONENT_RANK = {}

# HOW A PERSON IS WRITTEN, and there are two kinds of person here. A focal player is somebody
# the reader knows, so the Riot tag says nothing and comes off; one of the four is sixteen
# characters wide in a column four numbers wide and gets an initialism. An OPPONENT is a
# pseudonym whose tag IS the identity — six `Anonymous` rows in one match are told apart by
# nothing else — so those names pass through whole. The map is built in main() from the
# payload's own player list, which is why this file names no opponent and no rule about one.
SHORT_NAME = {"MartinLutherKing": "MLK"}


def display_name(name):
    return NAME.get(name, name)


# Two decimals on every quantity in match win probability points. `mwpa` already carried them,
# so a match printed +2.09% while the season it belongs to printed +6.4%: the same unit at two
# precisions, one of which cannot resolve two of these four players from each other.
DECIMALS = {"impact": "+.2%", "dp": "+.2%"}


def result_word(match_id, won):
    """How a match ended, read off the score and never off the flag.

    `match_result` already refuses the flag, and says why: this act has one 15-15 match and
    `won` is `false` on it, because a draw is not one of a boolean's two states. That refusal
    reached the index and stopped there. The match page's own fact list, the Result column of
    a player's match table and the ladder readout all still asked the flag, so Ascent 15-15
    printed the letter D on the front page and the word "lost" on the four pages that go into
    it. One lookup now, filled from the same `match_result` the index uses.

    The fallback is the flag, for a match_id the site index does not carry. Nothing built here
    is in that state — the assertion in main() is what keeps it that way — but a lookup that
    silently returned nothing would print an empty cell where a word belongs.
    """
    return RESULT.get(match_id, "won" if won else "lost")


def css_px(*tokens):
    """A length in pixels, read out of the stylesheet that declares it.

    Every `<img>` needs an explicit width and height so nothing reflows on load, and the
    stylesheet needs the same numbers so the box fits the line. Two literals for one measurement
    is how they drift, so there is one: the stylesheet declares it and this reads it. Three
    families ship at three shapes and all three sizes come from here — and so does `--sp-2`, the
    gap between a rank badge and its division, because the trajectory draws that pair in SVG and
    the lobby table draws it in HTML and they are one pair.
    """
    sheet = (HERE / "quad-site.css").read_text(encoding="utf-8")
    # AND THE SHEET IS CHECKED FOR THE ONE DEFECT NOTHING ELSE CATCHES. CSS comments do not
    # nest: a `/*` inside a comment body is ignored and the FIRST `*/` closes it, so a stray
    # authoring note containing one silently eats every rule between it and the next `*/`. That
    # is exactly how the waterfall's null rule stopped rendering on all four player pages while
    # every gate on this project still passed — contrast.py reads colour tokens and never parses
    # a rule, and a browser reports nothing. This file already opens the stylesheet to read a
    # length out of it, so it is the cheapest place to refuse one.
    at = 0
    while True:
        opened = sheet.find("/*", at)
        if opened < 0:
            break
        closed = sheet.find("*/", opened + 2)
        if closed < 0:
            raise AssertionError("quad-site.css has an unterminated comment at line %d"
                                 % (sheet.count("\n", 0, opened) + 1))
        if "/*" in sheet[opened + 2:closed]:
            raise AssertionError(
                "quad-site.css nests a comment at line %d: CSS comments do not nest, so every "
                "rule from there to the next */ is dead"
                % (sheet.count("\n", 0, opened) + 1))
        at = closed + 2
    out = {}
    for token in tokens:
        found = re.search(re.escape(token) + r":\s*(\d+)px", sheet)
        if not found:
            raise AssertionError("quad-site.css declares no %s; that length has no value" % token)
        out[token] = int(found.group(1))
    return out


def art_box(family, name, box):
    """A file's rendered width and height, contain-fitted into `box` from its own intrinsic size.

    `meta.assets.<family>.px` carries what the file really is; `box` is what the stylesheet says
    the slot is. Neither number is typed twice and the view never guesses a shape, which is what
    lets a family whose files run 1.3:1 to 5.7:1 share one slot without distorting any of them.
    """
    intrinsic = ((ASSETS.get(family) or {}).get("px") or {}).get(name)
    if not intrinsic:
        return None
    width, height = intrinsic
    scale = min(box[0] / float(width), box[1] / float(height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def art_file(family, name):
    """The path for one name in one family, or None. The only way the view resolves an image.

    A name that is not in the map renders the word alone. There is no string surgery here and
    therefore no way for this build to emit a broken image.
    """
    return ((ASSETS.get(family) or {}).get("files") or {}).get(name)


# ---------------------------------------------------------------- payload and formats

def load_payload():
    site = json.loads((PAYLOAD / "site.json").read_text(encoding="utf-8"))
    players = {}
    for entry in site["players"]:
        path = PAYLOAD / "player" / (entry["short"] + ".json")
        players[entry["short"]] = json.loads(path.read_text(encoding="utf-8"))
    matches = {}
    for entry in site["matches"]:
        path = PAYLOAD / "match" / (entry["match_id"] + ".json")
        matches[entry["match_id"]] = json.loads(path.read_text(encoding="utf-8"))
    return site, players, matches


def percentile(values, pct):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of an empty sample")
    k = (len(ordered) - 1) * pct / 100.0
    low, high = int(math.floor(k)), int(math.ceil(k))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def component_impact(cell, head):
    """One credit type in the headline's own unit: its share of a match win, per match played.

    THE ONE CUT OF THE LEDGER THAT CONVERTS, and the reason is a denominator it already shares.
    A component's rounds ARE the headline's rounds — trzzcko's kill credit is +3.092 over the
    same 163 that give him +1.8968 per 100 — so the divisor is the headline's own match count
    and the six converted points sum to `impact` to within 1e-9 on all four players. The
    endpoints are per 100 rounds, so they take the same positive constant `impact_lo` takes:
    rounds / (100 x matches), 0.2038 for trzzcko.

    A breakdown or a synergy cell cannot do this and is left in the estimator's unit. Its match
    count exists but is not its exposure: `Other` weapons are 1.2 rounds of a twenty-one-round
    match, and a per-match number over 1.2 rounds does not mean what +6.4% per match means.
    """
    k = head["rounds"] / (100.0 * head["matches"])
    return cell["total"] / head["matches"], cell["lo"] * k, cell["hi"] * k


def bar_scales(site, players, matches):
    """One fixed axis per quantity, from the act's own distribution.

    Two percentiles, and the reason they are two. A magnitude bar fills against
    p90, which guarantees by construction that the top tenth of bars clip — that
    is acceptable for a bar, because a clipped bar is flagged at both ends and
    the number is printed beside it. A MARKER GATE cannot work that way: a mark
    that clamps is a mark that lies about its size, and there is no number
    beside it. So the marker axis is p99, which is also what makes a match
    figure legible — the top hundredth of moves get a disc and the other
    ninety-nine hundredths are the vertical in the line, which was already the
    mark.
    """
    round_mwpa, match_mwpa, rate, component, action_dp = [], [], [], [], []
    for match in matches.values():
        for row in match["players"]:
            match_mwpa.append(abs(row["mwpa"]))
        for rnd in match["rounds"]:
            for row in rnd["players"]:
                round_mwpa.append(abs(row["mwpa"]))
        # The curve's own axis. A marker on the win probability figure is sized by how far the
        # line moved, and that has to mean the same thing on a 4-point kill in match 3 as in
        # match 60 -- so it fills against the act's distribution of action moves, never against
        # the biggest move in the match on screen.
        for node in match["wp_series"]:
            if node["kind"] == "action":
                action_dp.append(abs(node["dp"]))
    for row in site["players"]:
        rate.extend([abs(row["rate"]), abs(row["lo"]), abs(row["hi"])])
    for player in players.values():
        for cells in player["breakdowns"].values():
            for cell in cells:
                rate.extend([abs(cell["rate"]), abs(cell["lo"]), abs(cell["hi"])])
        for cell in player["synergy"]:
            if cell["rate"] is not None:
                rate.extend([abs(cell["rate"]), abs(cell["lo"]), abs(cell["hi"])])
        # The component waterfall is drawn per match, so its axis is in per-match units too. The
        # p90 of these seventy-two rate endpoints is 2.056, so a rail axis derived from the rates
        # would be 2.056 wide against rows printing +38.6%.
        for cell in player["components"].values():
            point, lo, hi = component_impact(cell, player["headline"])
            component.extend([abs(point), abs(lo), abs(hi)])
    # THE HEADLINE AXIS, and it is a MAXIMUM rather than a percentile. Twelve numbers — four
    # players by three endpoints — are the whole population of this quantity, and the season
    # tracker puts every one of them on screen at once. p90 of twelve numbers would clip two of
    # the four intervals, including the one the whole argument is about, and a clipped interval
    # on the figure that exists to say the intervals are wide is the one mark on this site that
    # cannot be allowed to stop at its own axis.
    impact = []
    for row in site["players"]:
        impact.extend([abs(row["impact"]), abs(row["impact_lo"]), abs(row["impact_hi"])])
    return {
        "percentile": BAR_PERCENTILE,
        "marker_percentile": MARKER_PERCENTILE,
        "round_mwpa": percentile(round_mwpa, BAR_PERCENTILE),
        "match_mwpa": percentile(match_mwpa, BAR_PERCENTILE),
        "rate": percentile(rate, BAR_PERCENTILE),
        "impact": max(impact),
        "component_impact": percentile(component, BAR_PERCENTILE),
        "action_dp": percentile(action_dp, BAR_PERCENTILE),
        "marker_gate": percentile(action_dp, MARKER_PERCENTILE),
    }


# THE AXES ARE PINNED, and this is house rule 3 finally meaning what it says. The rule is that a
# magnitude bar fills against a FIXED corpus percentile carried in the payload, never against the
# biggest row on screen — so that a mark of a given size means the same number on every page. But
# the percentile was recomputed from the whole corpus on every build, which made "fixed" mean
# fixed-within-one-build: four new matches moved every axis by a percent or two, every bar on
# every page moved with it, and all 78 files were rewritten from end to end for a corpus change
# that had nothing to do with 74 of them. Pinned, an axis moves when somebody decides it moves.
#
# The one axis allowed to move on its own is `impact`, and only outward. It is a maximum rather
# than a percentile precisely because a clipped interval on the figure whose whole argument is
# that the intervals are wide is the one bar this site cannot draw — so if a new interval runs
# past the pin, the pin widens to hold it. Nothing ever narrows without `--rescale`.
SCALE_PIN = PAYLOAD / "scale.json"
WIDEN_ONLY = ("impact",)


def pinned_scales(site, players, matches, rescale=False):
    live = bar_scales(site, players, matches)
    if rescale or not SCALE_PIN.exists():
        SCALE_PIN.write_text(json.dumps(live, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return live, {}, True
    pinned = dict(json.loads(SCALE_PIN.read_text(encoding="utf-8")))
    missing = sorted(k for k in live if k not in pinned)
    if missing:
        raise AssertionError(
            "%s carries no axis for %s. A new quantity needs a deliberate pin: rerun with "
            "--rescale." % (SCALE_PIN.name, ", ".join(missing)))
    widened = {}
    for key in WIDEN_ONLY:
        if live[key] > pinned[key]:
            widened[key] = (pinned[key], live[key])
            pinned[key] = live[key]
    if widened:
        SCALE_PIN.write_text(json.dumps(pinned, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    drift = dict((k, (pinned[k], live[k])) for k in sorted(live)
                 if k not in ("percentile", "marker_percentile")
                 and pinned[k] and abs(live[k] - pinned[k]) / abs(pinned[k]) > 0.01)
    return pinned, drift, bool(widened)


def esc(value):
    return html_mod.escape(str(value), quote=True)


def prose(text):
    """Payload text as body copy: escaped, with its backtick spans set as code."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(text))


def inline_json(obj):
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    for raw, safe in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                      ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        text = text.replace(raw, safe)
    return text


def fmt(value, spec):
    if value is None:
        return EM
    if spec == "bool":
        return "yes" if value else "no"
    if spec in ("text", "date"):
        return str(value)
    if spec == ".0f":
        return format(value, ",.0f")  # dict says .0f; counts read better grouped
    return format(value, spec)


def spec_for(key):
    entry = DICT.get(key)
    return entry["format"] if entry else FALLBACK_FORMAT[key]


def label_for(key):
    entry = DICT.get(key)
    return entry["label"] if entry else FALLBACK_LABEL[key]


def num(key, value):
    return fmt(value, spec_for(key))


def magnitude(key, value):
    """The same format without the sign flag, for a distance rather than a position."""
    return fmt(value, spec_for(key).replace("+", ""))


def count(value):
    return fmt(value, ".0f")


def confidence():
    """The interval's coverage, written the way the payload says probabilities are written."""
    return num("confidence", META["confidence"])


WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def spell(n):
    """A small count inside a sentence reads as a word; anything larger keeps its digits."""
    return WORDS[n] if 0 <= n < len(WORDS) else count(n)


def singular(word):
    """One of whatever the payload's plural label names.

    The unit under a card chip is `meta.dict`'s own label, so the singular has to be derived
    from it rather than typed beside it — a payload that renames the field has to rename both
    forms or neither. Two rules cover every label this site has: a plural in `-es` after a
    sibilant drops both letters (matches, not matche), any other `-s` drops one (rounds), and a
    word that was never a plural is left alone.
    """
    if word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def and_list(items):
    """A, B and C. Three of these four queue together, and `" and ".join` wrote "A and B and C"."""
    items = list(items)
    if len(items) < 3:
        return " and ".join(items)
    return "%s and %s" % (", ".join(items[:-1]), items[-1])


def cav(where):
    return CAV[CAV_ON_PAGE[where]]


def definition_of(key):
    entry = DICT.get(key)
    return entry["definition"] if entry else None


def humanize(token):
    return str(token).replace("_", " ")


def node_type_label(token):
    """What an action node IS, for a column that also prints structural kinds.

    ONE COLUMN, ONE CASE. The round timeline puts `kind_<kind>` labels and action types in the
    same cell, and the types went through `humanize` alone: "Round start", "Clock", "Terminal"
    beside "kill", "plant", "revive" — 26 tables a page, 68 pages, reading as two columns that
    happen to share a border. `plant` and `defuse` are dictionary fields and their labels were
    sitting there unread; `kill`, `revive`, `detonate` and `timer_expired` are not fields, have
    no entry, and get the payload's own token with a capital rather than an invented label.
    """
    entry = DICT.get(token)
    if entry:
        return entry["label"]
    text = humanize(token)
    return text[:1].upper() + text[1:]


def as_datetime(iso):
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(iso, pattern)
        except ValueError:
            continue
    raise ValueError("unparseable timestamp: %s" % iso)


def as_long_date(iso):
    """`August 6`. Every match in this act is 2026, so the year is a column of one value."""
    when = as_datetime(iso)
    return "%s %d" % (when.strftime("%B"), when.day)


# ------------------------------------------------------------------ sign and magnitude

def sign_of(value):
    if value is None:
        return "none"
    if value > 0:
        return "pos"
    if value < 0:
        return "neg"
    return "zero"


def smallest_printable(key):
    """The smallest magnitude this field's own format can write.

    Derived from `meta.dict[key].format` and nothing else, so the threshold below
    which a number stops claiming a direction moves when the format does.
    """
    m = re.search(r"\.(\d+)([f%])$", spec_for(key))
    if not m:
        return None
    decimals = int(m.group(1))
    # A `.1%` format multiplies by a hundred before it prints, so the smallest
    # value it can write is two orders further down than the decimal count says.
    return 10.0 ** (-(decimals + (2 if m.group(2) == "%" else 0)))


def signed_text(key, value):
    """The three states of a signed number, as `(text, class)`, before a medium sets them.

    HTML gets a span and SVG gets a `<text>`, and neither of them may decide this on its own:
    the em dash, the middot and the under-precision reading are one rule, and a second copy of
    it in the figure code is how the figure starts writing `+0.00%` for a number the table
    refuses to. `signed()` is this plus a span; the waterfall is this plus a `<text>`.
    """
    if "+" not in spec_for(key):
        raise AssertionError(
            "signed(%s) on format %s, which prints no sign: the sign character is the "
            "non-colour channel and this field has none" % (key, spec_for(key)))
    kind = sign_of(value)
    if kind == "none":
        return EM, "none"
    if kind == "zero":
        return MIDDOT, "zero"
    step = smallest_printable(key)
    if step is not None and abs(value) < step:
        return "<%s" % magnitude(key, step), "under"
    return num(key, value), kind


def signed(key, value, absent_reason="not measured"):
    """A number carrying its sign three ways: the printed sign, a colour class, and — where
    a bar is drawn beside it — which side of the null that bar hangs off.

    HOUSE RULE 2, AND WHERE ITS THREE CHANNELS NOW ARE. The direction arrows are gone; the
    `+` or `-` the format itself prints is the channel that does not depend on colour, so
    `signed_text` refuses any key whose format has no sign flag rather than trusting that
    every one of them has one. Colour is never alone and cannot become alone by a payload edit.

    Three states, and they are three different facts. An absent value is an em
    dash with its reason. An exact zero is a middot: measured, and neither
    direction. A value that is measured but smaller than its own format can
    write prints as less-than the smallest printable number, with no sign and
    no direction colour — printing `+0.00%` claims a direction the number
    cannot support, and printing an em dash would claim the value is missing
    when it is not. `meta.cav.measured_zero_at_display_precision` is the reason.
    """
    text, kind = signed_text(key, value)
    if kind == "none":
        return '<span class="num none" title="%s">%s</span>' % (esc(absent_reason), esc(text))
    if kind == "zero":
        return '<span class="num zero" title="an exact zero, measured">%s</span>' % esc(text)
    if kind == "under":
        return ('<span class="num under" title="measured, and smaller than the smallest number '
                'this field is written to">%s</span>') % esc(text)
    # No empty element where the arrow used to be: an empty `.glyph` span still carries the
    # stylesheet's own margin and would print a gap between the sign and the number.
    glyph = ('<span class="glyph" aria-hidden="true">%s</span>' % GLYPH[kind]) if GLYPH[kind] else ""
    return '<span class="num %s">%s%s</span>' % (kind, glyph, esc(text))


# NO MAGNITUDE BAR REACHES A TABLE ANY MORE, so `mag_bar` and `spoken` — the accessible name
# it needed — are gone with it. The number is the number: a bar beside it was a second
# rendering of a fact the cell already prints, at a precision the cell already has. What is
# still drawn is `interval_bar`, which is not a magnitude: it is an ESTIMATE, and its width
# is a quantity that appears nowhere else in the row.


def interval_bar(point, lo, hi, scale, aria):
    """Point estimate and its interval on the fixed rate axis, zero at the centre."""
    if lo is None or hi is None:
        return '<span class="ival none" role="img" aria-label="%s"></span>' % esc(aria)

    def x(value):
        return min(max((value + scale) / (2.0 * scale), 0.0), 1.0) * 100.0

    left, right = x(lo), x(hi)
    zero_width = ' data-zero-width="1"' if hi == lo else ""
    clipped = clip_flag(lo, hi, scale)
    covers = "covers" if lo <= 0 <= hi else "excludes"
    return (
        '<span class="ival" role="img" aria-label="%s" data-zero="%s"%s%s>'
        '<span class="ival-zero" aria-hidden="true"></span>'
        '<span class="ival-span" style="left:%.2f%%;width:%.2f%%"></span>'
        '<span class="ival-point %s" style="left:%.2f%%"></span></span>'
    ) % (esc(aria), covers, zero_width, clipped, left, max(right - left, 0.6),
         sign_of(point), x(point))


def interval_bound(value, key):
    """One endpoint, at the precision its field is written to, never claiming a zero it lacks.

    HOUSE RULE 1 AT THE ENDS OF AN INTERVAL, where it was missing. `signed()` has always
    refused to print `+0.0%` for a measured value smaller than its own format — but an interval
    printed its bounds through `num()` and had no such refusal, and the components rail brought
    the collision: a defuse interval of +0.00044 to +0.00695 per match wrote itself as
    "+0.0% to +0.7% excludes the null", a low end that reads AS the null on the one row whose
    verdict says it is not. Under the smallest printable magnitude the bound says which side of
    the null it is on and that it is smaller than this field is written to. In words rather
    than a symbol, because it is read aloud. `cav.measured_zero_at_display_precision`.
    """
    step = smallest_printable(key)
    if step is not None and value != 0 and abs(value) < step:
        return "%s%s" % ("under +" if value > 0 else "over -", magnitude(key, step))
    return num(key, value)


def interval_text(lo, hi, key=None):
    """The two endpoints, in the format of the quantity they bound.

    `key` because the headline endpoints are now read in two units: `lo` and `hi` are the
    estimator's own per-100-rounds format and the same interval printed as impact per match
    has to be written the way impact is written."""
    if lo is None or hi is None:
        return EM
    return "%s to %s" % (interval_bound(lo, key or "lo"), interval_bound(hi, key or "hi"))


def null_verdict(covers):
    """What an interval does to the null, as a finished phrase.

    Three rails used to print the bare verb — "-0.022 to +1.750 covers" — which
    reads as a sentence the renderer truncated. The object is named, and it is
    named the same thing the axis labels it: the null."""
    return "%s the null" % ("covers" if covers else "excludes")


# ---------------------------------------------------------------------------- the rail
#
# THE NULL RULE. One continuous line of full-strength ink at the value that means
# NO CLAIM, heavier than any datum and heavier than the data, unbroken as a single
# DOM element from the axis through every row of a block. It is a child of the
# TRACK column, which is what keeps it off the label and the number at every
# viewport and is why the rail never reflows into a stack.
#
# Three marks and only three: a capped dimension line in a hue is an ESTIMATE, a
# solid bar from the null is an EXACT MAGNITUDE, a line in ink is an EXACT PATH.
# The value the rule sits at comes from `meta.gate`, never from this file.


def axis_x(value, scale):
    """A value's position on a symmetric axis with the null at its centre."""
    return min(max((value + scale) / (2.0 * scale), 0.0), 1.0) * 100.0


def clip_flag(lo, hi, scale):
    """Which END ran past the fixed axis. Both used to be flagged because the
    flag did not say which; it does now, and a bar that stopped at the axis
    still cannot be read as one that stopped on its own."""
    ends = []
    if lo is not None and lo < -scale:
        ends.append("lo")
    if hi is not None and hi > scale:
        ends.append("hi")
    return ' data-clipped="%s"' % " ".join(ends) if ends else ""


# The marker column is gone. It carried two flags — "thin" and "one match" —
# in a column of its own beside a rate it never explained. Both are now said by
# the EXPOSURE column, which prints the rounds behind a cell as a share of the
# rounds an interval this wide needs, and which answers the reader's actual
# second question: not "is this cell flagged" but "why is my bar so wide".


# ------------------------------------------------------------------------------ tables

def agent_cell(name, root):
    """The agent's name, and — where the artwork resolves — an 18px portrait beside it.

    `alt=""` and `aria-hidden` are the correct alternative text here, not laziness: the word is
    in the same cell and visible, so `alt="Sova"` makes a screen reader say Sova twice. Explicit
    width and height because the null rule is a full-height element positioned against row
    geometry and there is no layout-shift budget; `loading="lazy"` because this table is 1,300px
    down a match page. A name with no file in `meta.assets` renders the word alone — the view
    does no string surgery on a file name, so there is no way for it to emit a broken image.
    """
    file_name = art_file("agent", name)
    chip = ""
    if file_name:
        chip = ('<span class="agent-chip" aria-hidden="true">'
                '<img src="%s%s" width="%d" height="%d" alt="" decoding="async" '
                'loading="lazy"></span>') % (root, esc(file_name),
                                             ART["--icon-art"], ART["--icon-art"])
    return '<span class="agent">%s<span>%s</span></span>' % (chip, esc(name))


def weapon_cell(name, root):
    """The weapon's name, and — where the artwork resolves — its silhouette on a plate beside it.

    Same contract as `agent_cell` and same alternative text for the same reason: the word is in
    the cell, so `alt="Vandal"` makes a screen reader say Vandal twice. What differs is the shape.
    Riot's weapon art is 96 wide at 17 to 73 tall, so the element's width and height are computed
    per file from `meta.assets.weapon.px` rather than assumed square — nothing is distorted and
    nothing reflows. `Other` is a grouping and not a weapon, so it is not in the map and renders
    the word alone, which is the same thing that happens to any name with no file.
    """
    file_name = art_file("weapon", name)
    box = art_box("weapon", name, (ART["--weapon-art-w"], ART["--icon-art"]))
    if file_name and box:
        chip = ('<span class="weapon-chip" aria-hidden="true">'
                '<img src="%s%s" width="%d" height="%d" alt="" decoding="async" '
                'loading="lazy"></span>') % (root, esc(file_name), box[0], box[1])
    else:
        # AN EMPTY SPACER, NOT AN EMPTY SLOT, and the difference is the whole point. `Other` is a
        # grouping and not a weapon: there is no picture missing, so there is nothing to draw a
        # box around. Compare the rank chip, where the empty slot IS the fact. What the spacer
        # buys is the left edge of the word column — a row that skipped it would sit 52px left of
        # every other word, and a ragged left edge is the opposite of the only reason to have an
        # icon column. It is a `weapon-chip`, so the identity control collapses it with the rest.
        chip = '<span class="weapon-chip is-none" aria-hidden="true"></span>'
    return '<span class="weapon">%s<span>%s</span></span>' % (chip, esc(name))


def rank_cell(step, root, badge=True, tag="span"):
    """A division and its badge, or the measured fact that no rank had been issued yet.

    THE BADGE NEVER TRAVELS WITHOUT THE WORD. Riot's tier art is hue-coded and its gold lands
    within OKLab ΔE 3.5 of `--martin`, and this site's rule is that hue is a person — so the
    collision is real and it is answered structurally: this function is the only way a badge
    reaches a page, and it always emits the division word beside it. The word encodes; the badge
    is recognition. `aria-hidden` is right for the same reason it is right on a portrait.

    Three renderings of the empty state are wrong and all three are still refused. `0` is a number
    it does not have. The em dash on this site means NOT MEASURED and this is measured. The
    platform's own name for it is the name of a QUEUE. What ships instead is the word `placement`
    beside an EMPTY slot in a dashed hairline: the ladder position exists and nothing has been
    issued into it. `cav.unrated_is_not_a_division` carries the argument.

    `badge=False` is not a fallback, it is a decision made twice on measurement. The per-match
    table on a player page runs to sixty rows of which forty-five are the same division, and the
    round ledger is wider still; a column that is three-quarters one glyph is texture, which is
    the objection this round is answering rather than ignoring. The badge ships where the badge IS
    the subject — the trajectory's own axis, and the lobby range in a match masthead — and the
    word ships everywhere, including here.
    """
    art = ART["--icon-art"]
    if step.get("tier"):
        file_name = art_file("rank", step["tier"]) if badge else None
        chip = ""
        if badge:
            chip = ('<span class="rank-chip is-empty" aria-hidden="true"></span>' if not file_name
                    else '<span class="rank-chip" aria-hidden="true">'
                         '<img src="%s%s" width="%d" height="%d" alt="" decoding="async" '
                         'loading="lazy"></span>' % (root, esc(file_name), art, art))
        return ('<%s class="rank">%s<span class="division">%s</span></%s>'
                % (tag, chip, esc(step["tier"]), tag))
    empty = '<span class="rank-chip is-empty" aria-hidden="true"></span>' if badge else ""
    return ('<%s class="rank" title="%s">%s<span class="division is-placement">%s</span></%s>'
            % (tag, esc(CAV["unrated_is_not_a_division"]), empty, esc(step["state"]), tag))


def null_head():
    """The header of a signed column: a bold zero sitting exactly on the painted
    rule that runs the full height of it. The value is `meta.gate.null_rate`."""
    return '<span title="%s">%s</span>' % (esc(definition_of("null") or ""),
                                           esc(count(GATE["null_rate"])))


def table(headers, rows, cls="tbl", caption=None, groups=None, foot=None):
    """headers: (label_html, css_class). rows: lists of cell html, same length.

    A header's class travels down its own column, which is what lets `z` — the
    painted rule at the null — be one unbroken vertical through every cell of a
    signed column rather than a tick drawn once per row.

    `groups` is [(label, span), …] and adds a column-group header. The grouping is carried by a
    solid gutter CELL rather than a border, because a border belongs to the column it is drawn
    on and slides out of view with it when the table scrolls sideways; a gutter column is part of
    the table's own geometry and survives the scroller. On an eleven-column table where two
    columns are the finding and five are the box score, that is ten pixels for a real answer to
    "which of these is the measurement".

    `groups` spans the COLUMN headers. A row carrying a `tbody` key is the other axis and is not
    a row at all: it closes the open `<tbody>` and opens the next one, with a full-width label
    row at the top of it. That is what replaced the Team column on the two match-page tables —
    a band that says its own name, so the fact is never in the wash alone.

    `foot` is a finished `<tr>`'s worth of cells, written by the caller because a footer that
    sums a column has to say which columns it spans and this cannot guess. Only tables without
    `groups` may use it: it would have to place its own gutters otherwise.
    """
    classes = [c for _, c in headers]
    gutters = set()
    if groups:
        if sum(span for _, span in groups) != len(headers):
            raise AssertionError("column groups cover %d of %d columns"
                                 % (sum(span for _, span in groups), len(headers)))
        at = 0
        for _, span in groups[:-1]:
            at += span
            gutters.add(at)

    def cells_html(items, tag, per_cell):
        out = []
        for i, item in enumerate(items):
            if i in gutters:
                out.append('<%s class="gutter" aria-hidden="true"></%s>' % (tag, tag))
            out.append(per_cell(i, item))
        return "".join(out)

    head = cells_html(headers, "th", lambda i, h: '<th scope="col"%s>%s</th>' % (
        ' class="%s"' % h[1] if h[1] else "", h[0]))
    group_row = ""
    if groups:
        spans = []
        for index, (label, span) in enumerate(groups):
            if index:
                spans.append('<th class="gutter" aria-hidden="true"></th>')
            spans.append('<th scope="colgroup" colspan="%d">%s</th>' % (span, esc(label)))
        group_row = '<tr class="group-head">%s</tr>' % "".join(spans)

    body, banded = [], False
    for row in rows:
        if isinstance(row, dict) and "tbody" in row:
            if banded:
                body.append("</tbody>")
            band = row["tbody"]
            body.append('<tbody%s><tr class="team-head"><th colspan="%d">%s</th></tr>'
                        % (band["attrs"], len(headers) + len(gutters), band["head"]))
            banded = True
            continue
        items = row["cells"] if isinstance(row, dict) else row
        attrs = row.get("attrs", "") if isinstance(row, dict) else ""
        body.append("<tr%s>%s</tr>" % (attrs, cells_html(
            items, "td",
            lambda i, c: "<td%s>%s</td>" % (
                ' class="%s"' % classes[i] if i < len(classes) and classes[i] else "", c))))
    inner = "".join(body) + "</tbody>" if banded else "<tbody>%s</tbody>" % "".join(body)
    if foot:
        if groups:
            raise AssertionError("a footer cannot place the gutter cells a column group needs")
        inner += "<tfoot><tr>%s</tr></tfoot>" % foot
    cap = "<caption>%s</caption>" % esc(caption) if caption else ""
    return '<table class="%s">%s<thead>%s<tr>%s</tr></thead>%s</table>' % (
        cls, cap, group_row, head, inner)


def facts(pairs):
    return "".join("<div><dt>%s</dt><dd>%s</dd></div>" % (esc(term), value)
                   for term, value in pairs)


# ------------------------------------------------------------------------- page shell

def nav_html(site, root, active):
    links = [("index.html", "Overview", "index")]
    for entry in site["players"]:
        links.append(("p/%s.html" % entry["short"], display_name(entry["name"]), entry["short"]))
    out = []
    for href, label, key in links:
        current = ' aria-current="page"' if key == active else ""
        out.append('    <a href="%s%s"%s>%s</a>' % (root, href, current, esc(label)))
    return "\n".join(out)


def footer_html():
    # THE DISCLOSURE, IN THE PAYLOAD'S OWN WORDS. It used to be a link to the methods page,
    # and when that page went the clause became a paraphrase written here — which is the one
    # thing this file is not allowed to do with a caveat. Three of them ship on every page now:
    # what "not indexed" does and does not mean, that the credits are descriptive and not
    # causal, and whose artwork this is.
    return (
        '  <p class="scope">Act %s. %s matches, %s rounds, %s round-players, %s distinct '
        'players. Release %s, built %s.</p>\n'
        '  <p class="disclosure">%s</p>\n'
        '  <p class="disclosure">%s %s</p>'
    ) % (esc(META["act"]), count(META["matches"]), count(META["rounds"]),
         count(META["round_players"]), count(META["players"]), esc(META["release"]),
         esc(META["generated_at"]), prose(cav("noindex")),
         prose(cav("causal")), prose(cav("assets")))


def icons_toggle_html(has_icons):
    """The identity control, rendered only where there is an identity to switch off.

    It is the whole defence of the imagery on this site: flip it and not one fact leaves the
    page, because no picture carries a measurement. Rendering it on a page with no imagery would
    make it a decoration about decoration.

    It covers all three families and its word says so — "icons", not "agent icons", now that a
    match page carries portraits and division badges and a player page carries badges and weapon
    silhouettes. A control whose label names one of the three would be a control a reader does not
    expect to reach the others.
    """
    if not has_icons:
        return ""
    return ('  <button class="icons-toggle" type="button" data-icons-toggle '
            'aria-pressed="true">%s</button>\n' % esc("icons on"))


# `meta` and `scale` are the same object on every page, and every page used to carry its own
# copy: 25 KB of identical JSON, 78 times. That is not a page-weight problem — it is a HISTORY
# problem. Nothing in either block belongs to one match, so a refresh that adds a match to the
# corpus rewrote the block inside all 78 files, and a version control system stores a changed
# file whole. Hoisted into one script the pages share, they are written once and change once.
# `Object.assign` in the shell puts them back at the root of `window.QUAD`, so the figures still
# read `QUAD.meta` and `QUAD.scale` and no view code knows this happened.
SHARED_KEYS = ("meta", "scale")


def shared_js(site):
    """The corpus-wide half of `window.QUAD`, written once for every page to load."""
    return "window.QUAD_SHARED=%s;\n" % inline_json(
        {"meta": dict((k, v) for k, v in site["meta"].items() if k != "cav"), "scale": SCALE})


def render_page(out_path, site, title, description, page, root, active, body, data,
                has_icons=False):
    shell = string.Template((TEMPLATES / "page.html").read_text(encoding="utf-8"))
    own = dict((k, v) for k, v in data.items() if k not in SHARED_KEYS)
    html = shell.substitute(
        title=esc(title), description=esc(description), page=esc(page), root=root,
        nav=nav_html(site, root, active), body=body, footer=footer_html(),
        icons_toggle=icons_toggle_html(has_icons), data=inline_json(own))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return len(html.encode("utf-8"))


def body_from(name, **fields):
    template = string.Template((TEMPLATES / name).read_text(encoding="utf-8"))
    return template.substitute(**fields)


def page_data(page, site, **extra):
    """window.QUAD. site.json's own keys sit at the root so the figures find `meta`
    beside `tracker` rather than nested a level deeper."""
    data = dict(site)
    data["page"] = page
    data["scale"] = SCALE
    data.update(extra)
    return data


# -------------------------------------------------------------------------- front page

def finding_line(site):
    """The page description, in one sentence. Ranked by impact per match, like everything else."""
    players = site["players"]
    covering = [p for p in players if p["covers_zero"]]
    if len(covering) == len(players):
        tail = "and every one of the %s intervals covers zero" % spell(len(players))
    elif covering:
        tail = "and %s of the %s intervals cover zero" % (
            spell(len(covering)), spell(len(players)))
    else:
        tail = "and no interval covers zero"
    # "Ranked by" was true of a rail that no longer exists. The four are still ORDERED by
    # impact — in the tracker's legend and in the cross-tab's columns — but no page prints a
    # rank number, and a description that promised one would be a promise the page does not keep.
    return "%s matches, %s players ordered by %s %s %s." % (
        count(META["matches"]), spell(len(players)), label_for("impact").lower(), EM, tail)


def mwpa_line():
    """WHAT THE SITE MEASURES, in two sentences, and it is the only prose on the front page.

    The three paragraphs that used to open this page — the finding, the width of the widest
    interval, and the order's own instability — are gone at the owner's instruction: the
    figure under this line already ends every one of the four series on its headline number,
    and the cross-tab below carries every number the figure is built from. What no picture on
    the page could supply is the unit, so that is what survives.
    """
    return ("%s is match win probability added: every kill, death, plant, defuse and second "
            "alive is priced by how much it moved this team's chance of winning the MATCH, "
            "not the round, each is measured against what everyone else in that round was "
            "worth, and a player's are summed. %s divides that by the matches they played, so "
            "%s is six extra wins in a hundred."
            % (label_for("mwpa"), label_for("impact"), num("impact", 0.06)))


def match_result(entry):
    """W, L or D and the scoreline, as one cell: (css class, text).

    THE SCORE DECIDES, NOT THE FLAG. This act contains one 15–15 match and `won` is `false`
    on it, because the payload's flag is a boolean and a draw is not one of its two states.
    A drawn match printed as "lost" is a wrong fact on the page, so the letter is read off
    the two numbers and the flag is not consulted at all.
    """
    home, away = entry["score"]
    kind = "won" if home > away else "lost" if home < away else "drew"
    letter = {"won": "W", "lost": "L", "drew": "D"}[kind]
    return kind, "%s %s%s%s" % (letter, count(home), NDASH, count(away))


def merged_index_table(site, root, tracker_by_match):
    """A CROSS-TAB. One row per match, one column per player, newest first.

    The focal players used to be one text cell of hued chips, which is a list and not a column:
    to answer "which matches did TheMarias play" a reader had to read seventy cells of running
    prose, and to compare two players in one match they had to compare two substrings of the
    same paragraph. Four columns answer both by scanning, and they answer a third question the
    chip list could not put on the page at all — who was present — because a player who did not
    play a match leaves their cell EMPTY.

    Empty means empty. Not a zero, which is a measurement this match does not contain, and not
    an em dash, which on this site means NOT MEASURED and would be a claim about a match this
    person was not in. The cell has nothing in it and the row is one player narrower. House
    rule 2, at the one place on the site where the absence is the fact.

    Nothing here reads the tracker's own order: `data-date` is on every row and quad-app.js
    sorts on it, so the default order and the sorted order come from the same field. Every
    player column is its own sort key, so the cross-tab is also four orderings of the act.
    """
    players = site["players"]

    def sort_head(key, label, cls):
        return ('<button class="sort" type="button" data-sort="%s">%s'
                '<span class="sort-mark"></span></button>' % (esc(key), esc(label)), cls)

    # THE DATE IS ITS OWN COLUMN. It used to ride inside the match link as `Haven · 2026-08-06`,
    # which made a scan for "when" a scan through a map name, and put an ISO string on a page
    # whose every match is the same year. Three structural columns now: what happened, where,
    # and when. The link stays on the map, because that cell is the one that names the match.
    headers = [sort_head("margin", label_for("won"), "l"),
               sort_head("map", label_for("map"), "l"),
               sort_head("date", label_for("started_at"), "l")]
    headers += [sort_head(entry["short"], display_name(entry["name"]), "num p-%s"
                          % entry["short"]) for entry in players]
    rows = []
    for entry in sorted(site["matches"], key=lambda e: e["started_at"], reverse=True):
        kind, score_text = match_result(entry)
        shorts = [s for s in entry["focal"] if (s, entry["match_id"]) in tracker_by_match]
        cells = [
            '<span class="%s">%s</span>' % (kind, esc(score_text)),
            '<a href="%sm/%s.html">%s</a>' % (
                root, esc(entry["match_id"]), esc(entry["map"])),
            '<span class="idx-when">%s</span>' % esc(as_long_date(entry["started_at"])),
        ]
        attrs = [' data-player="%s"' % esc(" ".join(shorts)),
                 ' data-date="%s"' % esc(entry["started_at"]),
                 ' data-map="%s"' % esc(entry["map"]),
                 ' data-margin="%d"' % (entry["score"][0] - entry["score"][1]),
                 ' data-href="%sm/%s.html"' % (root, esc(entry["match_id"]))]
        for player in players:
            short = player["short"]
            row = tracker_by_match.get((short, entry["match_id"]))
            if row is None:
                # THE EMPTY CELL. No character, no title, no aria — a `title` on an empty cell
                # is a tooltip on nothing, and a screen reader announcing "did not play" on
                # thirty of these rows would read the absence louder than the data. The column
                # header says whose column it is and the cell says nothing, which is the fact.
                cells.append("")
                continue
            # No hue wrapper on the cell: `table()` travels a header's class down its own
            # column, so the `p-<short>` on the heading is already on every td under it. A span
            # here would be the same class twice, one inside the other.
            cells.append(signed("mwpa", row["mwpa"]))
            attrs.append(' data-%s="%r"' % (esc(short), row["mwpa"]))
        rows.append({"attrs": "".join(attrs), "cells": cells})
    return table(headers, rows, cls="tbl idx idx-cross")


def offense_defense_payload(site, players):
    """Both halves of every player-match, for the front page's second figure.

    `attack_mwpa` and `defense_mwpa` sum to `mwpa` and live in the PLAYER payloads, which the
    front page does not otherwise carry. They are lifted here rather than added to site.json
    because the two halves are a view of the per-match number the tracker already plots, not a
    new quantity: nothing in the payload contract changes, and no other page gains a byte.
    """
    out = {}
    for entry in site["players"]:
        short = entry["short"]
        out[short] = [
            {"a": row["attack_mwpa"], "d": row["defense_mwpa"], "m": row["mwpa"],
             "map": row["map"], "date": as_long_date(row["started_at"]),
             "won": row["won"], "id": row["match_id"]}
            for row in players[short]["matches"]]
    return out


def build_index(site, players, out_dir):
    n_players = len(site["players"])
    tracker_by_match = {}
    for short, entries in site["tracker"].items():
        for row in entries:
            tracker_by_match[(short, row["match_id"])] = row
    # The index is one row per MATCH now, so the count on the All chip is the match count and
    # not the 108 player-matches the tracker holds. A filter chip narrows those 68 rows to the
    # ones whose `data-player` list contains that short; it does not change what a row is.
    n_rows = len(site["matches"])

    filters = ('  <div class="idx-filter">\n'
               '    <span class="idx-count" data-idx-count></span>\n'
               '    <button class="chip" type="button" data-idx-filter="" '
               'aria-pressed="true">All %s</button>\n%s\n  </div>') % (
        esc(count(n_rows)),
        "\n".join('    <button class="chip p-%s" type="button" data-idx-filter="%s" '
                  'aria-pressed="false">%s</button>'
                  % (esc(p["short"]), esc(p["short"]), esc(display_name(p["name"])))
                  for p in site["players"]))

    body = body_from(
        "index.html",
        tracker_heading=esc("The season, match by match"),
        mwpa_line=esc(mwpa_line()),
        # The one place a fact could go missing without the script, said plainly: the figure is
        # the only thing on this page that draws a player's headline, and the cross-tab under it
        # carries every number the figure is built from.
        tracker_fallback=esc(
            "Drawn by quad-app.js. Without it, every per-match number it plots is in the "
            "cross-tab below, and each player's own headline is on their page."),
        offdef_heading=esc("Offense against defense, every match"),
        offdef_fallback=esc(
            "Drawn by quad-app.js. Without it, both halves of every match are in the %s and "
            "%s columns of each player's own match table." % (label_for("attack_mwpa"),
                                                              label_for("defense_mwpa"))),
        matches_heading=esc("All %s matches, newest first" % count(n_rows)),
        matches_note=esc(
            "Sort on any heading, filter to one player in place, step the rows with j and k. "
            "An empty cell is a match that player was not in — empty is not zero, and those "
            "rows leave a sort rather than joining it at the null."),
        match_filters=filters,
        match_table=merged_index_table(site, "", tracker_by_match),
    )
    return render_page(
        out_dir / "index.html", site,
        # The tab and the link preview name the metric the page ranks on, not the estimator it
        # is rescaled from. "MWPA" said nothing about which of the two numbers the four are
        # sorted by, and the four are sorted by this one. The count is spelled, never typed.
        title="%s %s %s players, act %s" % (label_for("impact"), EM,
                                            spell(n_players), META["act"]),
        description=finding_line(site), page="index", root="", active="index",
        body=body, data=page_data("index", site, od=offense_defense_payload(site, players)))


# -------------------------------------------------------------------------- match page

def team_band(team_id, is_focal, extra=None):
    """The Team column, as a band. One row per side instead of the same word ten times.

    The wash on the `<tbody>` is where the eye finds the break; this row is where the fact is,
    because a wash is colour and colour is never the only carrier. It says the two things the
    column said: which team, and whether it is the side the four played on.

    `extra` is the round ledger's: a team's buy is a team fact, so it is stated once here rather
    than as a Buy class column repeated five times a side under a `.buys` list that said it a
    third time.
    """
    head = "%s %s %s" % (team_id, MIDDOT,
                         "the side the four played on" if is_focal else "opponents")
    if extra:
        head = "%s %s %s" % (head, MIDDOT, extra)
    return {"tbody": {
        "attrs": ' class="team-group%s" data-team="%s"'
                 % (" is-focal" if is_focal else "", esc(team_id)),
        "head": esc(head),
    }}


def match_players_table(match, root, focal_team):
    headers = [(esc(label_for("name")), ""),
               # Left-aligned, which it should always have been: it is a text column, and right
               # alignment gives ten portraits a ragged left edge — the opposite of a scan column.
               (esc(label_for("agent")), "l"), (esc(label_for("mwpa")), "num"),
               ("K", "num"), ("D", "num"),
               ("A", "num"), (esc(label_for("damage")), "num")]
    groups = [("Who", 2), ("The instrument", 1), ("The box score", 4)]
    rows = []
    # Team first, then the move: the rows have to arrive in band order for the bands to exist,
    # and inside a band the sort is the one it always was.
    order = sorted(match["players"], key=lambda r: (r["team"] != focal_team, -r["mwpa"]))
    band = None
    for row in order:
        if row["team"] != band:
            band = row["team"]
            rows.append(team_band(band, band == focal_team))
        if row["is_focal"]:
            who = '<a class="focal" href="%sp/%s.html">%s</a>' % (
                root, esc(row["short"]), esc(display_name(row["name"])))
        else:
            who = '<span class="anon">%s</span>' % esc(display_name(row["name"]))
        rows.append({
            "attrs": ' data-team="%s"%s' % (esc(row["team"]),
                                            ' data-focal="1"' if row["is_focal"] else ""),
            "cells": [
                who,
                agent_cell(row["agent"], root),
                signed("mwpa", row["mwpa"]),
                '<span class="num">%s</span>' % esc(count(row["kills"])),
                '<span class="num">%s</span>' % esc(count(row["deaths"])),
                '<span class="num">%s</span>' % esc(count(row["assists"])),
                '<span class="num">%s</span>' % esc(count(row["damage"])),
            ],
        })
    return table(headers, rows, cls="tbl match-players", groups=groups)


def lobby_tier_fact(match, root):
    """The one division fact a match page gets, in one line, and the one place a badge belongs.

    Not a Tier column: ten divisions across 68 pages is 680 cells putting a rank beside an MWPA,
    which is precisely the misreading `meta.cav.tier_is_not_mwpa` exists to prevent. The range is
    the part that answers a question the page actually asks — who was this against — and its
    answer is that a lobby is not division-homogeneous.

    The badge belongs HERE, on two values and not on six hundred and eighty, because the lobby's
    floor and ceiling are what this line is about. Both ends carry the division word, so the pair
    of badges says "these are two different rungs" at a glance and the words say which two. The
    placement count stays a count: a badge for it would be a badge for the absence of one.
    """
    lobby = match.get("lobby_tiers") or {}
    if not lobby.get("low"):
        return None
    ends = [rank_cell({"tier": lobby["low"]}, root)]
    if lobby["high"] != lobby["low"]:
        ends.append('<span class="rank-to">to</span>')
        ends.append(rank_cell({"tier": lobby["high"]}, root))
    if lobby["placement"]:
        ends.append('<span class="rank-also">%s %s in placement</span>'
                    % (MIDDOT, esc(count(lobby["placement"]))))
    # Joined on a space, not edge to edge: these spans extracted as "Gold 2toPlatinum 1", the
    # same defect the focal cell of the match index had. The gap has to be in the text.
    return '<span class="num rank-range">%s</span>' % " ".join(ends)


def match_rail_html(site, match_id, root):
    """Previous and next match, in the order they were played.

    Sixty-eight match pages had no link to any other match page, so a reader working through one
    evening returned to a hundred-row index each time. Two links close it. There is no thumbnail
    curve on them: at 68x20 in --quiet a win probability curve is a hairline scribble at 1x, and
    the label already says which match it is.
    """
    order = site["matches"]
    at = next(i for i, entry in enumerate(order) if entry["match_id"] == match_id)

    def step(index, cls, arrow_first):
        if index < 0 or index >= len(order):
            return '<span class="step %s is-end">%s</span>' % (
                cls, esc("%s no %s match" % (NDASH, cls)))
        entry = order[index]
        text = "%s %s%s%s %s %s" % (entry["map"], count(entry["score"][0]), NDASH,
                                    count(entry["score"][1]), MIDDOT,
                                    as_long_date(entry["started_at"]))
        label = ("%s %s" % (ARROWS[cls], text)) if arrow_first else ("%s %s" % (text, ARROWS[cls]))
        return '<a class="step %s" href="%sm/%s.html">%s</a>' % (
            cls, root, esc(entry["match_id"]), esc(label))

    return ('  <nav class="match-rail" aria-label="%s">%s'
            '<span class="where">%s</span>%s</nav>') % (
        esc("Previous and next match"), step(at - 1, "prev", True),
        esc("%s of %s" % (count(at + 1), count(len(order)))), step(at + 1, "next", False))


TOP_SWINGS = 3


def focal_swings(match, short_by_puuid):
    """The largest single moves one of the four was on either end of, biggest first.

    ONE EVENT IS ONE ROW, and restricting to the four is what makes that true by construction.
    The payload's own `top_plays` ranks ledger rows across all ten seats, so a kill and the
    death it caused arrived as two rows of the same instant at the same two probabilities —
    which is why a `collapse_mirrors` pass existed — and the six pseudonymous opponents took
    most of the list on a page about these four. The four are all on one side, so no event can
    pay one of them and debit another, and the mirror cannot occur.

    `dp` is the FOCAL SIDE's own move and all four play for the focal side, so the actor's
    credit and the victim's debit are both exactly `dp` with no sign flip. The payload records
    an action's `dp` against its ledger credit times leverage at 2.0e-16 over 10,113 nodes,
    so this is the ledger's number and not a second reading of it.
    """
    score = dict((rnd["round_number"], (rnd["own"], rnd["other"])) for rnd in match["rounds"])
    plays = []
    for node in match["wp_series"]:
        if node["kind"] != "action" or not node.get("dp"):
            continue
        for puuid, key in ((node.get("actor"), None), (node.get("victim"), "death_debit")):
            if puuid not in short_by_puuid:
                continue
            if key is None:
                # ONLY THE CREDIT TYPES. A revive moves the line and the ledger pays nobody
                # for it — there is no revive component — so ranking one here credited a
                # focal player with a swing the round panel below shows them not receiving.
                if node["type"] not in ("kill", "plant", "defuse"):
                    continue
                key = "kill_credit" if node["type"] == "kill" else node["type"]
            own, other = score.get(node["r"], (None, None))
            plays.append({"r": node["r"], "puuid": puuid, "key": key, "mwpa": node["dp"],
                          "own": own, "other": other})
    plays.sort(key=lambda play: -abs(play["mwpa"]))
    return plays[:TOP_SWINGS]


def top_plays_html(plays, name_by_puuid, short_by_puuid):
    """Four facts a row: which round, who, what, and what it was worth.

    The paragraph of context under each of these is gone. It restated the round win
    probability either side of the event, the score and the round's leverage index — three
    quantities in two units to explain one number that is printed directly above them, on a
    page whose every other figure is already in match win probability.
    """
    out = []
    for play in plays:
        where = ""
        if play["own"] is not None:
            where = '<span class="play-at">%s</span>' % esc(
                "at %s%s%s" % (count(play["own"]), NDASH, count(play["other"])))
        out.append(
            '    <li class="play" data-type="%s">\n'
            '      <p class="play-what"><a href="#r%s">Round %s</a> %s '
            '<span class="focal p-%s">%s</span> %s %s</p>\n'
            '      <p class="play-num">%s <span class="unit">%s</span></p>\n'
            '      %s\n    </li>' % (
                esc(play["key"]), esc(play["r"]), esc(count(play["r"])), MIDDOT,
                esc(short_by_puuid[play["puuid"]]), esc(name_by_puuid[play["puuid"]]),
                MIDDOT, esc(label_for(play["key"]).lower()),
                signed("mwpa", play["mwpa"]), esc(DICT["mwpa"]["unit"]), where))
    return "\n".join(out)


# THE LEDGER'S OWN ARITHMETIC, AND IT DOES NOT CLOSE ON ITS OWN. The five credits sum to the
# player's RAW round credit at match scale — `rwpa * leverage`, to 3e-16 across all 17,038
# round-players — and MWPA is that credit CENTRED on the mean credit of everyone else in the
# round, which `meta.dict.mwpa` says in its own definition. The gap between them reaches 2.6
# points, so five parts printed beside a total they do not make is a table that invites the
# reader to check the addition and lose. The centring term is named and drawn as the sixth part,
# and then the column adds up.
LEDGER_PARTS = ["kill_credit", "death_debit", "plant", "defuse", "alive_clock"]
# WHAT THE PLAYER DID versus WHAT THE CONSTRUCTION DID, and it is the payload's own distinction:
# the alive clock is "bookkeeping for who was present while the state aged, not a measure of
# survival skill", and the centring term is arithmetic against the other nine. Those two are
# drawn at half height in the stack. It is the only non-colour channel a segment can have here,
# because hue is a person and sign colour is the direction a probability moved.
LEDGER_BOOKKEEPING = ("alive_clock", "centering")


def ledger_parts(row):
    """One player's round as six signed parts, in a fixed order, summing to MWPA exactly.

    The key and the format key come apart on the last one: `centering` has a label and no
    dictionary entry, because it is arithmetic on two fields the payload does carry rather than
    a field of its own. It borrows MWPA's own format rather than declaring a second one that
    could drift from it, which is why `spec_for("centering")` is never asked for.
    """
    parts = [(key, key, label_for(key), row[key]) for key in LEDGER_PARTS]
    parts.append(("centering", "mwpa", label_for("centering"),
                  row["mwpa"] - sum(row[key] for key in LEDGER_PARTS)))
    return parts


def ledger_part_cell(fmt_key, label, value):
    """One part, at the precision of the field whose unit it is in. Three states: an absent
    value is an em dash, an exact zero is a middot named after the PART's own label, and
    anything else is `signed()`. The zero takes the label rather than the format key because
    the centring term borrows MWPA's format and the key cannot name it."""
    if value is None:
        return '<span class="num none" title="not credited in this round">%s</span>' % EM
    if value == 0:
        return '<span class="num zero" title="no %s in this round">%s</span>' % (
            esc(label.lower()), MIDDOT)
    return signed(fmt_key, value)


def bar_sign(fmt_key, value):
    """The colour class a mark on this axis may take, and it is `signed()`'s rule, not a
    second one. A value measured but smaller than its own format can write prints with no sign
    character and no direction colour, because a direction is a claim that number cannot
    support; a mark drawn for it may not claim one either. At that magnitude it is under a pixel
    of this axis anyway, so what the reader sees is the quiet net mark sitting on the null."""
    step = smallest_printable(fmt_key)
    if value and step is not None and abs(value) < step:
        return "under"
    return sign_of(value)


def ledger_bar(parts, total, scale):
    """The six parts as one signed stack off the null, with the net marked on the same axis.

    WHY A BAR IS BACK INSIDE A TABLE, when `mag_bar` came out of every table for being a second
    rendering of a number the cell already printed: this one draws a quantity no cell holds. A
    long credit arm almost cancelled by a long debit arm, with the net a hair off the null, is
    the whole shape of a round — and in five columns of two-decimal percentages it is invisible.

    Positives stack right of the null and negatives left, both in the order the numbers under
    the bar are printed in, and that order is the only thing naming a segment: hue is a person
    here and sign colour is a direction, so neither is free to say which part this is. Same-sign
    neighbours therefore merge, which is honest — a merged run is that arm's total, and the run
    under the bar splits it.

    THE NET IS A THIRD MARK, because a two-armed stack does not show its own total: MWPA is the
    difference between the arms, not the end of either. It is the site's interval point in the
    site's own geometry, sized past the segment band at both ends so it never disappears into an
    arm of its own colour. `scale` is `meta.scale.round_mwpa`, the pinned p90 of round MWPA, so a
    segment of a given length means the same number on every match page; 15.8% of the
    17,038 bars clip at one end, which is what a p90 axis means, and clipping is flagged at the
    end it ran off.

    No minimum segment width. A part too small to draw is smaller than a pixel of this axis and
    its number is printed under the bar, which is where the fact belongs; a floor would push the
    arms past the values they stand for.
    """
    span = 2.0 * scale
    pos_at, neg_at, segs, clipped = 0.0, 0.0, [], []
    for key, fmt_key, label, value in parts:
        if not value:
            continue
        width = abs(value) / span * 100.0
        if value > 0:
            left = 50.0 + pos_at
            pos_at += width
        else:
            neg_at += width
            left = 50.0 - neg_at
        right = left + width
        for end, off in (("lo", left < 0.0), ("hi", right > 100.0)):
            if off and end not in clipped:
                clipped.append(end)
        draw_left, draw_right = min(max(left, 0.0), 100.0), min(max(right, 0.0), 100.0)
        if draw_right <= draw_left:
            continue
        segs.append(
            # THE TITLE IS THE PRINTED NUMBER, not a second rendering of it. Composing it out of
            # `magnitude` and a hand-written minus wrote `-0.00%` for a value the row under the
            # bar prints as `<0.01%` — a sign and a magnitude the format cannot support, on the
            # one site whose whole rule is that it never claims one.
            '<span class="rl-seg %s%s" style="left:%.3f%%;width:%.3f%%" title="%s"></span>'
            % (bar_sign(fmt_key, value), " is-book" if key in LEDGER_BOOKKEEPING else "",
               draw_left, draw_right - draw_left,
               esc("%s %s" % (label, signed_text(fmt_key, value)[0]))))
    for end, off in (("lo", total < -scale), ("hi", total > scale)):
        if off and end not in clipped:
            clipped.append(end)
    # `aria-hidden`, and it is the correct alternative text rather than laziness: every number in
    # this bar is printed as text under it, so a described bar makes a screen reader read the
    # round's ledger twice. Same argument as the portrait beside a name.
    return ('<span class="rl-bar" aria-hidden="true"%s>%s'
            '<span class="rl-net %s" style="left:%.3f%%"></span></span>'
            % (' data-clipped="%s"' % " ".join(clipped) if clipped else "",
               "".join(segs), bar_sign("mwpa", total), axis_x(total, scale)))


def round_ledger_table(rnd, roster, buy_by_team, focal_team):
    """What each of ten people was worth in this round, and what that figure is made of.

    FOURTEEN COLUMNS BECAME EIGHT, and the six that went were not measurements.

      Buy class was the TEAM's band repeated five times a side, and it now sits once, on that
      team's own band row, beside the side and the loadout that the `.buys` list used to state a
      second time above the table. One statement of a team fact, in the row that names the team.

      Kill credit, death debit, plant, defuse and the alive clock were five columns of small
      signed percentages that the reader had to add in their head against a sixth. They are one
      column now: the stack draws them and the numbers are printed under it in the same order,
      so nothing moved into a tooltip and nothing was rounded away.

      The duel roles moved under the name, where they belong — they are a property of the person
      in this round, and they were the widest column in the table.

    `roster` is still ordered by MATCH MWPA rather than this round's, which is deliberate: the
    same person is on the same line in all twenty-five panels, so a reader stepping through
    rounds is reading a fixed grid rather than re-finding everybody each time.
    """
    headers = [(esc(label_for("name")), ""),
               (esc(label_for("mwpa")), "num"), (null_head(), "z rl-track"),
               (esc(label_for("weapon")), ""), (esc(label_for("loadout")), "num"),
               (esc(label_for("credits")), "num"), ("K", "num"),
               (esc(label_for("damage")), "num")]
    groups = [("Who", 1), ("What they were worth", 2), ("The kit and the box score", 5)]
    by_puuid = dict((row["puuid"], row) for row in rnd["players"])
    scale = SCALE["round_mwpa"]
    rows = []
    band = None
    # `roster` already arrives team-first, which is what makes the bands one pass.
    for person in roster:
        if person["team"] != band:
            band = person["team"]
            buy = buy_by_team.get(band)
            rows.append(team_band(band, band == focal_team, buy and "%s %s %s %s %s %s" % (
                buy["side"], MIDDOT, label_for("loadout").lower(),
                num("loadout", buy["loadout"]), MIDDOT, buy["class"])))
        row = by_puuid.get(person["puuid"])
        who = '<span class="rl-who %s">%s</span>' % (
            "focal p-%s" % esc(person["short"]) if person["is_focal"] else "anon",
            esc(display_name(person["name"])))
        if row is None:
            absent = '<span class="num none" title="not credited in this round">%s</span>' % EM
            rows.append({
                "attrs": ' class="absent" data-team="%s"' % esc(person["team"]),
                # The track cell's em dash rides in `.rl-parts` so it takes the inset the cell
                # itself does not have: `td.z` is padded to nothing horizontally on purpose.
                "cells": [who, absent, '<span class="rl-parts">%s</span>' % absent]
                         + [absent] * 5,
            })
            continue
        # A round can carry several roles. The separator is a real space, so the cell reads as
        # two tags when the text is extracted, not as one word. They wrap now: the reason they
        # could not was a fourteen-column table where one 73px row made the sheet look ragged,
        # and this cell is two lines tall on every row anyway.
        duels = '<span class="duels">%s</span>' % (
            " ".join('<span class="tag" data-duel="%s">%s</span>' % (esc(t), esc(humanize(t)))
                     for t in row["duel"])
            or '<span class="tag none" title="no duel role in this round">%s</span>' % MIDDOT)
        parts = ledger_parts(row)
        rows.append({
            "attrs": ' data-team="%s"%s' % (esc(row["team"]),
                                            ' data-focal="1"' if person["is_focal"] else ""),
            "cells": [
                who + duels,
                signed("mwpa", row["mwpa"]),
                ledger_bar(parts, row["mwpa"], scale)
                + '<span class="rl-parts">%s</span>' % "".join(
                    '<span class="rl-part"><span class="rl-key">%s</span>%s</span>'
                    % (esc(label), ledger_part_cell(fmt_key, label, value))
                    for _, fmt_key, label, value in parts),
                (esc(row["weapon"]) if row["weapon"] else
                 '<span class="none" title="no round-start primary recorded">%s</span>' % EM),
                '<span class="num">%s</span>' % esc(num("loadout", row["loadout"])),
                '<span class="num">%s</span>' % esc(num("credits", row["credits"])),
                '<span class="num">%s</span>' % esc(count(row["kills"])),
                '<span class="num">%s</span>' % esc(count(row["damage"])),
            ],
        })
    return table(headers, rows, cls="tbl round-ledger", groups=groups)


def secs(ms):
    return "%.1fs" % (ms / 1000.0)


# Who a node belongs to, for the three kinds that belong to nobody. Rule 1: an unattributed cell
# is an em dash and a reason, never a blank and never a name invented to fill it.
NOBODY = {
    "round_start": "the economy, before anyone acted",
    "clock": "the state ageing, split across the survivors",
    "terminal": "the model's own gap at the terminal, booked to a side",
}


# Actor and victim in one cell, with the direction as a character rather than an icon or a
# colour: it is read aloud, it scales with the type, and it costs nothing to load. Same argument
# `ARROWS` is written under, and the reason it is not `ARROWS["next"]` is that this arrow means
# "killed", not "forward".
TO = "→"


def timeline_person(puuid, name_by_puuid, short_by_puuid):
    name = esc(display_name(name_by_puuid.get(puuid, puuid)))
    short = short_by_puuid.get(puuid)
    if short:
        return '<span class="focal p-%s">%s</span>' % (esc(short), name)
    return '<span class="anon">%s</span>' % name


def timeline_actor(node, name_by_puuid, short_by_puuid):
    """Who the node belongs to — and, on a kill, who it was done to.

    The victim was in the payload and on no page. A column of actors alone says a kill happened
    and makes the reader carry the other half in their head; `MLK → Anonymous#3da6d8` is the
    round's story in the width the column already had. All 12,673 kill nodes resolve.
    """
    puuid = node.get("actor")
    if not puuid:
        reason = NOBODY.get(node["kind"], "no player is credited for this event")
        return '<span class="none" title="%s">%s</span>' % (esc(reason), EM)
    who = timeline_person(puuid, name_by_puuid, short_by_puuid)
    if node.get("victim"):
        # The spaces are INSIDE the span, so the cell extracts as `MLK → Anonymous#3da6d8`
        # rather than as one word. Same defect the lobby rank range had.
        who += '<span class="rl-vs"> %s </span>%s' % (
            TO, timeline_person(node["victim"], name_by_puuid, short_by_puuid))
    return who


def round_timeline_table(nodes, name_by_puuid, short_by_puuid):
    """The win probability curve for this one round, read down instead of across.

    The ledger beside it says what each of ten players was worth in the round; this says what
    happened in it, in order, and what each thing moved. Same numbers, and the `dp` on an action
    row is the same quantity the ledger credits — the curve's slope is the round's leverage.

    A clock node whose move is under `dp`'s own smallest printable magnitude is not a row. It is
    drift the format cannot write, which would print as a column of `<0.01%` and nothing else.
    They stay inside the footer total, and the footer says how many of them there were, so the
    column still adds up to the line.

    ONLY AN ACTION IS SOMETHING SOMEBODY DID, and that is now structural rather than a shade:
    the three unattributable kinds stay quiet, and an action row also carries a 2px inset rule at
    its left edge. Colour was doing that work alone, which is the one thing this site does not
    let colour do.
    """
    headers = [(esc(label_for("t")), "num"), (esc(label_for("kind")), ""),
               (esc(label_for("name")), ""), (esc(label_for("p")), "num"),
               (esc(label_for("dp")), "num")]
    step = smallest_printable("dp")
    rows, hidden = [], 0
    for node in nodes:
        if node["kind"] == "clock" and step is not None and abs(node["dp"]) < step:
            hidden += 1
            continue
        what = (node_type_label(node["type"]) if node["kind"] == "action" and node.get("type")
                else label_for(KIND_KEY % node["kind"]))
        rows.append({
            "attrs": ' data-kind="%s"' % esc(node["kind"]),
            "cells": [
                '<span class="num">%s</span>' % esc(secs(node["t"])),
                esc(what),
                timeline_actor(node, name_by_puuid, short_by_puuid),
                '<span class="num">%s</span>' % esc(num("p", node["p"])),
                signed("dp", node["dp"]),
            ],
        })
    total = sum(node["dp"] for node in nodes)
    close = nodes[-1]["p"]
    tally = esc("Round total %s %s nodes" % (MIDDOT, count(len(nodes))))
    if hidden:
        tally += esc(", %s of them clock drift under %s, summed here and not listed"
                     % (count(hidden), magnitude("dp", step)))
    foot = ('<th colspan="3" scope="row">%s</th>'
            '<td class="num"><span class="num">%s</span></td>'
            '<td class="num">%s</td>'
            % (tally, esc(num("p", close)), signed("dp", total)))
    return table(headers, rows, cls="tbl round-timeline", foot=foot)


def round_index_html(match, focal_team):
    """A plain index of anchors into the panels below.

    Not the figure's tab bar: the curve is continuous and selects a round itself, announcing it
    as `quad:round`. These anchors exist so every round is reachable by keyboard and by a link,
    and so a page with no script at all still works, where every panel is open and every anchor
    jumps to one. `data-round-tabs` stays on the container because the figure adopts whatever
    strip the page already has rather than growing a second one inside itself.
    """
    out = []
    for rnd in match["rounds"]:
        number = rnd["round_number"]
        won = rnd["winning_team"] == focal_team
        out.append(
            '    <a class="round-tab" href="#r%s" data-round="%s" data-outcome="%s">%s</a>'
            % (esc(number), esc(number), "won" if won else "lost", esc(count(number))))
    return "\n".join(out)


def round_facts_html(rnd):
    """The round's own four facts as labelled values, where a run-on sentence used to be.

    "Blue wins by elimination · score entering 1-2 · round leverage 0.1682 1.04x the act mean"
    was one line of prose carrying four numbers, printed above all 1,713 round panels. The four
    numbers are the content; the verbs were not. `leverage` and `li` are the same quantity twice
    — the index is the leverage over the act mean — and both stay, because the timeline's moves
    are measured in the first and the round's importance is read off the second. Two of the keys
    are written here rather than looked up, for the same reason "Who" and "The box score" are:
    they name a COLUMN of this page, not a field of the payload.
    """
    terminal = (esc(humanize(rnd["terminal_type"])) if rnd["terminal_type"] else
                '<span class="none" title="no terminal recorded">%s</span>' % EM)
    pairs = [
        ("Won by", None, "%s %s %s" % (esc(rnd["winning_team"]), MIDDOT, terminal)),
        ("Score entering", None, "%s%s%s" % (esc(count(rnd["own"])), NDASH,
                                             esc(count(rnd["other"])))),
        (label_for("leverage"), definition_of("leverage"), esc(num("leverage", rnd["leverage"]))),
        (label_for("li"), definition_of("li"), esc(num("li", rnd["li"])) + "×"),
    ]
    return "".join(
        '<span class="rl-fact"><span class="rl-key"%s>%s</span>'
        '<span class="rl-val">%s</span></span>'
        % (' title="%s"' % esc(why) if why else "", esc(key), value)
        for key, why, value in pairs)


def round_panels_html(match, roster, focal_team, shape, name_by_puuid, short_by_puuid):
    panels = []
    for rnd in match["rounds"]:
        number = rnd["round_number"]
        won = rnd["winning_team"] == focal_team
        buy_by_team = dict((b["team_id"], b) for b in rnd["buy"])
        panels.append(
            '  <section class="round-panel" id="r%s" data-round-panel="%s" '
            'data-outcome="%s" aria-labelledby="r%s-h">\n'
            '    <h3 id="r%s-h">Round %s <span class="round-outcome %s">%s</span></h3>\n'
            '    <p class="rl-meta">%s</p>\n'
            '    <div class="scroll" tabindex="0" role="region" '
            'aria-label="Round %s, in order">%s</div>\n'
            '    <div class="scroll" tabindex="0" role="region" '
            'aria-label="Round %s ledger">%s</div>\n'
            '  </section>' % (
                esc(number), esc(number), "won" if won else "lost", esc(number), esc(number),
                esc(count(number)), "won" if won else "lost",
                "focal side won" if won else "focal side lost",
                round_facts_html(rnd),
                esc(count(number)),
                round_timeline_table(shape["by_round"][number],
                                     name_by_puuid, short_by_puuid),
                esc(count(number)),
                round_ledger_table(rnd, roster, buy_by_team, focal_team)))
    return "\n".join(panels)


# The round panels are no longer switched by a tab strip of their own: the figure is the
# selector, and it announces a selection as `quad:round` on `document`. This listens for that
# and does the switching, so the panels follow the chart without either file reaching into the
# other. It also carries the keyboard and no-script paths: the anchors above the panels stay
# real links, `js-tabs` is set only once a switch is known to be possible, and a page whose
# script never runs keeps every panel open. Nothing in it is a count, a name or a format.
ROUND_CONTROLLER = """<script>
(function () {
  "use strict";
  var panels = document.querySelectorAll("[data-round-panel]");
  var links = document.querySelectorAll("[data-round-index] a[data-round]");
  if (!panels.length) return;

  function show(n) {
    if (n === null || n === undefined || n === "") return false;
    var key = String(n), i, on, hit = false;
    for (i = 0; i < panels.length; i++) {
      if (panels[i].getAttribute("data-round-panel") === key) hit = true;
    }
    if (!hit) return false;
    document.documentElement.classList.add("js-tabs");
    for (i = 0; i < panels.length; i++) {
      on = panels[i].getAttribute("data-round-panel") === key;
      panels[i].classList.toggle("is-on", on);
      panels[i].setAttribute("aria-hidden", on ? "false" : "true");
    }
    for (i = 0; i < links.length; i++) {
      on = links[i].getAttribute("data-round") === key;
      links[i].classList.toggle("is-on", on);
      if (on) links[i].setAttribute("aria-current", "true");
      else links[i].removeAttribute("aria-current");
    }
    return true;
  }

  function fromHash() {
    var m = /^#(?:round-|r)(\\d+)$/.exec(location.hash || "");
    return m ? m[1] : null;
  }

  document.addEventListener("quad:round", function (e) {
    if (e && e.detail) show(e.detail.round_number);
  });
  for (var k = 0; k < links.length; k++) {
    links[k].addEventListener("click", function (e) {
      show(e.currentTarget.getAttribute("data-round"));
    });
  }
  window.addEventListener("hashchange", function () { show(fromHash()); });

  if (!show(fromHash()) && links.length) show(links[0].getAttribute("data-round"));
}());
</script>"""


def curve_nodes(match):
    """The curve's own shape, counted rather than assumed."""
    series = match["wp_series"]
    if not series:
        raise AssertionError("%s carries no wp_series" % match["match_id"])
    counts = dict((kind, 0) for kind in KINDS)
    for node in series:
        if node["kind"] not in counts:
            raise AssertionError("%s carries an unknown node kind %r"
                                 % (match["match_id"], node["kind"]))
        counts[node["kind"]] += 1
    actions = [node for node in series if node["kind"] == "action"]
    biggest = max(actions, key=lambda node: abs(node["dp"])) if actions else None
    # The round panels want the same walk the figure wants, so it happens once and both read it.
    by_round = {}
    for node in series:
        by_round.setdefault(node["r"], []).append(node)
    return {"series": series, "counts": counts, "biggest": biggest, "by_round": by_round}


def focal_move(match):
    """The focal players' combined move in this match, and the phrase that says whose it is.

    A MATCH PAGE STATES ITS FINDING IN MWPA AND THAT IS ALREADY THE HEADLINE UNIT. Impact per
    match is the season total over matches played; on one match the denominator is one, so the
    two are the same number and no page has to explain a swap. This is what goes in the title.

    The names lose their Riot tags here, as they do in every other sentence on this site: a
    description is prose, and `#racis` in a link preview is a token the sentence has no use for.
    """
    rows = [row for row in match["players"] if row["is_focal"]]
    combined = sum(row["mwpa"] for row in rows)
    names = and_list(display_name(row["name"]) for row in rows)
    if len(rows) == 1:
        return combined, "%s was worth %s of a match win" % (names, num("mwpa", combined))
    return combined, "%s were worth %s of a match win between them" % (
        names, num("mwpa", combined))


def build_match(site_entry, match, site, out_dir):
    focal_team = next(t["team_id"] for t in match["teams"] if t["focal"])
    other_team = next(t["team_id"] for t in match["teams"] if not t["focal"])
    own = next(t["rounds_won"] for t in match["teams"] if t["focal"])
    other = next(t["rounds_won"] for t in match["teams"] if not t["focal"])
    focal_names = [display_name(row["name"]) for row in match["players"] if row["is_focal"]]
    date = as_long_date(match["started_at"])
    n_rounds = len(match["rounds"])
    title = "%s, %s%s%s" % (match["map"], count(own), NDASH, count(other))
    result = result_word(site_entry["match_id"], site_entry["won"])

    roster = sorted(match["players"], key=lambda r: (r["team"] != focal_team, -r["mwpa"]))
    shape = curve_nodes(match)
    name_by_puuid = dict((row["puuid"], display_name(row["name"]))
                         for row in match["players"])
    short_by_puuid = dict((row["puuid"], row["short"])
                          for row in match["players"] if row["is_focal"])
    # The curve is walked once, before the panels, because each panel's timeline is that walk
    # sliced by round: two walks are two chances for the figure and the table to disagree.
    panels = round_panels_html(match, roster, focal_team, shape, name_by_puuid, short_by_puuid)
    swings = focal_swings(match, short_by_puuid)

    fact_pairs = [
        (label_for("map"), esc(match["map"])),
        (label_for("started_at"), esc(date)),
        # NO ROUNDS ROW. It was the two numbers on the line under it added together, printed as
        # a third fact, on a page whose lede already says how long the match ran. A stat row
        # that is arithmetic on the next stat row is not a fact, it is a restatement.
        (label_for("score"), '<span class="num">%s%s%s</span> for %s' % (
            esc(count(own)), NDASH, esc(count(other)), esc(focal_team))),
        (label_for("won"), '<span class="%s">%s</span>' % (result, result)),
        (label_for("focal"), ", ".join(
            '<a href="../p/%s.html">%s</a>' % (esc(row["short"]),
                                                esc(display_name(row["name"])))
            for row in match["players"] if row["is_focal"])),
    ]
    lobby = lobby_tier_fact(match, "../")
    if lobby:
        fact_pairs.append((label_for("lobby_tiers"), lobby))

    body = body_from(
        "match.html", root="../", title=esc(title),
        subtitle=esc("%s %s %s rounds %s %s played for %s, against %s." % (
            date, MIDDOT, count(n_rounds), MIDDOT,
            and_list(focal_names), focal_team, other_team)),
        facts=facts(fact_pairs),
        match_rail=match_rail_html(site, match["match_id"], "../"),
        figure_heading=esc("%s, action by action" % label_for("wp_series")),
        # The counts, and nothing else. The paragraph that described the line and named its
        # largest move is gone with the methods link beside it: the figure draws both.
        figure_caption="%s %s" % (
            esc("%s nodes: %s."
                % (count(len(shape["series"])),
                   ", ".join("%s %s" % (count(shape["counts"][kind]),
                                        label_for(KIND_KEY % kind).lower())
                             for kind in KINDS))),
            prose(cav("curve"))),
        figure_fallback=esc(
            "The curve is drawn by quad-app.js. Without it, every round below is still open."),
        players_heading=esc("All %s players" % spell(len(match["players"]))),
        players_note=prose(cav("opponents")),
        players_table=match_players_table(match, "../", focal_team),
        top_heading=esc("The %s biggest swings" % spell(len(swings))),
        top_note=esc("Single events, signed, and only the four: a death debit ranks here as "
                     "one."),
        top_plays=top_plays_html(swings, name_by_puuid, short_by_puuid),
        rounds_heading=esc("Round by round"),
        rounds_note=esc("Selecting a round on the figure opens it here."),
        abilities_cav=prose(cav("abilities")),
        round_index=round_index_html(match, focal_team),
        round_panels=panels,
        round_script=ROUND_CONTROLLER)

    data = {"page": "match", "match": match, "scale": SCALE,
            "meta": dict((k, v) for k, v in META.items() if k != "cav")}
    combined, who_moved = focal_move(match)
    return render_page(
        out_dir / "m" / ("%s.html" % match["match_id"]), site,
        # The tab said "MWPA" on all 68 pages, which is the site's name and not this page's
        # finding. It now carries the one number the page is about: what the four were worth
        # here, which on a single match is impact per match with the denominator at one.
        title="%s, %s %s %s" % (title, date, EM, num("mwpa", combined)),
        description="%s %s%s%s on %s: %s, over %s rounds." % (
            match["map"], count(own), NDASH, count(other), date, who_moved, count(n_rounds)),
        page="match", root="../", active=None, body=body, data=data, has_icons=True)


# ------------------------------------------------------------------------- player page
#
# THE CARD, and it is the one object on this site built to be shown to somebody rather than
# interrogated. Its whole design is a single structural claim: THERE ARE TWO REGISTERS HERE AND
# THEY ARE NOT THE SAME KIND OF THING.
#
# On the left, one estimate — impact per match, with its interval drawn on the payload's own
# axis and the null rule running through it. On the right, counts: kills, deaths, assists,
# rounds. A kill happened. An impact per match is a guess with a width. The two are separated by
# one hairline and each side is labelled with what it is, which is the site's entire posture
# stated once, in the place the four of them will actually look.
#
# That is also why no interval, no span and no null rule appears on the right-hand side, and why
# the counts are not drawn as bars: a bar would put a kill count on an axis, and an axis is the
# vocabulary of the left. `cav.the_card_is_counts_not_estimates`.
#
# The strip under both is identity rather than measurement — the agents and the guns, with the
# art that already ships. It is the one place on the site where the artwork is rendered at the
# size the files actually are (`meta.assets.<family>.intrinsic_px`), because everywhere else it
# rides inside a table row and here it is not in one. The word ships beside every picture, so
# the identity control still takes all of it away without losing a fact.


def card_counts(card):
    """Kills, deaths and assists as the line a player already reads themselves in.

    `15 / 15 / 5` is how every scoreboard in this game writes a match, so the card writes the
    act the same way and puts the per-match qualifier under it once instead of three times.
    Three separate stat rows would have been the generic answer and it would also have been
    slower to read than the form the subject already has.
    """
    keys = ("kills_per_match", "deaths_per_match", "assists_per_match")
    # The slash is real punctuation with real spaces around it, not a border between two boxes:
    # copied out of the page and read aloud, this line has to still be three numbers with three
    # names, the same rule the match index's focal chips are held to.
    parts = ['<span class="kda-part"><span class="kda-n">%s</span>'
             '<span class="kda-k">%s</span></span>'
             % (esc(num(key, card[key])), esc(label_for(key))) for key in keys]
    slash = '<span class="kda-slash" aria-hidden="true"> / </span>'
    return '<p class="kda">%s</p>' % slash.join(parts)


def card_art_row(card, key, root, cell, count_key, unit_key):
    """One identity strip: agents by matches, or guns by rounds.

    Nothing is padded. The payload emits what the player has, up to `gate.card_top_n`, and a
    player with two agents gets two chips — an empty third slot would say "there is a third and
    we lost it", which is the one thing an empty slot means everywhere else on this site.

    The unit is singular on one. `1 MATCHES` was on themarias's and trzzcko's cards, on the row
    whose whole job is to be recognised, and a card the reader has to forgive is not the card
    this was for. Both forms come off the payload's own label: see `singular`.
    """
    items = card[key]
    if not items:
        return ""
    plural = label_for(unit_key).lower()
    single = singular(plural)
    return '<ul class="card-art">%s</ul>' % "".join(
        '<li>%s<span class="card-art-n">%s <span class="unit">%s</span></span></li>'
        % (cell(row["name"], root), esc(count(row[count_key])),
           esc(single if row[count_key] == 1 else plural))
        for row in items)


def card_agent_cell(name, root):
    """The agent portrait at its own intrinsic size, and the name beside it. See `agent_cell`."""
    size = (ASSETS.get("agent") or {}).get("intrinsic_px") or ART["--icon-art"]
    file_name = art_file("agent", name)
    chip = ""
    if file_name:
        chip = ('<span class="agent-chip is-card" aria-hidden="true">'
                '<img src="%s%s" width="%d" height="%d" alt="" decoding="async"></span>'
                ) % (root, esc(file_name), size, size)
    return '<span class="agent is-card">%s<span>%s</span></span>' % (chip, esc(name))


def card_weapon_cell(name, root):
    """The weapon silhouette on its plate, contain-fitted into the card's wider slot."""
    box = art_box("weapon", name, (ART["--weapon-card-w"], ART["--weapon-card-h"]))
    file_name = art_file("weapon", name)
    if file_name and box:
        chip = ('<span class="weapon-chip is-card" aria-hidden="true">'
                '<img src="%s%s" width="%d" height="%d" alt="" decoding="async"></span>'
                ) % (root, esc(file_name), box[0], box[1])
    else:
        chip = '<span class="weapon-chip is-card is-none" aria-hidden="true"></span>'
    return '<span class="weapon is-card">%s<span>%s</span></span>' % (chip, esc(name))


def card_side_split(player):
    """The headline broken into the two halves of a round, in the headline's own unit.

    THE ONE CUT OF THE SEASON THAT COSTS NOTHING TO BELIEVE. `impact` is the mean of a player's
    per-match MWPA, and the payload already carries every one of those matches split in two, so
    these two means add back to the headline exactly: no rescale, no second denominator, and
    nothing estimated here that is not already estimated in the number above it.
    `breakdowns.side` says the same thing with an interval and per 100 rounds, and it stays in
    its own table — two units on one card is the confusion the card exists to prevent.
    """
    rows = player["matches"]
    return [(key, sum(row[key] for row in rows) / float(len(rows)))
            for key in ("attack_mwpa", "defense_mwpa")]


def card_record(player):
    """Matches won, lost and drawn, read off the score and never off the flag.

    `result_word` is this site's one reading of a result, and it has to be: the act contains a
    15-15 match whose `won` is false, so a tally of the boolean would print a loss that did not
    happen. The three words and their order are `match_result`'s own. A result nobody had prints
    the middot, which on this site is a measured zero rather than a blank or a dropped slot.
    """
    tally = {}
    for row in player["matches"]:
        word = result_word(row["match_id"], row["won"])
        tally[word] = tally.get(word, 0) + 1
    out = []
    for word in ("won", "lost", "drew"):
        n = tally.get(word, 0)
        out.append((
            '<span class="num %s">%s</span>' % (word, esc(count(n))) if n else
            '<span class="num zero" title="no match in this act ended this way">%s</span>' % MIDDOT,
            word))
    return out


def card_tally(items):
    """A strip of results under a register: the figure, and the word for it underneath.

    ONE SHAPE ON BOTH SIDES OF THE HAIRLINE, and the difference between the two sides is the
    card's whole argument restated in small: every figure on the left prints a sign and none of
    them was counted, every figure on the right was counted and none of them can print one.
    """
    return '<ul class="pc-tally">%s</ul>' % "".join(
        '<li><span class="pc-n">%s</span><span class="pc-k">%s</span></li>' % (value, esc(label))
        for value, label in items)

def card_best(player, dimension):
    """The strongest cell of one breakdown, with its exposure, or None if none qualifies.

    A CARD SAYS THE HEADLINE OF A TABLE, so this picks by rate and refuses a cell the table
    itself marks thin: `Other` weapons over 1.2 rounds of a match would otherwise top three of
    these four cards on a sample the breakdown prints a dotted underline against. If every cell
    in a dimension is thin the best of them still shows, carrying that marker, because the
    alternative is a card that silently has no row for a dimension the reader can see below.
    """
    cells = player["breakdowns"].get(dimension) or []
    solid = [c for c in cells if not c["thin"] and c["rate"] is not None]
    pool = solid or [c for c in cells if c["rate"] is not None]
    if not pool:
        return None
    return max(pool, key=lambda c: c["rate"])


def card_bests(player):
    """Best map, agent and gun, in the estimator's own unit.

    NOT IN THE HEADLINE'S UNIT, and the strip says so once. A breakdown cell holds a slice of a
    match rather than a match, so its match count is a count of matches it appeared in and not
    an exposure to divide by — the same argument that keeps the five tables below in per-100
    rounds. Three rows here, one dimension each, and the tables carry the rest.
    """
    out = []
    for dimension in ("map", "agent", "weapon"):
        cell = card_best(player, dimension)
        if cell is None:
            continue
        out.append((label_for(dimension), cell["key"], cell["rate"], cell["thin"]))
    return out


def card_spark(player, short):
    """Every match this player played, in order, as one small signed path off the null.

    The season tracker on the front page draws the running MEAN and this draws the RAW datum,
    which is the thing that mean is a mean of — the card is the one object built to be shown
    to somebody, and what it was missing was any sense of the spread behind the big number.
    No axis and no ticks: it is a shape, the null under it is the only value it claims, and
    every one of these matches is printed exactly in the table further down the page.
    """
    rows = player["matches"]
    if len(rows) < 2:
        return ""
    w, h, pad = 320.0, 44.0, 3.0
    reach = max(abs(row["mwpa"]) for row in rows) or 1.0
    step = w / float(len(rows) - 1)

    def y(value):
        return h / 2.0 - value / reach * (h / 2.0 - pad)

    line = " ".join(("M%.1f %.1f" if not i else "L%.1f %.1f")
                    % (i * step, y(row["mwpa"])) for i, row in enumerate(rows))
    marks = ['<path class="pc-spark-line" d="%s"/>' % line,
             '<line class="pc-spark-null" x1="0" x2="%.0f" y1="%.1f" y2="%.1f"/>'
             % (w, h / 2.0, h / 2.0)]
    last = rows[-1]
    marks.append('<circle class="pc-spark-end" cx="%.1f" cy="%.1f" r="2.4"/>'
                 % (w, y(last["mwpa"])))
    return ('  <div class="pc-spark p-%s">\n'
            '    <p class="lab">%s</p>\n'
            '    <svg viewBox="-1 0 %.0f %.0f" role="img" aria-label="%s">%s</svg>\n'
            '  </div>') % (
        esc(short),
        esc("%s, every match in order" % label_for("mwpa")),
        w + 2, h,
        esc("%s over %s matches, oldest first, from %s to %s. Every value is in the match "
            "table on this page." % (label_for("mwpa"), count(len(rows)),
                                     num("mwpa", min(r["mwpa"] for r in rows)),
                                     num("mwpa", max(r["mwpa"] for r in rows)))),
        "".join(marks))


def player_card(player, root):
    """The whole card: two registers, one hairline, and the identity strip under them."""
    head = player["headline"]
    card = player["card"]
    short = player["short"]
    scale = SCALE["impact"]

    # THE ONE MARK ON THE CARD, and it is the site's own: a capped span in the player's hue on
    # the payload's fixed headline axis, with the null rule through it at full strength. It is
    # here so the left-hand side is an instrument rather than a big number in a box — the width
    # of that span against the height of that rule IS the finding, and no sentence says it as
    # fast. The axis under it is written out, so the span has a scale and is not decoration.
    #
    # TWO PARAGRAPHS CAME OFF THIS OBJECT AND NEITHER TOOK A FACT WITH IT. The verdict on the
    # interval was already printed one line above where it was written out again, and the round
    # count that explained the width is in the Counted register's own qualifier now. What the
    # space bought is a strip of RESULTS under each register: the headline split by side here,
    # the record over there. Both belong to the register they sit in — the split is the same
    # estimate cut in two, the record is three counts — so neither crosses the hairline.
    # THE INTERVAL IS OFF THE CARD. It was the span, its axis and a line of text — three
    # renderings of one width on the object built to be shown to somebody — and the width is
    # still stated exactly where it is load-bearing: under the waterfall, which is the figure
    # whose whole subject is what the number is made of, and in every breakdown table on this
    # page. What the space bought is three more cuts of the same estimate and the shape of the
    # season behind it.
    bests = card_bests(player)
    estimated = (
        '      <p class="card-reg">%s</p>\n'
        '      <p class="big">%s <span class="unit">%s</span></p>\n'
        '      <div class="pc-strip">\n'
        '        <p class="lab">%s</p>\n'
        '        %s\n'
        '      </div>%s'
    ) % (
        esc("Estimated"),
        signed("impact", head["impact"]), esc(label_for("impact").lower()),
        # The strip says its own unit, because the two figures under it are the number above
        # them cut in two and a reader who lands on the strip first has to be able to tell.
        esc("%s by %s" % (label_for("impact"), label_for("side").lower())),
        card_tally([(signed(key, value), label_for(key))
                    for key, value in card_side_split(player)]),
        ('\n      <div class="pc-strip">\n'
         '        <p class="lab">%s</p>\n'
         '        <ul class="pc-best">%s</ul>\n'
         '      </div>' % (
             # The unit is named here and nowhere else on the card, because it is the one
             # figure on this object that is not per match.
             esc("Strongest, in %s" % label_for("rate")),
             "".join('<li><span class="pc-best-d">%s</span>'
                     '<span class="pc-best-k%s">%s</span>%s</li>'
                     % (esc(dimension), " thin" if thin else "", esc(key),
                        signed("rate", rate))
                     for dimension, key, rate, thin in bests))) if bests else "")

    counted = (
        '      <p class="card-reg">%s</p>\n'
        '%s\n'
        '      <p class="card-per">%s</p>\n'
        '      <div class="pc-strip">\n'
        '        <p class="lab">%s</p>\n'
        '        %s\n'
        '      </div>'
    ) % (
        esc("Counted"),
        card_counts(card),
        # THE DENOMINATOR, AS TWO COUNTS RATHER THAN AS A SENTENCE. The paragraph that used to
        # spell out how long a match is for this player was one division of these two numbers,
        # and both of them are counts, so both of them belong on this side anyway.
        esc("per match, over %s matches and %s rounds of act %s"
            % (count(card["matches"]), count(card["rounds"]), META["act"])),
        esc(label_for("won")),
        card_tally(card_record(player)))

    spark = card_spark(player, short)
    strip = []
    agents = card_art_row(card, "agents", root, card_agent_cell, "matches", "matches")
    if agents:
        more = ""
        if card["agents_played"] > len(card["agents"]):
            more = ' <span class="card-more">%s</span>' % esc(
                "%s more" % count(card["agents_played"] - len(card["agents"])))
        strip.append('    <div class="card-strip-block">\n'
                     '      <p class="card-reg">%s%s</p>\n%s\n    </div>'
                     % (esc(label_for("card_agents")), more, agents))
    weapons = card_art_row(card, "weapons", root, card_weapon_cell, "rounds", "rounds")
    if weapons:
        # The excluded-pistol clause is off the card. It explained an absence nobody asked
        # about, on the object that is meant to be read at a glance; the `by weapon` table on
        # this page is where a reader who wants the weapon rule goes.
        strip.append('    <div class="card-strip-block">\n'
                     '      <p class="card-reg">%s</p>\n%s\n    </div>'
                     % (esc(label_for("card_weapons")), weapons))

    return (
        '  <div class="card p-%s">\n'
        '    <div class="card-face">\n'
        '      <div class="card-reg-est">\n%s\n      </div>\n'
        '      <div class="card-reg-cnt">\n%s\n      </div>\n'
        '    </div>\n'
        '%s'
        '    <div class="card-strip">\n%s\n    </div>\n'
        '  </div>'
    ) % (esc(short), estimated, counted,
         (spark + "\n") if spark else "",
         "\n".join(strip))


# ------------------------------------------------------------- the ledger waterfall
#
# HORIZONTAL BARS, READ TOP TO BOTTOM. Vertical columns would have to carry "Lobby
# adjustment" and "Duel credit" as rotated or wrapped column heads; horizontally they are a
# left-hand column of words at any width, and the ledger is a reading order anyway.
#
# Each bar starts where the one above it ended, so the five parts add up ON THE PAGE and the
# hairline between two bars is the arithmetic. A floating bar is a MOVE and takes sign
# colour; the total hangs off the null in the player's own hue and carries its interval,
# which is the one place the two vocabularies are allowed to meet. What the reader is meant
# to see is the difference between them: five exact cuts of a ledger, and one number that is
# not known. The figure is emitted here rather than drawn by the script, and its geometry is
# arithmetic on one width, so there is no measurement pass and no layout dependency.
WF_W = 960.0             # viewBox width; the same drawing width as the trajectory above it
WF_LABEL_PX = 12.5       # the row label
WF_SUB_PX = 10.5         # the share line and the tick row: `.axlab`'s own size, which is the
                         # size TRACK_MONO_ADV was measured at
WF_LABEL_PAD = 16.0      # the longest label to the plot
WF_VAL_PAD = 16.0        # the plot to the value column
WF_TOP = 30.0            # the first row band, under the panel title
WF_ROW = 42.0            # one component
WF_BAR = 16.0
WF_CAP = 12.0            # the cap a `.rail-iv` has, because this is the same mark
WF_GAP = 16.0            # air on both sides of the rule that cuts the total off its parts
WF_MIN = 1.5             # a bar under this would not render; the number beside it still does
WF_AIR = 1.04            # past the widest mark: no cap may land ON the edge of a plot, where
                         # a line that stopped on its own reads as one that was stopped
WF_FOOT = 12.0


ORDINALS = ["", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th"]


def component_ranks(players):
    """Where each player stands on each row of the ledger, among the focal players.

    THE ONE COMPARISON THE WATERFALL COULD NOT MAKE. A player's page shows what their own
    number is made of and nothing about whether +1.52% of plant is a lot — and the answer is
    four rows away on somebody else's page. This is the whole population: four people, so a
    rank here is not a claim about anybody else in the lobby, and it is a SORT ORDER on a
    quantity whose intervals overlap, which is why it prints as a small ordinal beside the
    figure and never as a medal or a size.

    Ties share the better ordinal, the way a leaderboard does, and the next rank skips.
    """
    out = {}
    keys = set()
    for player in players.values():
        keys.update(player["components"].keys())
    for key in keys:
        scored = []
        for short, player in players.items():
            cell = player["components"].get(key)
            if cell is None:
                continue
            scored.append((component_impact(cell, player["headline"])[0], short))
        scored.sort(key=lambda pair: -pair[0])
        rank = 0
        for i, (value, short) in enumerate(scored):
            if not i or value != scored[i - 1][0]:
                rank = i + 1
            out[(short, key)] = (rank, len(scored))
    return out


def rank_word(short, key):
    """The ordinal, or nothing if this row is not ranked. Never invents a total it lacks."""
    entry = COMPONENT_RANK.get((short, key))
    if not entry:
        return ""
    rank, total = entry
    return "%s of %s" % (ORDINALS[rank] if rank < len(ORDINALS) else count(rank), count(total))


def components_waterfall(player, short):
    """The five parts, walked from the null to the headline they sum to.

    ONE PICTURE WHERE THERE WERE TWO PARAGRAPHS AND A RAIL. Five intervals on one axis were
    five statements the reader had to add up; a walk adds them up in front of them, and the
    connector between two bars is the addition itself.

    IN IMPACT PER MATCH, the number at the top of this page. `component_impact` converts each
    cell on the headline's own denominator, and `build_player` refuses to ship a page whose
    five points do not sum to `impact` at display precision — which is the only reason this
    can be drawn as a walk at all. The total takes `impact_lo` and `impact_hi` straight off the
    payload: no arithmetic on the row the other five are checked against.

    THE TWO HALVES OF THE DUEL are no longer written out beside it. `meta.gate.duel_parts`
    still names them and the payload still carries both; what the row says here is what the
    ledger says, which is that they are one event and are resampled as one column.
    """
    head = player["headline"]
    cells = list(player["components"].items())
    n = len(cells)
    # The walk. Every bar starts at the running total the bar above it left behind, and the
    # last one ends on the headline.
    points, edges, run = [], [0.0], 0.0
    for _, cell in cells:
        point = component_impact(cell, head)[0]
        points.append(point)
        run += point
        edges.append(run)
    # THE AXIS IS THIS PLAYER'S OWN WALK AND THIS PLAYER'S OWN INTERVAL, and that is the one
    # deliberate departure from the pinned corpus axes. A pinned axis exists so that a mark of
    # a given size means the same number on every page, which is the right rule for a quantity
    # a reader compares BETWEEN people. This figure compares nothing between people: it is one
    # ledger, and the only comparison it asks for is between the five cuts and the width of
    # what their sum is not known to. On the pinned headline axis — which is the widest of the
    # four intervals — the two narrow players' parts draw as slivers nobody can tell apart.
    # Every tick prints its own value, so no length here is ever read off another page. Two
    # marks can still stop at nothing but their own value: a walk cannot clamp, because a
    # clamped step would break the chain the figure is made of, and an interval cannot clip,
    # because a clipped interval on the figure whose argument is that the interval is wide is
    # the one mark this site does not draw.
    reach = max([abs(v) for v in edges]
                + [abs(v) for v in (head["impact"], head["impact_lo"], head["impact_hi"])
                   if v is not None])
    # A ledger of exact zeros would divide by one, not by nothing.
    scale = (reach or smallest_printable("impact")) * WF_AIR

    def walked(value):
        """A point on the walk, in words. The start of it is the null and has a name."""
        return label_for("null").lower() if value == 0 else signed_text("impact", value)[0]

    rows = []
    for i, (key, cell) in enumerate(cells):
        text, kind = signed_text("impact", points[i])
        definition = definition_of(key)
        rows.append({
            "label": label_for(key), "value": text, "kind": kind,
            "rank": rank_word(short, key),
            "sub": "%s %s" % (num("share", cell["share"]), label_for("share").lower()),
            "title": "%s: %s per match, %s of the ledger, taking the running total from %s to "
                     "%s.%s" % (label_for(key), text, num("share", cell["share"]),
                                walked(edges[i]), walked(edges[i + 1]),
                                (" " + definition) if definition else "")})
    total, total_kind = signed_text("impact", head["impact"])
    interval = interval_text(head["impact_lo"], head["impact_hi"], "impact")
    verdict = null_verdict(head["covers_zero"])
    rows.append({
        "label": label_for("impact"), "value": total, "kind": total_kind,
        # The summary row is not ranked: the four headlines are on the front page, ordered,
        # under a figure that says how wide their intervals are.
        "rank": "",
        "sub": "%s %s" % (count(head["matches"]), label_for("matches").lower()),
        "title": "%s: %s per match, %s interval %s, which %s."
                 % (label_for("impact"), total, confidence(), interval, verdict)})

    # Both gutters are COMPUTED from the strings that land in them, the way the trajectory's
    # label column is: nothing here is a constant a longer label could overrun. One character
    # is `TRACK_MONO_ADV` scaled by the size — the tracking is the same .06em, so an advance is
    # a ratio of that one measurement and never a second literal.
    adv = TRACK_MONO_ADV * WF_LABEL_PX / WF_SUB_PX
    pad_l = round(max(max(len(row["label"]) for row in rows) * adv,
                      max(len(row["sub"]) for row in rows) * TRACK_MONO_ADV) + WF_LABEL_PAD, 1)
    # The value column now holds two strings on a component row — the figure and where it
    # stands among the four — so the gutter is measured against both, stacked. The ordinal is
    # set at the sub size, so it costs the column only what the wider of the two needs.
    rank_w = max([len(row["rank"]) * TRACK_MONO_ADV for row in rows] or [0.0])
    val_w = round(max(max(len(row["value"]) for row in rows) * adv, rank_w) + WF_VAL_PAD, 1)
    plot = WF_W - pad_l - val_w

    def x(value):
        return pad_l + axis_x(value, scale) / 100.0 * plot

    def cy(i):
        return WF_TOP + i * WF_ROW + WF_ROW / 2.0 + (WF_GAP if i == n else 0.0)

    # The plot ends under the total's own interval, not under its bar: that dimension line is
    # the last mark in the figure and it needs its caps clear of the axis.
    mid = cy(n) + WF_BAR / 2.0 + 5.0
    floor = mid + WF_CAP / 2.0 + 8.0
    tick_y = floor + 18
    note_y = tick_y + 20
    height = note_y + WF_FOOT
    marks = ['<text class="paneltitle" x="%.1f" y="14">%s</text>'
             % (pad_l, esc("%s, in ledger order" % label_for("impact")))]
    # The total is ruled off from the parts, as the rail's summary row was.
    marks.append('<line class="wf-sep" x1="0" x2="%.0f" y1="%.1f" y2="%.1f"/>'
                 % (WF_W, WF_TOP + n * WF_ROW + WF_GAP / 2.0, WF_TOP + n * WF_ROW + WF_GAP / 2.0))
    # THE CONNECTORS ARE THE ARITHMETIC, and they are what makes a waterfall readable: each
    # one leaves the end of a bar and arrives at the start of the next. The last lands on the
    # total's own value rather than on the sum of the five, so the figure closes on the number
    # the payload carries and not on one this file added up.
    for i in range(n):
        end = x(head["impact"] if i == n - 1 else edges[i + 1])
        marks.append('<line class="wf-link" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                     % (end, end, cy(i) + WF_BAR / 2.0, cy(i + 1) - WF_BAR / 2.0))
    # A bar keeps its direction even where its number is under what the format can write: the
    # length is measured, and it is only the digits that cannot say so.
    for i, point in enumerate(points):
        start, end = x(edges[i]), x(edges[i + 1])
        marks.append('<rect class="wf-bar %s" x="%.1f" y="%.1f" width="%.1f" height="%.0f"/>'
                     % (sign_of(point), min(start, end), cy(i) - WF_BAR / 2.0,
                        max(abs(end - start), WF_MIN), WF_BAR))
    zero, tip = x(0.0), x(head["impact"])
    marks.append('<rect class="wf-total" x="%.1f" y="%.1f" width="%.1f" height="%.0f"/>'
                 % (min(zero, tip), cy(n) - WF_BAR / 2.0, max(abs(tip - zero), WF_MIN), WF_BAR))
    if head["impact_lo"] is not None and head["impact_hi"] is not None:
        # AN ESTIMATE, under the bar it belongs to and in the same hue: a capped dimension
        # line, the same mark `.rail-iv` is and at the same cap height. It hangs UNDER the bar
        # rather than through it because the two are two different claims about one number —
        # the bar is where the ledger lands, the line is what the resampling could not rule
        # out — and a line drawn through a solid bar of its own colour fuses them into one
        # striped mark. Neither end can reach the edge of the plot: the axis holds them.
        marks.append('<line class="wf-iv" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                     % (x(head["impact_lo"]), x(head["impact_hi"]), mid, mid))
        for bound in (head["impact_lo"], head["impact_hi"]):
            marks.append('<line class="wf-cap" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                         % (x(bound), x(bound), mid - WF_CAP / 2.0, mid + WF_CAP / 2.0))
    # THE NULL RULE, third instance: full-strength ink at the value that means no claim,
    # heavier than any datum, drawn over the marks it judges rather than under them.
    marks.append('<line class="wf-null" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                 % (zero, zero, WF_TOP - 8, floor))

    for i, row in enumerate(rows):
        marks.append('<text class="wf-label" x="0" y="%.1f">%s</text>'
                     % (cy(i) - 2, esc(row["label"])))
        marks.append('<text class="wf-sub" x="0" y="%.1f">%s</text>'
                     % (cy(i) + 11, esc(row["sub"])))
        # EVERY BAR PRINTS ITS OWN NUMBER, in one right-aligned column, because a figure whose
        # values are only in the hover is a figure half the readers never get.
        # THE FIGURE, AND WHERE IT STANDS. The ordinal sits under the number in the same
        # column, at the sub size and in --quiet: it is a sort order on four overlapping
        # intervals, so it may not carry the weight the measurement carries.
        marks.append('<text class="wf-val %s" x="%.0f" y="%.1f" text-anchor="end">%s</text>'
                     % (row["kind"], WF_W - 2,
                        cy(i) + (0.5 if row["rank"] else 4.0), esc(row["value"])))
        if row["rank"]:
            marks.append('<text class="wf-rank" x="%.0f" y="%.1f" text-anchor="end">%s</text>'
                         % (WF_W - 2, cy(i) + 12.0, esc(row["rank"])))

    steps = [-scale, -scale / 2.0, GATE["null_rate"], scale / 2.0, scale]
    for k, value in enumerate(steps):
        marks.append('<text class="axlab%s" x="%.1f" y="%.0f" text-anchor="%s">%s</text>'
                     % (" is-null" if value == GATE["null_rate"] else "", x(value), tick_y,
                        "start" if k == 0 else "end" if k == len(steps) - 1 else "middle",
                        esc(label_for("null").upper() if value == GATE["null_rate"]
                            else num("impact", value))))
    marks.append('<text class="wf-note" x="%.1f" y="%.0f">%s</text>'
                 % (pad_l, note_y, esc("%s interval %s %s" % (confidence(), interval, verdict))))
    # One hit area per row, across the whole row, carrying the row as a sentence — including
    # the field's own definition, which the rail used to hang off the label. Nothing in it is
    # a number the row does not already print.
    for i, row in enumerate(rows):
        top = cy(i) - WF_ROW / 2.0
        marks.append('<rect class="wf-hit" x="0" y="%.1f" width="%.0f" height="%.1f">'
                     '<title>%s</title></rect>'
                     % (top, WF_W, (floor if i == n else cy(i) + WF_ROW / 2.0) - top,
                        esc(row["title"])))

    # A TITLE AND A DESC, NOT AN aria-label. `role="img"` is children-presentational: an
    # aria-label replaces everything inside the figure with one string, so the six rows and the
    # definition on each hit area reached a reader with a pointer and nobody else. The title is
    # what the figure IS and the desc is what it says, row by row — the same split the two
    # scripted figures already use, and the same facts the bars print.
    title = "%s parts of %s in ledger order, and the total they sum to" % (
        spell(n).capitalize(), label_for("impact").lower())
    desc = "%s Each bar starts where the last ended. %s" % (
        " ".join("%s." % row["title"] for row in rows),
        "The total is %s, %s interval %s, which %s." % (total, confidence(), interval, verdict))
    return ('<div class="fig fig-wf p-%s">\n'
            '    <div class="fig-scroll" tabindex="0" role="region" aria-label="%s">'
            '<svg viewBox="0 0 %d %.0f" role="img" aria-labelledby="%s-wt %s-wd">'
            '<title id="%s-wt">%s</title><desc id="%s-wd">%s</desc>%s</svg></div>\n'
            '  </div>') % (esc(short),
                           esc("%s parts and the total %s scrolls sideways"
                               % (spell(n).capitalize(), EM)),
                           int(WF_W), height, esc(short), esc(short),
                           esc(short), esc(title), esc(short), esc(desc), "".join(marks))


def ladder_heading(player):
    """The heading over the path, off the same three states the sentence under it reads.

    IT WAS A CONSTANT AND IT WAS FALSE ON ONE PAGE. "The one thing that moved" sat over
    TheMarias's ladder above a sentence saying she held one division throughout — a heading
    contradicting the only line in its own section. Nothing on this site claims a direction the
    data does not have, and a heading is not exempt.
    """
    ladder = player["ladder"]
    if not ladder["ranked"]:
        return "The ladder, which was never issued"
    if not (ladder["steps_up"] + ladder["steps_down"]):
        return "The one thing that did not move"
    return "The one thing that moved"


def ladder_sentence(player):
    """What the path did, in one sentence, above the picture of it doing so."""
    ladder = player["ladder"]
    total = len(player["matches"])
    if not ladder["ranked"]:
        return ("No division was issued in any of this player's %s act matches, so there is no "
                "path to draw." % count(total))
    def plural(n, word):
        return "%s %s%s" % (spell(n), word, "" if n == 1 else "s")

    if not (ladder["steps_up"] + ladder["steps_down"]):
        shape = "held %s throughout" % ladder["last"]
    elif ladder["steps_down"]:
        shape = ("climbed from %s to %s, with %s and %s on the way"
                 % (ladder["first"], ladder["last"], plural(ladder["steps_up"], "promotion"),
                    plural(ladder["steps_down"], "demotion")))
    else:
        shape = ("climbed from %s to %s in %s and never fell back"
                 % (ladder["first"], ladder["last"], plural(ladder["steps_up"], "promotion")))
    return ("Across the %s ranked matches that followed %s in placement, this player %s."
            % (count(ladder["ranked"]), count(ladder["placement"]), shape))


# ---------------------------------------------------------------- the rank trajectory
# TWO PLOTS ON ONE X AXIS, never one plot with two scales. Above, the division held at
# each match as a step path in --ink: the third instance of "a line in ink is an exact
# path", in a third unit. Below, that match's MWPA as a bar from the null, in the
# player's hue, on the same fixed axis the rest of the site uses.
#
# The figure is emitted here rather than drawn by the script, so a reader with no
# JavaScript gets the whole object and the crosshair is an enhancement. Its geometry is
# arithmetic on one width, so there is no layout dependency and no measurement pass.
TRACK_W = 960.0          # viewBox width; the SVG scales to its container
# The label gutter is COMPUTED, not a constant, because it now holds two columns — a badge slot
# and a division name — and the name is the variable one. It was a constant when the name was
# right-aligned against the panel; with a badge to its left, right-aligning left a 48px hole
# between the two on this act's short names and would have collided with the ladder's longest.
# Both columns are left-aligned now, so they read as two columns, and the gutter is exactly as
# wide as the longest name on the axis needs.
# The gap between the badge and the first character of the division is not here: it is `--sp-2`,
# read out of the stylesheet, because the same gap in the same place in HTML is `--sp-2` too.
TRACK_LABEL_PAD = 16.0   # between the last character and the panel
TRACK_MONO_ADV = 6.93    # one character at 10.5px mono with .06em tracking, measured in-browser
TRACK_PAD_R = 34.0
TRACK_TOP = 25.0         # first gridline
TRACK_ROW = 34.667       # one division
TRACK_GUTTER = 46.0      # under the last gridline when a placement caption has to fit there:
                         # an empty badge slot one rung below the lowest division, plus air.
                         # It was 82 when it separated two panels; the lower panel is gone.
TRACK_FOOT = 12.0        # clearance under the tick row


def tier_axis(track):
    """Which divisions the y axis carries: the ones held, floored at the payload's minimum.

    A player who held one division would otherwise get a one-row axis and a flat line filling
    the panel edge to edge, which would read as a range. `gate.tier_axis_min_span` stops that,
    and the padding goes UPWARD so the axis never claims a division below the one the player
    actually sat on — an axis that opened at Iron 3 for a Bronze 2 player would be inventing a
    fall he never had.
    """
    ladder = GATE["tier_order"]
    held = [step["ordinal"] for step in track if step["ordinal"] is not None]
    if not held:
        return []
    low, high = min(held), max(held)
    while (high - low + 1) < GATE["tier_axis_min_span"] and high < len(ladder):
        high += 1
    while (high - low + 1) < GATE["tier_axis_min_span"] and low > 1:
        low -= 1
    return [(ordinal, ladder[ordinal - 1]["name"]) for ordinal in range(low, high + 1)]


def rank_badge_svg(name, x, cy, root):
    """One division badge inside the figure, as a bare `<image>` at `--icon-art`.

    THE SLOT WENT WITH THE BOX. It was an `--icon-slot` rect with a 1px `--rule-strong` stroke
    around an `--icon-art` picture, and the two extra pixels existed to hold that rule. The rule
    is gone in both media, so the picture sits at x itself and is 18 wide, exactly what
    `.rank-chip` is in the lobby table — a badge that measured 20 in the figure and 18 six inches
    below it was the same badge at two sizes.

    `aria-hidden` because the axis label beside it says the division in words, and one class on
    the group so the identity control reaches an image inside a figure by exactly the mechanism
    it reaches one inside a table.
    """
    file_name = art_file("rank", name)
    if not file_name:
        return ""
    art = ART["--icon-art"]
    return ('<g class="rank-badge-svg" aria-hidden="true">'
            '<image href="%s%s" x="%.1f" y="%.1f" width="%d" height="%d"/></g>'
            % (root, esc(file_name), x, cy - art / 2.0, art, art))


def rank_trajectory(player, short):
    """The one thing about these four people that measurably moved, drawn in ink."""
    track = player["rank_track"]
    axis = tier_axis(track)
    if not axis:
        return ""
    rows = len(axis)
    # The gutter: a badge, the gap, the longest division name on THIS axis, and a pad. Nothing
    # here is a constant that a longer ladder could overrun, and nothing is wider than it needs.
    #
    # AND THE GAP IS THE STYLESHEET'S. It was 20 + 10 = 30, an eleven-unit hole between an 18px
    # picture and its word, while `.rank` in the lobby table put `--sp-2` — 8px — between the
    # same two things. One family, two media, one measurement: the badge is `--icon-art` wide and
    # the word starts one `--sp-2` after it, both read out of quad-site.css.
    label_x = ART["--icon-art"] + ART["--sp-2"]
    pad_l = round(label_x + max(len(name) for _, name in axis) * TRACK_MONO_ADV
                  + TRACK_LABEL_PAD, 1)
    y_of = dict((ordinal, TRACK_TOP + (len(axis) - 1 - i) * TRACK_ROW)
                for i, (ordinal, _) in enumerate(axis))
    upper_bottom = TRACK_TOP + (rows - 1) * TRACK_ROW
    # ONE PANEL NOW. The lower panel drew this match's MWPA as a bar from the null and it is
    # gone: it was the same per-match number the season tracker on the front page already draws
    # for all four at once and the match table below already prints exactly, so the figure was
    # spending two thirds of its height restating the page. What is left is the one thing about
    # these four people that measurably moved, which is the only reason the figure exists.
    #
    # `floor` is where the placement caption and the x ticks land, and it replaces a geometry
    # that was derived from the deleted panel's half-height. The placement caption needs its
    # own row under the last gridline; the ticks sit under that.
    placement = sum(1 for row in track if row["state"] == "placement")
    floor = upper_bottom + (TRACK_GUTTER if placement else TRACK_ROW)
    tick_y = floor + 22
    height = tick_y + TRACK_FOOT
    plot = TRACK_W - pad_l - TRACK_PAD_R
    n = len(track)
    step_w = plot / n

    def cx(i):
        return pad_l + (i + 0.5) * step_w

    boundary = pad_l + placement * step_w
    marks = []

    # THE PLACEMENT REGION HAS NO AXIS AT ALL. Not a faint one and not a dashed box: the
    # gridlines start at the boundary, because there was no rank to draw them for. The
    # emptiness is labelled and its reason is on the region's own title.
    # THE ONE PLACE ON A PLAYER PAGE WHERE A RANK BADGE IS THE SUBJECT. This axis IS the ladder:
    # every row of it is a division and nothing else, three to five rows, no repeat possible. The
    # badge sits at a fixed x at the far left of the label column and the division name stays
    # right-aligned against the panel, so the badges form one scan column and the words form
    # another. Both are always drawn: the word is what encodes, the badge is recognition, and the
    # identity control hides only the second of the two. A division whose file is missing gets no
    # slot at all rather than an empty one — an empty slot on this axis would read as a rung the
    # player never held, and the empty slot means something specific elsewhere.
    for ordinal, name in axis:
        marks.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                     % (boundary, TRACK_W - TRACK_PAD_R, y_of[ordinal], y_of[ordinal]))
        marks.append(rank_badge_svg(name, 0.0, y_of[ordinal], "../"))
        marks.append('<text class="axlab" x="%.1f" y="%.1f">%s</text>'
                     % (label_x, y_of[ordinal] + 3.5, esc(name)))
    if placement:
        marks.append('<line class="boundary" x1="%.1f" x2="%.1f" y1="18" y2="%.1f"/>'
                     % (boundary, boundary, upper_bottom + 7))
        # One line, under the region, in the gutter. It was three lines inside the region and
        # that put a second label column beside the division names, sharing a vertical rhythm
        # the two do not agree on — and the width of the region varies from 63% of the panel
        # (eight matches) to 8% (sixty), so no position inside it is safe at every n. The
        # emptiness above is what carries the meaning; this says what the emptiness is.
        #
        # AND THIS IS WHERE UNRATED GETS ITS RENDERING. The line now starts in the same two
        # columns as every division above it — an EMPTY slot in a dashed hairline, then the words
        # — so the placement prefix reads as one more rung of the same ladder with nothing issued
        # into it. It is not an em dash, which on this site means NOT MEASURED; it is not a zero;
        # and it is not Riot's own string, which is the name of a queue. cav has the argument.
        caption = "%s %s%s%s %s in placement, no rank issued" % (
            label_for("matches").lower(), count(1), NDASH, count(placement), MIDDOT)
        # The empty rung is the only rank box left on the site, and it is drawn at `--icon-art`
        # with its hairline inside that width — the same 18px `.rank-chip.is-empty` occupies
        # under `box-sizing: border-box`. It was 20 while the badges above it were 18, so the one
        # box that survives sat two pixels wider than the column it heads.
        art = ART["--icon-art"]
        baseline = upper_bottom + 30
        marks.append('<g><title>%s</title>'
                     '<rect class="badge-box is-empty" x="0.5" y="%.1f" width="%d" height="%d" '
                     'rx="2"/><text class="axlab" x="%.1f" y="%.1f">%s</text></g>'
                     % (esc(CAV["unrated_is_not_a_division"]),
                        baseline - art / 2.0 - 3.0, art - 1, art - 1,
                        label_x, baseline, esc(caption)))

    ranked = [row for row in track if row["state"] == "ranked"]
    if ranked:
        # A STEP, not a slope. The division did not drift between two matches: it was one value
        # for the whole of one match and another value for the whole of the next, and the change
        # happened at the boundary between them. Drawing the join as a diagonal would invent a
        # rate of change on a quantity that has none.
        points = ["M%.1f %.1f" % (boundary, y_of[ranked[0]["ordinal"]])]
        for k, row in enumerate(ranked):
            edge = cx(row["i"]) + step_w / 2.0
            points.append("L%.1f %.1f" % (edge, y_of[row["ordinal"]]))
            if k + 1 < len(ranked):
                points.append("L%.1f %.1f" % (edge, y_of[ranked[k + 1]["ordinal"]]))
        path = " ".join(points)
        # A step path on an ordinal axis lies ALONG its own gridlines by construction, so 2px of
        # ink over a 1px gridline merges into one line and the path disappears. The casing is the
        # panel colour and breaks the gridline exactly where the path crosses it.
        marks.append('<path class="track-case" d="%s"/>' % path)
        marks.append('<path class="track" d="%s"/>' % path)
        for row in ranked:
            marks.append('<circle class="track-dot" cx="%.1f" cy="%.1f" r="2"/>'
                         % (cx(row["i"]), y_of[row["ordinal"]]))

    # x ticks every five matches, and the final one only when it clears the previous.
    ticks = [i for i in range(0, n, 5)]
    if n - 1 not in ticks and cx(n - 1) - cx(ticks[-1]) > 26:
        ticks.append(n - 1)
    for i in ticks:
        marks.append('<text class="axlab" x="%.1f" y="%.0f" text-anchor="middle">%s</text>'
                     % (cx(i), tick_y, esc(count(i + 1))))
    # NO DATES ON THIS AXIS. A date at each end was drawn here and then cut, and the reason is
    # worth keeping: x is MATCH ORDER, an ordinal, and two dates at the two ends of an axis are
    # how you label a linear scale. This act is not evenly spread — one of these four played
    # thirteen matches in a day — so a reader taking the ends as a time scale would read the
    # spacing between the steps as elapsed time, which is the quiet kind of lie this site
    # refuses. Every date is exact in the readout and in the table below.

    marks.append('<text class="paneltitle" x="%.0f" y="14">%s</text>'
                 % (pad_l, esc("Division, in match order")))

    # The crosshair opens on the demotion, because a fall is the one step on this path that a
    # badge and a division count both delete. With no demotion it opens on the last match.
    opening = next((row["i"] for before, row in zip(ranked, ranked[1:])
                    if row["ordinal"] < before["ordinal"]), n - 1)
    marks.append('<line class="cross" data-track-cross x1="%.1f" x2="%.1f" y1="18" y2="%.1f"/>'
                 % (cx(opening), cx(opening), floor))
    for row in track:
        marks.append('<rect class="hitbar" data-track-hit="%d" x="%.1f" y="18" width="%.1f" '
                     'height="%.1f"><title>%s</title></rect>'
                     % (row["i"], pad_l + row["i"] * step_w, step_w, floor - 18,
                        esc(track_line(player, row, plain=True))))

    label = ("One axis of %s matches in the order they were played, carrying the division held "
             "at each as a step path in ink." % count(n))
    svg = ('<svg viewBox="0 0 %d %.0f" role="img" tabindex="0" aria-label="%s" '
           'data-track-fig>%s</svg>' % (int(TRACK_W), height, esc(label), "".join(marks)))
    return ('<div class="fig fig-track p-%s">%s'
            '<p class="fig-track-readout" data-track-readout aria-live="polite">%s</p></div>'
            % (esc(short), svg, track_line(player, track[opening])))


def track_line(player, step, plain=False):
    """One match, as the readout reads it: where, what division, and what it was worth."""
    row = dict((m["match_id"], m) for m in player["matches"])[step["match_id"]]
    division = step["tier"] or "%s, no rank issued" % step["state"]
    parts = [
        ("%s " % label_for("match_id").lower(), count(step["i"] + 1),
         " of %s" % count(len(player["matches"]))),
        ("", "%s %s %s" % (as_long_date(row["started_at"]), MIDDOT, row["map"]),
         " %s %s" % (MIDDOT, result_word(row["match_id"], row["won"]))),
        ("%s " % label_for("tier").lower(), division, ""),
        ("%s " % label_for("mwpa"), num("mwpa", row["mwpa"]), ""),
    ]
    if plain:
        return " · ".join("".join(part).strip() for part in parts)
    return "".join("<span>%s<b>%s</b>%s</span>" % (esc(a), esc(b), esc(c)) for a, b, c in parts)


def player_matches_table(player):
    """Every match, and — new this round — the division held when it was played.

    The Tier column is the table twin of the trajectory above it: the figure shows the shape and
    this shows the value, so nothing on this page is readable only by hover. It is here and
    nowhere else. A division beside a per-match MWPA on a table the reader has already been told
    how to read is a fact; the same pair on 68 match pages, ten rows at a time, is the misreading
    `meta.cav.tier_is_not_mwpa` exists to prevent.
    """
    steps = {step["match_id"]: step for step in player["rank_track"]}
    headers = [(esc(label_for("started_at")), ""), (esc(label_for("map")), ""),
               (esc(label_for("tier")), "l"),
               (esc(label_for("agent")), ""),
               (esc(label_for("won")), ""), (esc(label_for("mwpa")), "num"),
               (esc(label_for("attack_mwpa")), "num"), (esc(label_for("defense_mwpa")), "num")]
    rows = []
    for row in player["matches"]:
        result = result_word(row["match_id"], row["won"])
        rows.append([
            '<a href="../m/%s.html">%s</a>' % (esc(row["match_id"]),
                                               esc(as_long_date(row["started_at"]))),
            # badge=False: forty-five of these sixty rows are the same division. See rank_cell.
            esc(row["map"]), rank_cell(steps[row["match_id"]], "../", badge=False),
            esc(row["agent"]),
            '<span class="%s">%s</span>' % (result, result),
            signed("mwpa", row["mwpa"]),
            signed("attack_mwpa", row["attack_mwpa"]),
            signed("defense_mwpa", row["defense_mwpa"]),
        ])
    return table(headers, rows, cls="tbl player-matches")


def one_cluster(cell, matches_key="matches"):
    """A cell whose rounds all come from one match has one bootstrap cluster."""
    return cell.get(matches_key) == 1 and cell.get("rate") is not None


def interval_cell(cell, matches_key="matches"):
    """The interval, or the reason there is not one.

    A bootstrap clustered on match has ONE cluster on a one-match cell, so the
    interval collapses to a point and reads as EXCLUDING the null with more
    confidence than anything else on the site. That is the tightest, most
    certain-looking number here and it is an artefact. It does not print.
    """
    if one_cluster(cell, matches_key):
        return ('<span class="num none" title="%s">%s one match, no interval</span>'
                % (esc(CAV["single_match_interval"]), EM))
    return '<span class="num">%s</span>' % esc(interval_text(cell["lo"], cell["hi"]))


def exposure_cell(cell, rounds_key="rounds", matches_key="matches"):
    """Why this interval is as wide as it is, in one column.

    Rounds against `meta.gate.exposure_threshold_rounds`, which is the rounds a
    leverage-weighted rate needs before its interval can exclude the null.
    """
    rounds = cell.get(rounds_key)
    if not rounds:
        return '<span class="num none" title="no rounds in this cell">%s</span>' % EM
    share = rounds / float(GATE["exposure_threshold_rounds"])
    out = ['<span class="num%s" title="%s of the %s rounds an interval this wide needs">%s</span>'
           % (" thin" if cell.get("thin") else "", esc(count(rounds)),
              esc(count(GATE["exposure_threshold_rounds"])), esc(num("exposure", share)))]
    if one_cluster(cell, matches_key):
        out.append('<span class="marker one-match">one match</span>')
    return " ".join(out)


def breakdown_key_cell(dimension, key, root):
    """The cell that names the row. For `by weapon` it also carries the silhouette.

    THIS IS THE OTHER HALF OF THE LEDGER ARGUMENT. A breakdown row is a distinct value by
    construction — that is what a breakdown is — so this column is n shapes for n rows and the
    picture is a direct handle on the row rather than a texture over it. The same icon in the
    round ledger would repeat its modal glyph in half of every ten-seat column, which is why it is
    not there; `meta.cav.where_imagery_is_allowed` carries both measurements.
    """
    if dimension == "weapon":
        return weapon_cell(key, root)
    return esc(key)


def breakdown_table(cells, dimension, short, root):
    # THE z COLUMN IS GONE FROM THIS TABLE AND FROM THE SYNERGY ONE. It drew the interval a
    # third time: the point estimate is in `rate`, both ends are in the interval column, and
    # the bar restated the pair at a lower precision on a fixed axis this page never names.
    # The uncertainty stays — it is two numbers wide and it was always the numbers doing the
    # work. See `interval_cell`.
    #
    # The dimension's own label, not the payload's field name for the column that holds it.
    # "Cell" is what `key` is called in the contract; "Map" is what the column says.
    #
    # THREE REGISTERS, CARRIED BY THE HEADER. A header's class travels down its own column, so
    # `bt-key`, `bt-find`, `bt-ival` and `bt-aside` are the entire hierarchy of these six
    # tables and no cell needs a class of its own: the row's name, the finding, the width of
    # the finding, and the exposure that explains the width. `l` came off the weapon column
    # with the bar — every column here is left-aligned by default now, and `l` also resets the
    # weight this file wants on the column that names the row.
    headers = [(esc(label_for(dimension)), "bt-key"),
               (esc(label_for("matches")), "num bt-aside"),
               (esc(label_for("exposure")), "num bt-aside"),
               (esc(label_for("rate")), "num bt-find"),
               ("%s interval" % confidence(), "num bt-ival"),
               (esc(label_for("total")), "num")]
    rows = []
    for cell in cells:
        rows.append({
            "attrs": ' data-key="%s"%s' % (esc(cell["key"]),
                                           ' data-thin="1"' if cell["thin"] else ""),
            "cells": [
                breakdown_key_cell(dimension, cell["key"], root),
                '<span class="num">%s</span>' % esc(count(cell["matches"])),
                exposure_cell(cell),
                signed("rate", cell["rate"]),
                interval_cell(cell),
                signed("total", cell["total"]),
            ],
        })
    return table(headers, rows, cls="tbl bt breakdown p-%s" % short)


def breakdowns_html(player, short, root):
    """Five blocks, stacked, and stacked is a decision rather than what was already here.

    TABS AND TWO COLUMNS WERE BOTH CONSIDERED AND BOTH LOSE SOMETHING REAL. A tab puts four of
    the five findings behind a click on a page whose posture is that nothing is readable only
    by interaction, and it needs script to do it on a site that has to open off disk. Two
    columns halve the width of a six-column table and put all five into permanent horizontal
    scroll on a laptop. What was actually wrong with the stack was the TEXT: five identical
    sentences counting rows the reader can see. That count is now a figure beside the heading,
    and the two notes that survive are the two facts a table cannot state about itself.
    """
    note_for = {
        "side": "The split needs about %s rounds at this credit variance; the act has %s."
                % (count(GATE["side_split_rounds"]), count(META["rounds"])),
        "weapon": "The weapon is the one held at round start; the short tails are Other.",
    }
    out = []
    for key in BREAKDOWN_ORDER:
        cells = player["breakdowns"][key]
        note = ('\n    <p class="note">%s</p>' % esc(note_for[key])) if key in note_for else ""
        out.append(
            '  <section class="breakdown-block bt-block" id="by-%s" aria-labelledby="by-%s-h">\n'
            '    <div class="bt-head">\n'
            '      <h3 id="by-%s-h">By %s</h3>\n'
            '      <p class="bt-count">%s</p>\n'
            '    </div>\n'
            '    <div class="scroll" tabindex="0" role="region" aria-label="%s">%s</div>%s\n'
            '  </section>' % (
                esc(key), esc(key), esc(key), esc(label_for(key).lower()),
                esc("%s %s" % (count(len(cells)), "cell" if len(cells) == 1 else "cells")),
                # R1: five breakdown scrollers per player page had no tabindex, no role and no
                # label, so a keyboard-only reader could not reach the columns they hide.
                esc("%s by %s, with its interval" % (label_for("mwpa"), label_for(key).lower())),
                breakdown_table(cells, key, short, root), note))
    return "\n".join(out)


def breakdown_unit_note(player):
    """Why these five tables are not in the unit at the top of the page, with the deciding number.

    The division would RUN — every breakdown cell carries a match count — and it would be
    wrong: the thinnest cell on this page is a rounding of one match, so its match count counts
    the matches the cell APPEARED in and is not an exposure. Per 100 rounds is the honest
    denominator for a slice of a match, and the column header says so on all six tables.

    IT ALSO CARRIES THE TWO CLAUSES THAT USED TO PRINT OVER EVERY BLOCK. The thin marker has no
    other legend, and an absent cell is missing rather than blank — which is the one thing about
    these tables the em dash rule cannot say, because there is no cell there to put a dash in.
    """
    thinnest = min(cell["rounds"] / float(cell["matches"])
                   for key in BREAKDOWN_ORDER for cell in player["breakdowns"][key])
    return ("In %s, not per match: the thinnest cell here is %s rounds of a match, so a match "
            "count is not an exposure. Under %s rounds a cell is marked thin; with no rounds it "
            "is not a row at all."
            % (label_for("rate"), format(thinnest, ".1f"),
               count(GATE["rate_floor_marker_rounds"])))


def synergy_table(player, short):
    # NO ROUNDS COLUMN, here as everywhere. `shared_rounds` was a column of its own beside an
    # Exposure cell computed from the same field, which is the round count twice in adjacent
    # columns and the second of them headed with the word. The count is not lost: `Exposure`
    # says it against the threshold the way the five breakdown tables do, and carries the raw
    # number in its title.
    #
    # NO z COLUMN EITHER, for the reason `breakdown_table` gives, and the column order is that
    # table's now. Six tables on one page reading four different ways were four ways of reading
    # one thing. The hue on this table is the FOCAL player's and not the partner's: every number
    # in it is this player's own rate over the rounds that partner also played.
    headers = [(esc(label_for("partner_name")), "bt-key"),
               (esc(label_for("shared_matches")), "num bt-aside"),
               (esc(label_for("exposure")), "num bt-aside"),
               (esc(label_for("rate")), "num bt-find"),
               ("%s interval" % confidence(), "num bt-ival")]
    rows = []
    for cell in player["synergy"]:
        empty = cell["rate"] is None
        reason = "never shared a round with this partner in this act"
        rows.append({
            "attrs": ' data-partner="%s"%s' % (esc(cell["partner_short"]),
                                               ' data-empty="1"' if empty else ""),
            "cells": [
                '<a href="%s.html">%s</a>' % (esc(cell["partner_short"]),
                                              esc(display_name(cell["partner_name"]))),
                '<span class="num">%s</span>' % esc(count(cell["shared_matches"])),
                ('<span class="marker empty">no shared rounds</span>' if empty
                 else exposure_cell(cell, "shared_rounds", "shared_matches")),
                signed("rate", cell["rate"], absent_reason=reason),
                ('<span class="num none" title="%s">%s</span>' % (esc(reason), EM) if empty
                 else interval_cell(cell, "shared_matches")),
            ],
        })
    return table(headers, rows, cls="tbl bt synergy p-%s" % short)


def build_player(site, player, out_dir):
    head = player["headline"]
    short = player["short"]

    # THE ASSERTION ITEM 10 ASKS FOR, and it is a build failure rather than a note on the page.
    # Merging two rows into one is a display decision; a display decision that quietly broke the
    # arithmetic under the headline would be the worst thing this site could ship. The five
    # converted points must sum to `impact` to better than half of what `impact`'s own format
    # can write, which is the same precision the sentence on the page reconciles at.
    reconciled = sum(component_impact(cell, head)[0]
                     for cell in player["components"].values())
    if abs(reconciled - head["impact"]) >= smallest_printable("impact") / 2.0:
        raise AssertionError(
            "%s: the %d components sum to %r against a headline of %r"
            % (short, len(player["components"]), reconciled, head["impact"]))
    # And the merged row is the two halves, exactly. If it were not, the rail would be printing
    # a number that is in neither the ledger nor the payload.
    # The tolerance is the payload's own rounding and nothing looser: totals are written to six
    # decimals, so three rounded numbers can disagree by 1.5e-6 and by nothing more than that.
    parts_total = sum(player["duel_parts"][key]["total"] for key in GATE["duel_parts"])
    if abs(parts_total - player["components"][GATE["duel_key"]]["total"]) > 2e-6:
        raise AssertionError("%s: %s is not %s summed"
                             % (short, GATE["duel_key"], " + ".join(GATE["duel_parts"])))

    body = body_from(
        "player.html", root="../", title=esc(display_name(player["name"])),
        card=player_card(player, "../"),
        components_heading=esc("The %s parts, and the headline they sum to"
                               % spell(len(player["components"]))),
        components_waterfall=components_waterfall(player, short),
        ladder_heading=esc(ladder_heading(player)),
        ladder_note=esc(ladder_sentence(player)),
        ladder_figure=rank_trajectory(player, short),
        # THE NUMBER THAT STOPS THE LADDER BEING READ AS A SECOND OPINION ON THE RATING, and
        # it says whose it is. Printed identically under four different players' paths, "across
        # 144 ranked lobbies" read as that player's 144 on a page whose act has 83 matches; it
        # is the whole corpus of focal player-matches with enough ranked others in the lobby.
        ladder_cav=esc("The ladder is a second instrument, and this is the act rather than "
                       "this player: across all %s focal player-matches with at least %s "
                       "ranked others in the lobby, the lobby's division correlates with that "
                       "match's %s at r = %s."
                       % (count(META["ladder"]["n"]), count(META["ladder"]["minimum_ranked"]),
                          label_for("mwpa"), format(META["ladder"]["r_mwpa"], "+.3f"))),
        matches_heading=esc("All %s matches" % count(len(player["matches"]))),
        matches_table=player_matches_table(player),
        breakdown_note=esc(breakdown_unit_note(player)),
        breakdowns=breakdowns_html(player, short, "../"),
        synergy_heading=esc("With each of the other %s" % spell(len(player["synergy"]))),
        synergy_table=synergy_table(player, short),
        # The scroller's own label, from this page's numbers rather than from the template: it
        # said "Rate alongside each of the other three", which named the old headline and typed
        # a count. It is the only text on this page a sighted reader never sees.
        synergy_label=esc("%s alongside each of the other %s"
                          % (label_for("rate"), spell(len(player["synergy"])))),
        synergy_cav=esc("Each row is this player's own %s over the rounds that partner also "
                        "played, so the two directions of a pairing differ. Per 100 rounds, "
                        "like the five tables above." % label_for("mwpa")))

    return render_page(
        out_dir / "p" / ("%s.html" % player["short"]), site,
        # The tab carried the estimator's name and no number. It now carries this player's own
        # headline, which is the one thing a link to this page is a link to.
        title="%s %s %s %s, act %s" % (display_name(player["name"]), EM,
                                       num("impact", head["impact"]),
                                       label_for("impact").lower(), META["act"]),
        description="%s: %s %s over %s matches of act %s, %s interval %s, which %s." % (
            display_name(player["name"]), num("impact", head["impact"]),
            label_for("impact").lower(),
            count(head["matches"]), META["act"], confidence(),
            interval_text(head["impact_lo"], head["impact_hi"], "impact"),
            null_verdict(head["covers_zero"])),
        page="player", root="../", active=player["short"], body=body,
        # A player page carries division badges on the trajectory axis and a weapon silhouette on
        # every `by weapon` row, so it gets the control that removes them. It had no imagery and
        # no control before this round.
        data=page_data("player", site, player=player), has_icons=True)


# ------------------------------------------------------------------------------- build

def main():
    global META, DICT, GATE, CAV, SCALE, ASSETS, ART, RESULT, NAME
    site, players, matches = load_payload()
    META = site["meta"]
    DICT = META["dict"]
    GATE = META["gate"]
    ASSETS = META.get("assets", {})
    # THE TWO OVERRIDES THIS FILE MAKES ON THE PAYLOAD'S OWN DICTIONARY, both of them display
    # precision and neither of them a definition. They are applied to META itself so that
    # quad-shared.js carries them too: build.py and quad-app.js must never write the same
    # quantity at two precisions.
    for key, spec in DECIMALS.items():
        DICT[key]["format"] = spec
    NAME = dict((entry["name"], SHORT_NAME.get(entry["name"].split("#")[0],
                                               entry["name"].split("#")[0]))
                for entry in site["players"])
    ART = css_px("--icon-art", "--icon-slot", "--weapon-art-w", "--sp-2",
                 "--icon-card", "--weapon-card-w", "--weapon-card-h")

    CAV = dict((item["id"], item["text"]) for item in META["cav"])
    COMPONENT_RANK.update(component_ranks(players))
    SCALE, drift, widened = pinned_scales(
        site, players, matches, rescale="--rescale" in sys.argv)
    # One reading of the score, shared by every surface that prints a result word.
    RESULT = dict((entry["match_id"], match_result(entry)[0]) for entry in site["matches"])

    # THE REFUSAL, MADE EXECUTABLE — and it is unchanged now that all three families ship. The
    # guard never said "one family"; it says a folder of artwork must be DECLARED, in the payload,
    # by name, with an explicit file map behind it. Three folders are declared this round where
    # one was, so it passes honestly, and a fourth appearing on disk — re-downloaded, restored,
    # copied in by a later contributor — still stops the build until someone deletes it or writes
    # it into the payload on purpose. The point was never that imagery is forbidden; it is that
    # imagery arrives through the payload or it does not arrive.
    declared = {Path(path).parent.name
                for family in META.get("assets", {}).values()
                for path in family.get("files", {}).values()}
    found = {folder.name for folder in (HERE / "assets").iterdir() if folder.is_dir()}
    if found - declared:
        raise AssertionError(
            "undeclared image families on disk: %s. %s"
            % (", ".join(sorted(found - declared)), CAV["where_imagery_is_allowed"]))
    # And the mirror of it: a family declared in the payload whose folder is gone would render
    # every one of its names as a bare word with no sign that anything was lost. That is the
    # failure the explicit map is supposed to make impossible, so it is checked rather than
    # trusted.
    if declared - found:
        raise AssertionError("declared image families with no folder on disk: %s"
                             % ", ".join(sorted(declared - found)))

    if len(site["matches"]) != META["matches"]:
        raise AssertionError("site.matches is %d rows against meta.matches %d"
                             % (len(site["matches"]), META["matches"]))
    if len(matches) != META["matches"]:
        raise AssertionError("%d match payloads against meta.matches %d"
                             % (len(matches), META["matches"]))
    total_rounds = sum(len(m["rounds"]) for m in matches.values())
    if total_rounds != META["rounds"]:
        raise AssertionError("%d rounds across the match payloads against meta.rounds %d"
                             % (total_rounds, META["rounds"]))
    total_round_players = sum(len(r["players"]) for m in matches.values() for r in m["rounds"])
    if total_round_players != META["round_players"]:
        raise AssertionError("%d round-players against meta.round_players %d"
                             % (total_round_players, META["round_players"]))
    # The match index carries the round count as a scalar and the match payload carries the rounds
    # themselves. Two sources for one number, so the build refuses to emit a page where they differ.
    off = [entry["match_id"] for entry in site["matches"]
           if entry["rounds"] != len(matches[entry["match_id"]]["rounds"])]
    if off:
        raise AssertionError("site.matches rounds disagree with the match payload: %s"
                             % ", ".join(off))
    # The curve is the match page's figure now, so a match without one is a page that cannot be
    # built rather than a page with an empty box on it. Every round contributes a start and a
    # terminal, so those two counts are the round count and are checked against it.
    curve = {}
    for match_id, match in matches.items():
        curve[match_id] = curve_nodes(match)
    total_nodes = sum(len(shape["series"]) for shape in curve.values())
    node_kinds = dict((kind, sum(shape["counts"][kind] for shape in curve.values()))
                      for kind in KINDS)
    for kind in ("round_start", "terminal"):
        if node_kinds[kind] != META["rounds"]:
            raise AssertionError("%d %s nodes against meta.rounds %d"
                                 % (node_kinds[kind], kind, META["rounds"]))
    total_events = sum(len(rnd["events"]) for m in matches.values() for rnd in m["rounds"])
    if node_kinds["action"] != total_events:
        raise AssertionError("%d action nodes against %d events in the round payloads"
                             % (node_kinds["action"], total_events))

    written = []
    sizes = {}

    sizes["index"] = build_index(site, players, HERE)
    written.append(HERE / "index.html")

    match_bytes = 0
    for entry in site["matches"]:
        match = matches[entry["match_id"]]
        match_bytes += build_match(entry, match, site, HERE)
        written.append(HERE / "m" / ("%s.html" % entry["match_id"]))
    sizes["match"] = match_bytes

    player_bytes = 0
    for entry in site["players"]:
        player_bytes += build_player(site, players[entry["short"]], HERE)
        written.append(HERE / "p" / ("%s.html" % entry["short"]))
    sizes["player"] = player_bytes

    # THE METHODS PAGE IS GONE, at the owner's instruction: this site is public and the model
    # behind these numbers is not. The one sentence each page needed from it — what a caveat
    # covered — is now printed on that page in full, and the stale file is removed rather than
    # left orphaned in the directory where a search engine or a saved link could still reach it.
    stale = HERE / "methods.html"
    if stale.exists():
        stale.unlink()

    (HERE / "quad-shared.js").write_text(shared_js(site), encoding="utf-8")
    (HERE / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    expected = META["matches"] + len(site["players"]) + 1
    if len(written) != expected:
        raise AssertionError("wrote %d pages against %d expected" % (len(written), expected))
    missing = [str(p) for p in written if not p.exists()]
    if missing:
        raise AssertionError("pages missing after write: %s" % ", ".join(missing))

    total = sum(p.stat().st_size for p in written) + (HERE / "robots.txt").stat().st_size
    print("pages       %d  (%d match, %d player, index)"
          % (len(written), META["matches"], len(site["players"])))
    print("match pages %d rounds, %d round-players inlined"
          % (total_rounds, total_round_players))
    print("curve       %d nodes inlined  (%s)"
          % (total_nodes, ", ".join("%s %d" % (kind, node_kinds[kind]) for kind in KINDS)))
    print("bytes       index %d, players %d, matches %d, total on disk %d"
          % (sizes["index"], sizes["player"], sizes["match"], total))
    print("bar axes    " + ", ".join("%s %.4f" % (k, v) for k, v in sorted(SCALE.items())
                                     if k != "percentile")
          + " (p%d, pinned in %s)" % (SCALE["percentile"], SCALE_PIN.name))
    if widened:
        print("            impact widened to hold a new interval; the pin was rewritten")
    if drift:
        # Printed, never acted on. The pin is what the bars used; this is the corpus saying how
        # far it has moved since somebody last agreed to that pin, so the decision to follow it
        # stays a decision. `--rescale` takes it.
        print("axis drift  " + ", ".join("%s pinned %.4f, corpus now %.4f" % (k, a, b)
                                         for k, (a, b) in drift.items())
              + "  — rerun with --rescale to adopt")


if __name__ == "__main__":
    main()
