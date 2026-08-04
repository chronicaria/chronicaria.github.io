#!/usr/bin/env python3
"""Static-site generator for the four-player MWPA dashboard.

Run:  python3 build.py        (from anywhere; paths are self-relative)

Reads valorant/quad/payload/ and writes, beside this file:

    index.html            four ranked cards, the tracker container, the match index
    m/<match_id>.html     one per match, with that match's payload inlined
    p/<short>.html        one per focal player
    methods.html          the metric, the interval, the caveats, the field list
    robots.txt

Every page inlines its own JSON as `window.QUAD` in a script tag, so every page opens
off file:// with no fetch. On the front page `window.QUAD` is site.json, with its own
keys at the root; a player page adds that player's block beside them. A match page
carries only its own match payload, under `match`, with the meta block the figure needs
to format a number beside it. No page carries a second match.

Nothing here hardcodes a definition, a threshold or a count. Labels, formats,
definitions, the thin-cell floor and the caveat texts all come from `meta.dict`,
`meta.gate` and `meta.cav`. The two things this file does decide are which fields go in
which column and the percentile the magnitude bars fill against, and both are stated on
the methods page.

The presentation layer is split: this file emits semantic HTML and the data-driven
inline widths, `quad-site.css` styles it, and `quad-app.js` fills `[data-tracker]` and
`[data-match-figure]`. Both of those live beside this file and belong to another build.
The class vocabulary they can rely on:

    .cards .card                front-page player cards
    .mag .mag-half .mag-zero .fill      magnitude bar, zero line in the middle
    .ival .ival-span .ival-point .ival-zero      interval bar on the same fixed axis
    .pos .neg .zero .none       sign classes, on numbers and on fills
    .num                        any figure; monospace, right aligned
    .tbl .scroll                data table, and its horizontal scroll container
    .facts .cavs                definition lists
    .round-strip .round-index .round-tab .round-panel   round index; panels are visible without JS
    .marker .tag .fallback .note .cav .standfirst       inline markers and prose

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
# quantity being drawn, never against the largest row on screen. Stated on the methods page.
BAR_PERCENTILE = 90
# The gate a single action has to clear before it gets a marker of its own on the
# win probability curve, and the axis that marker is sized against. See bar_scales.
MARKER_PERCENTILE = 99

# Fields the payload's own dict does not carry, because they only exist at round grain.
# `rwpa`, `rwpa_centered` and `team` came out with the columns that printed them. The payload
# still carries all three and the methods glossary note is derived from this map, so a label
# left here would have told the reader about columns no page has.
FALLBACK_LABEL = {
    "duel": "Duel", "li": "Leverage index",
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
# player page. Both are on methods, in full, with every other caveat; what a breakdown needs
# beside it is the one number that explains its own width, and that number is in meta.gate.
# Only the caveats a page still prints. Four came out of this map with the paragraphs they
# fed — act scope, the ranking decision, the component sum, the ordered synergy — because a
# caveat repeated above every figure is a caveat nobody finishes. Every one of them is on
# methods, in full, and the pages that dropped them kept the one sentence that was load-bearing.
CAV_ON_PAGE = {
    "opponents": "pseudonymous_opponents",
    "abilities": "no_abilities",
    "thin": "thin_cells_shown",
    "single_match": "single_match_interval",
    "causal": "descriptive_not_causal",
    "curve": "wp_curve_boundary_seam",
}

META = {}
DICT = {}
GATE = {}
CAV = {}
SCALE = {}
ASSETS = {}
ART = {}
RESULT = {}


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
        # The component rail is drawn per match now, so its axis is in per-match units too. The
        # p90 of these seventy-two rate endpoints is 2.056, so a rail axis derived from the rates
        # would be 2.056 wide against rows printing +38.6%.
        for cell in player["components"].values():
            point, lo, hi = component_impact(cell, player["headline"])
            component.extend([abs(point), abs(lo), abs(hi)])
    # THE HEADLINE AXIS, and it is a maximum for the same reason the grain ruler below is. The
    # four rows of the standings rail are the whole population of this quantity and all four are
    # on screen at once: p90 of those twelve numbers is 0.1576, which would clip trzzcko's high
    # end at +0.2331 and themarias's low end at -0.1615 — two of the four intervals, including
    # the one the ranking argument is about. A clipped interval on the figure that exists to say
    # the intervals are wide is the one bar on this site that cannot be allowed to stop at the
    # axis.
    impact = []
    for row in site["players"]:
        impact.extend([abs(row["impact"]), abs(row["impact_lo"]), abs(row["impact_hi"])])
    # THE COMMON RULER. One axis shared by all four grains on every player page,
    # so a single action, the round it ended, the worst match and the whole act
    # are drawn at their real relative sizes. It is the act's own maximum rather
    # than a percentile, because a grain figure whose largest bar clipped would
    # be making exactly the comparison it exists to refuse.
    grain = []
    for player in players.values():
        grain.append(abs(player["headline"]["total"]))
        for row in player["matches"]:
            grain.append(abs(row["mwpa"]))
    for match in matches.values():
        for rnd in match["rounds"]:
            for row in rnd["players"]:
                grain.append(abs(row["mwpa"]))
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
        "grain": max(grain),
    }


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


def as_date(iso):
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(iso, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("unparseable timestamp: %s" % iso)


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


def signed(key, value, absent_reason="not measured"):
    """A number carrying its sign three ways: the printed sign, a colour class, and — where
    a bar is drawn beside it — which side of the null that bar hangs off.

    HOUSE RULE 2, AND WHERE ITS THREE CHANNELS NOW ARE. The direction arrows are gone; the
    `+` or `-` the format itself prints is the channel that does not depend on colour, so
    this refuses any key whose format has no sign flag rather than trusting that every one
    of them has one. Colour is never alone and cannot become alone by a payload edit.

    Three states, and they are three different facts. An absent value is an em
    dash with its reason. An exact zero is a middot: measured, and neither
    direction. A value that is measured but smaller than its own format can
    write prints as less-than the smallest printable number, with no sign and
    no direction colour — printing `+0.00%` claims a direction the number
    cannot support, and printing an em dash would claim the value is missing
    when it is not. `meta.cav.measured_zero_at_display_precision` is the reason.
    """
    if "+" not in spec_for(key):
        raise AssertionError(
            "signed(%s) on format %s, which prints no sign: the sign character is the "
            "non-colour channel and this field has none" % (key, spec_for(key)))
    kind = sign_of(value)
    if kind == "none":
        return '<span class="num none" title="%s">%s</span>' % (esc(absent_reason), EM)
    if kind == "zero":
        return '<span class="num zero" title="an exact zero, measured">%s</span>' % MIDDOT
    step = smallest_printable(key)
    if step is not None and abs(value) < step:
        return ('<span class="num under" title="measured, and smaller than the smallest number '
                'this field is written to">&lt;%s</span>') % esc(magnitude(key, step))
    # No empty element where the arrow used to be: an empty `.glyph` span still carries the
    # stylesheet's own margin and would print a gap between the sign and the number.
    glyph = ('<span class="glyph" aria-hidden="true">%s</span>' % GLYPH[kind]) if GLYPH[kind] else ""
    return '<span class="num %s">%s%s</span>' % (kind, glyph, esc(num(key, value)))


def ledger_cell(key, value, absent_reason="not credited in this round"):
    """Round-ledger figure. An exact zero is a measured zero and reads as a middot."""
    if value is None:
        return '<span class="num none" title="%s">%s</span>' % (esc(absent_reason), EM)
    if value == 0:
        return '<span class="num zero" title="no %s in this round">%s</span>' % (
            esc(label_for(key).lower()), MIDDOT)
    return signed(key, value)


def spoken(key, value):
    """The number as the cell beside the bar PRINTS it, in words a screen reader can read out.

    A magnitude bar's accessible name used to be `num(key, value)`, which has neither of
    `signed`'s two special states. A cell reading `<0.1%` sat next to a bar announcing
    "+0.0% match win probability points" — 1,678 of them across the 74 pages once the round
    timeline started drawing a bar per node at `dp`'s coarser format — and
    `meta.cav.measured_zero_at_display_precision` says in as many words that such a value prints
    with no sign and no direction. An exact zero has the same problem: the eye gets a middot and
    the ear got a sign. One number, one spelling, in both channels.
    """
    if value == 0:
        return "zero"
    step = smallest_printable(key)
    if step is not None and abs(value) < step:
        return "less than %s" % magnitude(key, step)
    return num(key, value)


def mag_bar(value, scale, aria):
    """Magnitude bar with the zero line in the middle: sign is position as well as colour."""
    if value is None:
        return '<span class="mag none" role="img" aria-label="%s"></span>' % esc(aria)
    kind = sign_of(value)
    width = min(abs(value) / scale, 1.0) * 100.0
    clipped = clip_flag(min(value, 0.0), max(value, 0.0), scale)
    fill = '<span class="fill %s" style="width:%.2f%%"></span>' % (kind, width)
    return (
        '<span class="mag" role="img" aria-label="%s"%s>'
        '<span class="mag-half mag-neg">%s</span>'
        '<span class="mag-zero" aria-hidden="true"></span>'
        '<span class="mag-half mag-pos">%s</span></span>'
    ) % (esc(aria), clipped, fill if kind == "neg" else "", fill if kind == "pos" else "")


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


def covers_zero_sentence(row, rounds_key="rounds"):
    """The wording the interval drives, per the payload's own flag."""
    rounds = row.get(rounds_key)
    if row.get("covers_zero") is None:
        return "There is no interval here, because there are no rounds to resample."
    if row["covers_zero"]:
        return ("The interval covers zero: %s rounds do not separate this from no effect at "
                "all." % count(rounds))
    if row.get("matches") == 1:
        return ("The interval excludes zero, and it should not be read that way: every one "
                "of these %s rounds comes from a single match, so the match-clustered "
                "bootstrap has one cluster and nothing to vary." % count(rounds))
    return "The interval excludes zero on %s rounds." % count(rounds)


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


def rail_estimate(point, lo, hi, scale):
    """An ESTIMATE: a capped dimension line, with the point estimate a notch."""
    if lo is None or hi is None:
        return '<span class="rail-track-inner"></span>'
    left, right = axis_x(lo, scale), axis_x(hi, scale)
    clipped = clip_flag(lo, hi, scale)
    return (
        '<span class="rail-track-inner"%s>'
        '<span class="rail-iv" style="left:%.2f%%;width:%.2f%%">'
        '<span class="cap lo"></span><span class="cap hi"></span></span>'
        '<span class="rail-point" style="left:%.2f%%"></span></span>'
    ) % (clipped, left, max(right - left, 0.4), axis_x(point, scale))


def rail_magnitude(value, scale, cls="plain"):
    """An EXACT MAGNITUDE: a solid bar hanging off the null, no end caps."""
    if value is None:
        return '<span class="rail-track-inner"></span>'
    zero, at = axis_x(0.0, scale), axis_x(value, scale)
    left, width = min(zero, at), abs(at - zero)
    clipped = clip_flag(min(value, 0.0), max(value, 0.0), scale)
    return ('<span class="rail-track-inner"%s>'
            '<span class="rail-bar %s %s" style="left:%.2f%%;width:%.2f%%"></span></span>'
            ) % (clipped, cls, sign_of(value), left, width)


def rail_width(width, scale):
    """A WIDTH drawn from the null: how wide a thing is, on the same axis."""
    zero = axis_x(0.0, scale)
    span = min(abs(width) / (2.0 * scale), 1.0) * 100.0
    return ('<span class="rail-track-inner">'
            '<span class="rail-span" style="left:%.2f%%;width:%.2f%%"></span></span>'
            ) % (zero, span)


def rail_axis(scale, unit_label, key):
    """The rail's own axis, on the rail's own grid, with the null named on it.

    `key` is the field whose format writes the ticks. Three rails run on three quantities and
    the axis has to be written in the unit of the one it is under. It has NO default: the
    default was `rate`, and it was what put +.3f ticks under a grain rail whose rows are
    written +.4f and under a standings rail whose rows are written +.1%. A caller that forgets
    the unit now fails to build instead of printing the old headline's format."""
    steps = [-scale, -scale / 2.0, GATE["null_rate"], scale / 2.0, scale]
    # The two quarter ticks are marked so the narrow layout can drop them. At
    # 375px the track is 163px wide and five mono labels need about 200px, so
    # all five ran into each other and the null's own name was overprinted by
    # the numbers on either side of it. The ends and the null survive, which
    # is the whole axis: a range and the value it is read against.
    quarters = (steps[1], steps[3])
    ticks = "".join(
        '<span%s style="left:%.2f%%;transform:translateX(%s)">%s</span>' % (
            ' class="is-null"' if value == GATE["null_rate"]
            else ' class="is-quarter"' if value in quarters else "",
            axis_x(value, scale),
            "0" if value == steps[0] else "-100%" if value == steps[-1] else "-50%",
            # BOTH ENDS SIGNED. The right half printed through `magnitude`, so an axis running
            # "-23.3% ... THE NULL ... 23.3%" sat one line under a standfirst that writes the
            # same two numbers as "-23.3% to +23.3%", and under rows whose whole format rule is
            # that the sign always prints. The tracker's own y axis already writes "+10.0%".
            esc(label_for("null").upper()) if value == GATE["null_rate"]
            else esc(num(key, value)))
        for value in steps)
    return ('<div class="rail-axis"><span class="rail-axis-unit lab">%s</span>'
            '<span class="rail-axis-ticks" aria-hidden="true">%s</span></div>'
            ) % (esc(unit_label), ticks)


def rail_row(label_html, track_html, nums_html, cls=""):
    return ('    <div class="rail-row%s">\n'
            '      <div class="rail-label">%s</div>\n'
            '      <div class="rail-track">%s</div>\n'
            '      <div class="rail-nums">%s</div>\n'
            '    </div>' % (" " + cls if cls else "", label_html, track_html, nums_html))


def rail(rows, cls="", null_f=None):
    """One rail, and one null rule through every row of it."""
    style = ' style="--null-f:%.5f"' % null_f if null_f is not None else ""
    return ('  <div class="rail%s"%s>\n'
            '    <div class="rail-track-layer" aria-hidden="true"></div>\n%s\n  </div>'
            ) % (" " + cls if cls else "", style, "\n".join(rows))


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
        links.append(("p/%s.html" % entry["short"], entry["name"], entry["short"]))
    links.append(("methods.html", "Methods", "methods"))
    out = []
    for href, label, key in links:
        current = ' aria-current="page"' if key == active else ""
        out.append('    <a href="%s%s"%s>%s</a>' % (root, href, current, esc(label)))
    return "\n".join(out)


def footer_html(root):
    return (
        '  <p class="scope">Act %s. %s matches, %s rounds, %s round-players, %s distinct '
        'players. Release %s, built %s.</p>\n'
        '  <p class="disclosure">Not indexed, which is not the same as not public: '
        '<a href="%smethods.html#caveats">the caveats say what that means</a>.</p>'
    ) % (esc(META["act"]), count(META["matches"]), count(META["rounds"]),
         count(META["round_players"]), count(META["players"]), esc(META["release"]),
         esc(META["generated_at"]), root)


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


def render_page(out_path, site, title, description, page, root, active, body, data,
                has_icons=False):
    shell = string.Template((TEMPLATES / "page.html").read_text(encoding="utf-8"))
    html = shell.substitute(
        title=esc(title), description=esc(description), page=esc(page), root=root,
        nav=nav_html(site, root, active), body=body, footer=footer_html(root),
        icons_toggle=icons_toggle_html(has_icons), data=inline_json(data))
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
    return "%s matches, %s players ranked by %s %s %s." % (
        count(META["matches"]), spell(len(players)), label_for("impact").lower(), EM, tail)


def finding_headline(site):
    """The finding in a dozen words, and it is the payload's own flags that write it.

    It counts MATCHES now rather than rounds: the headline quantity is per match played, so
    the exposure the reader should have in mind is the one the metric is divided by."""
    players = site["players"]
    covering = [p for p in players if p["covers_zero"]]
    if len(covering) == len(players):
        return ("%s people, %s matches, and the measurement cannot tell them apart."
                % (spell(len(players)).capitalize(), count(META["matches"])))
    return ("%s people, %s matches, and %s of the %s beat the null."
            % (spell(len(players)).capitalize(), count(META["matches"]),
               spell(len(players) - len(covering)), spell(len(players))))


def finding_standfirst(site):
    """One sentence, and it is the whole argument: there is an order and it is smaller
    than the uncertainty on a single one of its own rows."""
    players = site["players"]
    covering = [p for p in players if p["covers_zero"]]
    spread = max(p["impact"] for p in players) - min(p["impact"] for p in players)
    widest = max(players, key=lambda p: p["impact_hi"] - p["impact_lo"])
    lead = ("Every interval covers the null" if len(covering) == len(players)
            else "%s of the %s intervals cover the null"
                 % (spell(len(covering)).capitalize(), spell(len(players))))
    return ("%s, and the widest is %s times the whole spread of the order."
            % (lead, format((widest["impact_hi"] - widest["impact_lo"]) / spread, ".1f")))


def standings_rail(site, root):
    """The four, on one axis, against one null.

    Four cards would be four zero lines that happen to line up, and the site's
    whole claim is about one. So: four rows, one rule, and beneath them the same
    axis again carrying the two widths that make the argument — the whole
    ranking, and one player's interval.

    The quantity is IMPACT PER MATCH. The rate per 100 rounds it is rescaled from is a positive
    constant apart from it — rounds per match runs 19.5 to 21.2 across these four — so the order
    of the rows is the order that rail always had, and the BCa endpoints are the same endpoints.
    """
    players = site["players"]
    scale = SCALE["impact"]
    rows = []
    for entry in players:
        # Eight characters, in --quiet, at label size: the division this player held at their
        # last act match. A FACT, on its own deliberate line so it cannot be read as a trend —
        # the shape of the path is on the player page, at 860px, where it is legible.
        ladder = entry.get("ladder") or {}
        ended = ('<span class="rail-sub">%s</span>'
                 % esc("ended the act at %s" % ladder["last"])) if ladder.get("last") else ""
        label_html = (
            '<span class="rail-rank">%s / %s</span>'
            '<span class="rail-who p-%s"><a href="%sp/%s.html" title="%s">%s</a></span>'
            '<span class="rail-sub">%s %s %s %s</span>%s'
        ) % (esc(count(entry["rank"])), esc(count(len(players))), esc(entry["short"]),
             root, esc(entry["short"]), esc(entry["name"]),
             # A Riot tag is one unbreakable token and some of them are long.
             # The rail carries the name; the full tag is on the link and in
             # the nav, so nothing is lost and no word breaks mid-glyph.
             esc(entry["name"].split("#")[0]),
             esc(count(entry["rounds"])), esc(label_for("rounds").lower()), MIDDOT,
             esc("%s %s" % (count(entry["matches"]), label_for("matches").lower())), ended)
        nums = '%s<span class="rail-iv-text">%s</span>' % (
            signed("impact", entry["impact"]),
            esc("%s %s" % (interval_text(entry["impact_lo"], entry["impact_hi"], "impact"),
                           null_verdict(entry["covers_zero"]))))
        rows.append(rail_row('<span class="p-%s">%s</span>' % (esc(entry["short"]), label_html),
                             '<span class="p-%s">%s</span>' % (
                                 esc(entry["short"]),
                                 rail_estimate(entry["impact"], entry["impact_lo"],
                                               entry["impact_hi"], scale)),
                             nums))

    # FOR SCALE. The two widths on the axis they are widths of, so the argument
    # is a picture instead of a sentence the reader has to take on trust.
    spread = max(p["impact"] for p in players) - min(p["impact"] for p in players)
    widest = max(players, key=lambda p: p["impact_hi"] - p["impact_lo"])
    rows.append(rail_row(
        '<span class="rail-rank">%s</span><span class="rail-who">%s</span>' % (
            esc("FOR SCALE"), esc("The whole ranking")),
        rail_width(spread, scale),
        '<span class="num">%s</span><span class="rail-iv-text">wide</span>'
        % esc(magnitude("impact", spread)), cls="is-scale"))
    rows.append(rail_row(
        '<span class="rail-who p-%s">%s</span>' % (
            esc(widest["short"]), esc("%s's interval" % widest["name"].split("#")[0])),
        '<span class="p-%s">%s</span>' % (
            esc(widest["short"]),
            rail_width(widest["impact_hi"] - widest["impact_lo"], scale)),
        '<span class="num">%s</span><span class="rail-iv-text">wide</span>'
        % esc(magnitude("impact", widest["impact_hi"] - widest["impact_lo"]))))
    return rail_axis(scale, label_for("impact"), "impact") + "\n" + rail(rows)


def ladder_front_note(site):
    """The eight new characters on each rail row, in one sentence, with the number that
    stops them being read as a second opinion on the rating: r = +0.074."""
    return ("The last line of a row is the division held at the final act match; across %s "
            "ranked lobbies it correlates with that match's %s at r = %s."
            % (count(META["ladder"]["n"]), label_for("mwpa"),
               format(META["ladder"]["r_mwpa"], "+.3f")))


def exposure_rail(site):
    """Rounds played, against the rounds an interval this wide needs.

    The threshold is `meta.gate.exposure_threshold_rounds` — a research figure,
    now carried by the payload rather than quoted inside a caveat, because the
    view draws a rule at it.
    """
    threshold = GATE["exposure_threshold_rounds"]
    top = max([p["rounds"] for p in site["players"]] + [threshold]) * 1.08
    rows = []
    for entry in sorted(site["players"], key=lambda p: -p["rounds"]):
        share = entry["rounds"] / float(threshold)
        width = min(entry["rounds"] / top, 1.0) * 100.0
        cut = min(threshold / top, 1.0) * 100.0
        if width > cut:
            bar = ('<span class="rail-track-inner">'
                   '<span class="exposure-bar" style="width:%.2f%%"></span>'
                   '<span class="exposure-over" style="left:%.2f%%;width:%.2f%%"></span></span>'
                   ) % (cut, cut, width - cut)
        else:
            bar = ('<span class="rail-track-inner">'
                   '<span class="exposure-bar" style="width:%.2f%%"></span></span>') % width
        rows.append(rail_row(
            '<span class="rail-who p-%s">%s</span>' % (esc(entry["short"]),
                                                       esc(entry["name"].split("#")[0])),
            '<span class="p-%s">%s</span>' % (esc(entry["short"]), bar),
            '<span class="num">%s</span><span class="rail-iv-text">%s of threshold</span>' % (
                esc(count(entry["rounds"])), esc(num("exposure", share)))))
    return (rail(rows, cls="is-exposure", null_f=min(threshold / top, 1.0)),
            threshold, top)


def exposure_line(site):
    """One sentence, and it carries the threshold, so the note above the rail could go."""
    threshold = GATE["exposure_threshold_rounds"]
    clear = [p for p in site["players"] if p["rounds"] >= threshold]
    if not clear:
        return ("Not one of the %s has the %s rounds an interval this wide needs to exclude "
                "the null." % (spell(len(site["players"])), count(threshold)))
    names = and_list(p["name"].split("#")[0] for p in clear)
    still = [p for p in clear if p["covers_zero"]]
    tail = (", and the interval still %s the null" % ("cover" if len(still) > 1 else "covers")
            if still else "")
    return ("Only %s %s the %s rounds an interval this wide needs%s."
            % (names, "have" if len(clear) > 1 else "has", count(threshold), tail))


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


def merged_index_table(site, root, name_of, tracker_by_match):
    """ONE ROW PER MATCH, newest first, and the row IS the link.

    It was one row per player per match, which printed the score, then the margin, then the
    word won — three spellings of the same fact, on 108 rows for 68 matches. The scoreline
    carries all three, the focal players collapse into one cell of hued chips, and the signed
    column is the four's COMBINED move in that match with the null painted through it.

    Nothing here reads the tracker's own order: `data-date` is on every row and quad-app.js
    sorts on it, so the default order and the sorted order come from the same field.

    THE MARGIN SORT LIVES ON THE RESULT CELL. Merging the score, the margin and the word won
    into one cell was right — they were three spellings of one fact — but the ordering was a
    fourth thing and it went with them, and ordering sixty-eight matches by how close they were
    stopped being possible anywhere on the site. `data-margin` is back on the row and the Result
    heading is the button that reads it: the cell already prints both numbers it is derived from.
    """
    headers = [('<button class="sort" type="button" data-sort="margin">%s'
                '<span class="sort-mark"></span></button>' % esc(label_for("won")), "l"),
               ('<button class="sort" type="button" data-sort="date">%s'
                '<span class="sort-mark"></span></button>' % esc(label_for("match_id")), "l"),
               (esc(label_for("focal")), "l"),
               ('<button class="sort" type="button" data-sort="mwpa">%s'
                '<span class="sort-mark"></span></button>' % esc(label_for("mwpa")), "num"),
               # The bold zero in the header sits exactly on the painted rule
               # that runs the full height of this column.
               (null_head(), "z"),
               ('<button class="sort" type="button" data-sort="rounds">%s'
                '<span class="sort-mark"></span></button>' % esc(label_for("rounds")), "num")]
    rows = []
    for entry in sorted(site["matches"], key=lambda e: e["started_at"], reverse=True):
        kind, score_text = match_result(entry)
        shorts = [s for s in entry["focal"] if (s, entry["match_id"]) in tracker_by_match]
        combined = sum(tracker_by_match[(s, entry["match_id"])]["mwpa"] for s in shorts)
        # One chip per focal player, in that player's hue, carrying their own move in this
        # match. The hue is never the only carrier: the chip says the name.
        #
        # AND THE CHIPS ARE SEPARATED IN THE TEXT, not only in the box model. Joined edge to
        # edge this cell extracted as "MartinLutherKing -2.09%SN0RLAX +6.92%Trzzcko -7.52%" —
        # one player's value running into the next one's name on copy and in a screen reader,
        # where a margin does not exist. The separator is a real middot with real spaces
        # around it, so the cell reads as three chips in every channel a reader has.
        who = (" <span class=\"focal-sep\">%s</span> " % MIDDOT).join(
            '<span class="focal p-%s">%s %s</span>'
            % (esc(short), esc(name_of[short].split("#")[0]),
               signed("mwpa", tracker_by_match[(short, entry["match_id"])]["mwpa"]))
            for short in shorts)
        rows.append({
            "attrs": (' data-player="%s" data-date="%s" data-mwpa="%r" data-margin="%d" '
                      'data-rounds="%d" data-href="%sm/%s.html"'
                      % (esc(" ".join(shorts)), esc(entry["started_at"]), combined,
                         entry["score"][0] - entry["score"][1],
                         entry["rounds"], root, esc(entry["match_id"]))),
            "cells": [
                '<span class="%s">%s</span>' % (kind, esc(score_text)),
                '<a href="%sm/%s.html">%s</a>' % (
                    root, esc(entry["match_id"]),
                    esc("%s %s %s" % (entry["map"], MIDDOT, as_date(entry["started_at"])))),
                who,
                signed("mwpa", combined),
                mag_bar(combined, SCALE["match_mwpa"],
                        "%s %s" % (spoken("mwpa", combined), DICT["mwpa"]["unit"])),
                '<span class="num">%s</span>' % esc(count(entry["rounds"])),
            ],
        })
    return table(headers, rows, cls="tbl idx")


def build_index(site, out_dir, name_of):
    n_players = len(site["players"])
    tracker_by_match = {}
    for short, entries in site["tracker"].items():
        for row in entries:
            tracker_by_match[(short, row["match_id"])] = row
    exposure_html, _threshold, _top = exposure_rail(site)
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
                  % (esc(p["short"]), esc(p["short"]), esc(p["name"].split("#")[0]))
                  for p in site["players"]))

    body = body_from(
        "index.html",
        finding=esc(finding_headline(site)),
        standfirst=esc(finding_standfirst(site)),
        rail_heading=esc("The %s, ranked by %s"
                         % (spell(n_players), label_for("impact").lower())),
        rail_meta=esc("%s BCa interval, clustered on match %s axis %s to %s"
                      % (confidence(), MIDDOT, num("impact", -SCALE["impact"]),
                         num("impact", SCALE["impact"]))),
        standings=standings_rail(site, ""),
        scale_note=esc("The last two bars are on that same axis: the whole order is narrower "
                       "than one player's interval."),
        ladder_note=esc(ladder_front_note(site)),
        exposure_heading=esc("Exposure"),
        exposure=exposure_html,
        exposure_line=esc(exposure_line(site)),
        # The note the metric change left behind said "one line per player" and never said what
        # the line was. It is the headline recomputed after every match, which is the one
        # property that ties this figure to the rail above it: trzzcko's line ends at +6.4%
        # because that is what the rail prints. The mark under it is the same quantity at n=1.
        tracker_note=esc("The line is %s on the matches played so far, so it ends on the number "
                         "the rail above prints. The lollipop under it is that one match's %s, "
                         "on the same axis."
                         % (label_for("impact").lower(), label_for("mwpa"))),
        tracker_fallback=esc(
            "Drawn by quad-app.js. Without it, the same per-match numbers are in the index "
            "below."),
        matches_heading=esc("All %s matches, newest first" % count(n_rows)),
        # THE NOTE NAMES THE FOUR HEADINGS THAT SORT. It used to promise "any heading" over a
        # table where two of the six do not: the focal cell is a list of names in no order, and
        # the bar column's heading is the null mark. The labels are read out of meta.dict in the
        # order the headers are built, so a column that gains or loses a sort rewrites this
        # sentence rather than outliving it.
        matches_note=esc("Sort on %s, filter to one player in place, and step the rows with "
                         "j and k."
                         % and_list(label_for(key)
                                    for key in ("won", "match_id", "mwpa", "rounds"))),
        match_filters=filters,
        match_table=merged_index_table(site, "", name_of, tracker_by_match),
    )
    return render_page(
        out_dir / "index.html", site,
        # The tab and the link preview name the metric the page ranks on, not the estimator it
        # is rescaled from. "MWPA" said nothing about which of the two numbers the four are
        # sorted by, and the four are sorted by this one. The count is spelled, never typed.
        title="%s %s %s players, act %s" % (label_for("impact"), EM,
                                            spell(n_players), META["act"]),
        description=finding_line(site), page="index", root="", active="index",
        body=body, data=page_data("index", site))


# -------------------------------------------------------------------------- match page

def team_band(team_id, is_focal):
    """The Team column, as a band. One row per side instead of the same word ten times.

    The wash on the `<tbody>` is where the eye finds the break; this row is where the fact is,
    because a wash is colour and colour is never the only carrier. It says the two things the
    column said: which team, and whether it is the side the four played on.
    """
    return {"tbody": {
        "attrs": ' class="team-group%s" data-team="%s"'
                 % (" is-focal" if is_focal else "", esc(team_id)),
        "head": esc("%s %s %s" % (team_id, MIDDOT,
                                  "the side the four played on" if is_focal else "opponents")),
    }}


def match_players_table(match, root, focal_team):
    headers = [(esc(label_for("name")), ""),
               # Left-aligned, which it should always have been: it is a text column, and right
               # alignment gives ten portraits a ragged left edge — the opposite of a scan column.
               (esc(label_for("agent")), "l"), (esc(label_for("mwpa")), "num"),
               (null_head(), "z"),
               (esc(label_for("rounds")), "num"), ("K", "num"), ("D", "num"),
               ("A", "num"), (esc(label_for("damage")), "num")]
    groups = [("Who", 2), ("The instrument", 2), ("The box score", 5)]
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
                root, esc(row["short"]), esc(row["name"]))
        else:
            who = '<span class="anon">%s</span>' % esc(row["name"])
        rows.append({
            "attrs": ' data-team="%s"%s' % (esc(row["team"]),
                                            ' data-focal="1"' if row["is_focal"] else ""),
            "cells": [
                who,
                agent_cell(row["agent"], root),
                signed("mwpa", row["mwpa"]),
                mag_bar(row["mwpa"], SCALE["match_mwpa"],
                        "%s %s" % (spoken("mwpa", row["mwpa"]), DICT["mwpa"]["unit"])),
                '<span class="num">%s</span>' % esc(count(row["rounds"])),
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
                                    as_date(entry["started_at"]))
        label = ("%s %s" % (ARROWS[cls], text)) if arrow_first else ("%s %s" % (text, ARROWS[cls]))
        return '<a class="step %s" href="%sm/%s.html">%s</a>' % (
            cls, root, esc(entry["match_id"]), esc(label))

    return ('  <nav class="match-rail" aria-label="%s">%s'
            '<span class="where">%s</span>%s</nav>') % (
        esc("Previous and next match"), step(at - 1, "prev", True),
        esc("%s of %s" % (count(at + 1), count(len(order)))), step(at + 1, "next", False))


def collapse_mirrors(plays):
    """One trigger pull is one event, not two rows.

    A kill credit and the death debit it caused are the same instant of the same
    round at the same two probabilities, signed opposite. Ranking by |mwpa|
    surfaces both, so on most match pages two of the three biggest swings were
    one thing. The pair collapses to the row with the credit, which frees the
    slot for the next distinct event.
    """
    kept, seen = [], []
    for play in plays:
        mirror = None
        for other in kept:
            if (other["round_number"] == play["round_number"]
                    and abs(other["p_before"] - play["p_before"]) < 1e-12
                    and abs(other["p_after"] - play["p_after"]) < 1e-12
                    and other["mwpa"] * play["mwpa"] < 0):
                mirror = other
                break
        if mirror is None:
            kept.append(dict(play))
        else:
            mirror.setdefault("also", []).append(play)
        seen.append(play)
    return kept


def top_plays_html(match):
    out = []
    for rank, play in enumerate(collapse_mirrors(match["top_plays"]), start=1):
        out.append(
            '    <li class="play" data-type="%s">\n'
            '      <p class="play-what"><a href="#r%s">Round %s</a> %s %s %s %s</p>\n'
            '      <p class="play-num">%s <span class="unit">%s</span></p>\n'
            '      <p class="play-ctx">Round win probability %s to %s from the focal side, '
            'at %s%s%s, where the %s was %s.%s</p>\n'
            '    </li>' % (
                esc(play["type"]), esc(play["round_number"]), esc(count(play["round_number"])),
                MIDDOT, esc(play["name"]), MIDDOT, esc(label_for(play["type"]).lower()),
                signed("mwpa", play["mwpa"]), esc(DICT["mwpa"]["unit"]),
                esc(num("p_before", play["p_before"])), esc(num("p_after", play["p_after"])),
                esc(count(play["round_own"])), NDASH, esc(count(play["round_other"])),
                esc(label_for("leverage").lower()), esc(num("leverage", play["leverage"])),
                esc(" The same trigger pull is also the %s, %s to %s — one event, one row."
                    % (" and ".join(label_for(m["type"]).lower() for m in play["also"]),
                       ", ".join(m["name"] for m in play["also"]),
                       num("mwpa", play["also"][0]["mwpa"])))
                if play.get("also") else ""))
    return "\n".join(out)


def round_ledger_table(rnd, roster, buy_by_team, focal_team):
    headers = [(esc(label_for("name")), ""),
               (esc(label_for("kill_credit")), "num"), (esc(label_for("death_debit")), "num"),
               (esc(label_for("plant")), "num"), (esc(label_for("defuse")), "num"),
               (esc(label_for("alive_clock")), "num"), (esc(label_for("mwpa")), "num"),
               (null_head(), "z"), (esc(label_for("duel")), ""), (esc(label_for("weapon")), ""),
               (esc(label_for("buy_class")), ""), (esc(label_for("loadout")), "num"),
               (esc(label_for("credits")), "num"), ("K", "num"),
               (esc(label_for("damage")), "num")]
    by_puuid = dict((row["puuid"], row) for row in rnd["players"])
    rows = []
    band = None
    # `roster` already arrives team-first, which is what makes the bands one pass.
    for person in roster:
        if person["team"] != band:
            band = person["team"]
            rows.append(team_band(band, band == focal_team))
        row = by_puuid.get(person["puuid"])
        who = ('<span class="focal">%s</span>' % esc(person["name"]) if person["is_focal"]
               else '<span class="anon">%s</span>' % esc(person["name"]))
        if row is None:
            absent = '<span class="num none" title="not credited in this round">%s</span>' % EM
            rows.append({
                "attrs": ' class="absent" data-team="%s"' % esc(person["team"]),
                "cells": [who] + [absent] * 6 + [
                    '<span class="mag none"></span>',
                    absent, absent, absent, absent, absent, absent, absent],
            })
            continue
        # A round can carry several roles. The separator is a real space, so the
        # cell reads as two tags when the text is extracted, not as one word.
        duel = '<span class="duels">%s</span>' % (
            " ".join('<span class="tag" data-duel="%s">%s</span>' % (esc(t), esc(humanize(t)))
                     for t in row["duel"])
            or '<span class="tag none" title="no duel role in this round">%s</span>' % MIDDOT)
        weapon = (esc(row["weapon"]) if row["weapon"] else
                  '<span class="none" title="no round-start primary recorded">%s</span>' % EM)
        buy = buy_by_team.get(row["team"])
        rows.append({
            "attrs": ' data-team="%s"%s' % (esc(row["team"]),
                                            ' data-focal="1"' if person["is_focal"] else ""),
            "cells": [
                who,
                ledger_cell("kill_credit", row["kill_credit"]),
                ledger_cell("death_debit", row["death_debit"]),
                ledger_cell("plant", row["plant"]),
                ledger_cell("defuse", row["defuse"]),
                ledger_cell("alive_clock", row["alive_clock"]),
                signed("mwpa", row["mwpa"]),
                mag_bar(row["mwpa"], SCALE["round_mwpa"],
                        "%s %s" % (spoken("mwpa", row["mwpa"]), DICT["mwpa"]["unit"])),
                duel, weapon,
                esc(buy["class"]) if buy else
                '<span class="none" title="no buy recorded">%s</span>' % EM,
                '<span class="num">%s</span>' % esc(num("loadout", row["loadout"])),
                '<span class="num">%s</span>' % esc(num("credits", row["credits"])),
                '<span class="num">%s</span>' % esc(count(row["kills"])),
                '<span class="num">%s</span>' % esc(count(row["damage"])),
            ],
        })
    return table(headers, rows, cls="tbl round-ledger")


# `meta.dict.t` is milliseconds, `.0f`, because that is what the payload stores. A column of
# 19,078 and 32,127 is not a clock a reader reads, so the cell prints seconds to one decimal —
# the same conversion, to the same decimal, that quad-app.js `secs()` prints on the figure, so a
# node hovered on the curve and the same node in this table say the same time.
def secs(ms):
    return "%.1fs" % (ms / 1000.0)


# Who a node belongs to, for the three kinds that belong to nobody. Rule 1: an unattributed cell
# is an em dash and a reason, never a blank and never a name invented to fill it.
NOBODY = {
    "round_start": "the economy, before anyone acted",
    "clock": "the state ageing, split across the survivors",
    "terminal": "the model's own gap at the terminal, booked to a side",
}


def timeline_actor(node, name_by_puuid, short_by_puuid):
    puuid = node.get("actor")
    if not puuid:
        reason = NOBODY.get(node["kind"], "no player is credited for this event")
        return '<span class="none" title="%s">%s</span>' % (esc(reason), EM)
    name = name_by_puuid.get(puuid, puuid)
    short = short_by_puuid.get(puuid)
    if short:
        return '<span class="focal p-%s">%s</span>' % (esc(short), esc(name))
    return '<span class="anon">%s</span>' % esc(name)


def round_timeline_table(rnd, nodes, name_by_puuid, short_by_puuid):
    """The win probability curve for this one round, read down instead of across.

    The ledger beside it says what each of ten players was worth in the round; this says what
    happened in it, in order, and what each thing moved. Same numbers, and the `dp` on an action
    row is the same quantity the ledger credits — the curve's slope is the round's leverage.

    A clock node whose move is under `dp`'s own smallest printable magnitude is not a row. It is
    9,558 of the act's 27,108 nodes, 35%: drift the format cannot write, which would print as a
    column of `<0.1%` and nothing else. They stay inside the footer total, and the footer says
    how many of them there were, so the column still adds up to the line.
    """
    headers = [(esc(label_for("t")), "num"), (esc(label_for("kind")), ""),
               (esc(label_for("name")), ""), (esc(label_for("p")), "num"),
               (esc(label_for("dp")), "num"), (null_head(), "z")]
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
                mag_bar(node["dp"], SCALE["action_dp"],
                        "%s %s" % (spoken("dp", node["dp"]), DICT["dp"]["unit"])),
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
            '<td class="num">%s</td><td class="z">%s</td>'
            % (tally, esc(num("p", close)), signed("dp", total),
               mag_bar(total, SCALE["action_dp"],
                       "%s %s" % (spoken("dp", total), DICT["dp"]["unit"]))))
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


def round_panels_html(match, roster, focal_team, shape, name_by_puuid, short_by_puuid):
    panels = []
    for rnd in match["rounds"]:
        number = rnd["round_number"]
        won = rnd["winning_team"] == focal_team
        buy_by_team = dict((b["team_id"], b) for b in rnd["buy"])
        buys = "".join(
            '<li data-team="%s"><span class="team">%s</span> %s %s %s %s %s %s</li>' % (
                esc(b["team_id"]), esc(b["team_id"]), esc(b["side"]), MIDDOT,
                esc(label_for("loadout")).lower(), esc(num("loadout", b["loadout"])),
                MIDDOT, esc(b["class"]))
            for b in rnd["buy"])
        terminal = (esc(humanize(rnd["terminal_type"])) if rnd["terminal_type"] else
                    '<span class="none" title="no terminal recorded">%s</span>' % EM)
        panels.append(
            '  <section class="round-panel" id="r%s" data-round-panel="%s" '
            'data-outcome="%s" aria-labelledby="r%s-h">\n'
            '    <h3 id="r%s-h">Round %s <span class="round-outcome %s">%s</span></h3>\n'
            '    <p class="round-meta">%s wins by %s %s score entering %s%s%s %s %s %s, %s%s '
            'the act mean</p>\n'
            '    <ul class="buys">%s</ul>\n'
            '    <div class="scroll" tabindex="0" role="region" '
            'aria-label="Round %s, in order">%s</div>\n'
            '    <div class="scroll" tabindex="0" role="region" '
            'aria-label="Round %s ledger">%s</div>\n'
            '  </section>' % (
                esc(number), esc(number), "won" if won else "lost", esc(number), esc(number),
                esc(count(number)), "won" if won else "lost",
                "focal side won" if won else "focal side lost",
                esc(rnd["winning_team"]), terminal, MIDDOT,
                esc(count(rnd["own"])), NDASH, esc(count(rnd["other"])), MIDDOT,
                esc(label_for("leverage").lower()), esc(num("leverage", rnd["leverage"])),
                esc(num("li", rnd["li"])), "×", buys, esc(count(number)),
                round_timeline_table(rnd, shape["by_round"][number],
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


def curve_standfirst(match, shape, name_by_puuid):
    """One clause for what the line is, then this match's own largest move.

    The leverage-slope argument that used to sit here — why a vertical is readable as a number —
    was 273 characters identical above all 68 figures. It is on methods, once. What is left is
    the sentence only this page can write.
    """
    biggest = shape["biggest"]
    lead = "The focal side's match win probability, moving inside rounds rather than at their ends."
    if biggest is None:
        return "%s %s" % (esc(lead), esc("Nothing in this match moved it."))
    who = name_by_puuid.get(biggest.get("actor"))
    largest = (
        "Largest move: the %s in round %s%s, %s."
        % (esc(humanize(biggest.get("type") or "action")), esc(count(biggest["r"])),
           " by %s" % esc(who) if who else "", signed("dp", biggest["dp"])))
    return "%s %s" % (esc(lead), largest)


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
    names = and_list(row["name"].split("#")[0] for row in rows)
    if len(rows) == 1:
        return combined, "%s was worth %s of a match win" % (names, num("mwpa", combined))
    return combined, "%s were worth %s of a match win between them" % (
        names, num("mwpa", combined))


def build_match(site_entry, match, site, out_dir):
    focal_team = next(t["team_id"] for t in match["teams"] if t["focal"])
    other_team = next(t["team_id"] for t in match["teams"] if not t["focal"])
    own = next(t["rounds_won"] for t in match["teams"] if t["focal"])
    other = next(t["rounds_won"] for t in match["teams"] if not t["focal"])
    focal_names = [row["name"] for row in match["players"] if row["is_focal"]]
    date = as_date(match["started_at"])
    n_rounds = len(match["rounds"])
    title = "%s, %s%s%s" % (match["map"], count(own), NDASH, count(other))
    result = result_word(site_entry["match_id"], site_entry["won"])

    roster = sorted(match["players"], key=lambda r: (r["team"] != focal_team, -r["mwpa"]))
    shape = curve_nodes(match)
    name_by_puuid = dict((row["puuid"], row["name"]) for row in match["players"])
    short_by_puuid = dict((row["puuid"], row["short"])
                          for row in match["players"] if row["is_focal"])
    # The curve is walked once, before the panels, because each panel's timeline is that walk
    # sliced by round: two walks are two chances for the figure and the table to disagree.
    panels = round_panels_html(match, roster, focal_team, shape, name_by_puuid, short_by_puuid)

    fact_pairs = [
        (label_for("map"), esc(match["map"])),
        (label_for("started_at"), esc(date)),
        (label_for("rounds"), esc(count(n_rounds))),
        (label_for("score"), '<span class="num">%s%s%s</span> for %s' % (
            esc(count(own)), NDASH, esc(count(other)), esc(focal_team))),
        (label_for("won"), '<span class="%s">%s</span>' % (result, result)),
        (label_for("focal"), ", ".join(
            '<a href="../p/%s.html">%s</a>' % (esc(row["short"]), esc(row["name"]))
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
        figure_standfirst=curve_standfirst(match, shape, name_by_puuid),
        # The counts, and a link. The sentence that explained what a vertical is has gone: the
        # standfirst above the figure now shows the largest one instead of describing all of them.
        figure_caption=(
            '%s <a href="../methods.html#cav-%s">%s</a>' % (
                esc("%s nodes: %s."
                    % (count(len(shape["series"])),
                       ", ".join("%s %s" % (count(shape["counts"][kind]),
                                            label_for(KIND_KEY % kind).lower())
                                 for kind in KINDS))),
                esc(CAV_ON_PAGE["curve"]),
                esc("What the step at a round boundary is"))),
        figure_fallback=esc(
            "The curve is drawn by quad-app.js. Without it, every round below is still open."),
        players_heading=esc("All %s players" % spell(len(match["players"]))),
        players_note=prose(cav("opponents")),
        players_table=match_players_table(match, "../", focal_team),
        top_heading=esc("The %s biggest swings"
                        % spell(len(collapse_mirrors(match["top_plays"])))),
        top_note=esc("Single ledger rows, signed and unfiltered, so a death debit ranks here "
                     "as one."),
        top_plays=top_plays_html(match),
        rounds_heading=esc("Round by round"),
        rounds_note=esc("Selecting a round on the figure opens it here."),
        # The caveat itself is 297 characters and it sat above the round panels on all 68 pages.
        # What a reader needs here is that there is no utility column and that this is why; the
        # rest of it — four integers per player-match, null in every round record — is
        # methodology and is on methods, in full, behind this link.
        abilities_cav='%s <a href="../methods.html#cav-%s">%s</a>' % (
            esc("Abilities are absent from this data at every grain, so nothing below counts "
                "utility."),
            esc(CAV_ON_PAGE["abilities"]), esc("What that leaves out")),
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

def components_rail(player, short):
    """The six parts, and the headline they sum to, on one axis and one null.

    A table of six intervals is six zero lines that happen to line up. On the
    rail the two enormous rows that nearly cancel and the short span that
    survives them are one picture.

    IN IMPACT PER MATCH, which is the number at the top of this page. The last row of this rail
    is labelled as the headline and it used to print +0.313 per 100 rounds under a page whose
    headline reads +6.4% — a summary row in a unit that appears nowhere else on the page it
    summarises. Inside one player the rescale is a single positive constant, so this is the
    same picture it always was with the page's own unit written under it, and the six rows now
    sum to the big number rather than to a number the reader has to be told about. The headline
    row takes `impact_lo` and `impact_hi` straight from the payload: no arithmetic at all on
    the row the other six are checked against. See `component_impact`.
    """
    scale = SCALE["component_impact"]
    head = player["headline"]
    rows = []
    for key, cell in player["components"].items():
        definition = definition_of(key)
        point, lo, hi = component_impact(cell, head)
        rows.append(rail_row(
            '<span class="rail-who p-%s"%s>%s</span>'
            '<span class="rail-sub">%s %s %s</span>' % (
                esc(short), ' title="%s"' % esc(definition) if definition else "",
                esc(label_for(key)), esc(num("share", cell["share"])), MIDDOT,
                esc("of the ledger")),
            '<span class="p-%s">%s</span>' % (
                esc(short), rail_estimate(point, lo, hi, scale)),
            '%s<span class="rail-iv-text">%s %s</span>' % (
                signed("impact", point),
                esc(interval_text(lo, hi, "impact")),
                esc(null_verdict(lo <= 0 <= hi)))))
    rows.append(rail_row(
        '<span class="rail-who p-%s">%s</span>' % (esc(short), esc(label_for("impact"))),
        '<span class="p-%s">%s</span>' % (
            esc(short), rail_estimate(head["impact"], head["impact_lo"],
                                      head["impact_hi"], scale)),
        '%s<span class="rail-iv-text">%s %s</span>' % (
            signed("impact", head["impact"]),
            esc(interval_text(head["impact_lo"], head["impact_hi"], "impact")),
            esc(null_verdict(head["covers_zero"]))), cls="is-scale"))
    return rail_axis(scale, label_for("impact"), "impact") + "\n" + rail(rows)


def grains_of(player, matches):
    """The four grains of one player's act, on one baseline.

    Every other site's chart is in different units from its stat table, so a
    shared ruler would mean nothing. Here the curve IS the metric — an action's
    move on the line is exactly the number the ledger credits it — so one kill,
    the round it ended, the player's worst match and the player's whole act are
    four measurements of the same quantity at four grains, and they can be drawn
    against one another with no arithmetic asked of the reader.
    """
    puuid = player["puuid"]
    best, best_match = None, None
    for row in player["matches"]:
        match = matches[row["match_id"]]
        for node in match["wp_series"]:
            if node["kind"] != "action" or node.get("actor") != puuid:
                continue
            if best is None or abs(node["dp"]) > abs(best["dp"]):
                best, best_match = node, match
    grains = []
    if best is not None:
        grains.append(("grain_action", best["dp"],
                       "%s %s %s %s" % (humanize(best.get("type") or "action"), MIDDOT,
                                        best_match["map"], as_date(best_match["started_at"]))))
        credited = None
        for rnd in best_match["rounds"]:
            if rnd["round_number"] != best["r"]:
                continue
            for row in rnd["players"]:
                if row["puuid"] == puuid:
                    credited = row["mwpa"]
        if credited is not None:
            grains.append(("grain_round", credited,
                           "round %s of %s" % (count(best["r"]), best_match["map"])))
    worst = min(player["matches"], key=lambda r: r["mwpa"]) if player["matches"] else None
    if worst is not None:
        grains.append(("grain_match", worst["mwpa"],
                       "%s %s %s" % (worst["map"], MIDDOT, as_date(worst["started_at"]))))
    grains.append(("grain_act", player["headline"]["total"],
                   "%s matches" % count(player["headline"]["matches"])))
    return grains


def grain_rail(grains, short):
    scale = SCALE["grain"]
    rows = []
    for key, value, where in grains:
        rows.append(rail_row(
            '<span class="rail-who p-%s">%s</span><span class="rail-sub">%s</span>' % (
                esc(short), esc(label_for(key)), esc(where)),
            '<span class="p-%s">%s</span>' % (esc(short), rail_magnitude(value, scale, "hue")),
            signed(key, value)))
    # The axis is written in the format the four ROWS are written in. It took `rail_axis`'s old
    # default and printed +.3f ticks — the per-100-rounds format — over rows written +.4f, so
    # the 0.620 at the end of the axis and the +0.6200 on the act bar were the same number
    # twice. Same field, same format, one unit on the figure.
    return rail_axis(scale, DICT["grain_act"]["unit"], "grain_act") + "\n" + rail(rows)


def grain_sentence(grains, player):
    """What the four bars say, in one sentence and in the payload's own numbers."""
    by_key = dict((key, value) for key, value, _ in grains)
    if "grain_action" not in by_key or "grain_act" not in by_key:
        return "A grain that does not exist for this player is absent rather than zero."
    ratio = abs(by_key["grain_action"]) / abs(by_key["grain_act"]) if by_key["grain_act"] else 0
    head = player["headline"]
    # A SHARE ONLY EXISTS WHILE THE ACT IS THE BIGGER NUMBER. themarias's act nets to -1.47%
    # against a single kill of +11.47%, and the share clause wrote that as "779.9% of the act" --
    # arithmetically exact, and a percentage over one hundred of a denominator whose sign is the
    # other way round reads as a broken number rather than as the finding. Above 1.0 the sentence
    # says the multiple and says why the denominator is small, which is the thing worth reading:
    # a season that cancels to nearly nothing is what makes one action outweigh it.
    if ratio > 1.0:
        share_clause = ("one action is %s times the whole act, which cancels to nearly nothing"
                        % format(ratio, ".1f"))
    else:
        # The payload's own share format, not a literal: this line used to hardcode ".0%" and
        # was the only prose percentage on the site printing a whole number.
        share_clause = "%s of the act" % num("share", ratio)
    # And the last clause ties the longest bar to the headline above it: the act grain IS the
    # season total, so it is the numerator of impact per match and the reader can see the
    # division that produced the big number rather than being told about it.
    return ("One trigger pull came to %s against %s for all %s matches: %s, on one "
            "baseline. The act bar is what the headline divides — %s over %s matches is %s."
            % (num("grain_action", by_key["grain_action"]),
               num("grain_act", by_key["grain_act"]), count(head["matches"]),
               share_clause,
               num("grain_act", by_key["grain_act"]), count(head["matches"]),
               num("impact", head["impact"])))


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
TRACK_GUTTER = 82.0      # between the panels: they share x and nothing else. It grew by 16px
                         # this round to clear the placement row's empty badge slot, which sits
                         # one rung below the lowest division and must not touch it.
TRACK_HALF = 48.0        # the lower panel's half-height, at the payload's own axis
TRACK_FOOT = 78.0        # the tick row, and clearance under it


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
    matches = {row["match_id"]: row for row in player["matches"]}
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
    null_y = upper_bottom + TRACK_GUTTER + TRACK_HALF
    height = null_y + TRACK_FOOT
    plot = TRACK_W - pad_l - TRACK_PAD_R
    n = len(track)
    step_w = plot / n
    scale = SCALE["match_mwpa"]

    def cx(i):
        return pad_l + (i + 0.5) * step_w

    placement = sum(1 for row in track if row["state"] == "placement")
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

    # The lower panel: the same magnitude mark the rest of the site draws, on the same axis.
    for row in track:
        value = matches[row["match_id"]]["mwpa"]
        reach = min(abs(value) / scale, 1.0) * TRACK_HALF
        end = null_y - reach if value > 0 else null_y + reach
        marks.append('<line class="bar" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                     % (cx(row["i"]), cx(row["i"]), null_y, end))
        if abs(value) > scale:
            tip = null_y - TRACK_HALF - 5 if value > 0 else null_y + TRACK_HALF + 5
            marks.append('<line class="bar clipped" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" '
                         'stroke-dasharray="1 2"/>' % (cx(row["i"]), cx(row["i"]), end, tip))
    for sign in (1, -1):
        y = null_y - sign * TRACK_HALF
        marks.append('<line class="grid" x1="%.0f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                     % (pad_l, TRACK_W - TRACK_PAD_R, y, y))
        marks.append('<text class="axlab" x="%.0f" y="%.1f" text-anchor="end">%s</text>'
                     % (pad_l - 10, y + 3.5, esc(num("mwpa", sign * scale))))
    marks.append('<line class="null" x1="%.0f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                 % (pad_l, TRACK_W - TRACK_PAD_R, null_y, null_y))
    marks.append('<text class="axlab is-null" x="%.0f" y="%.1f" text-anchor="end">%s</text>'
                 % (pad_l - 10, null_y + 3.5, esc(label_for("null").upper())))

    # x ticks every five matches, and the final one only when it clears the previous.
    tick_y = null_y + TRACK_HALF + 24
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
    marks.append('<text class="paneltitle" x="%.0f" y="%.1f">%s</text>'
                 % (pad_l, upper_bottom + 62,
                    esc("%s this match, against the null" % label_for("mwpa"))))

    # The crosshair opens on the demotion, because a fall is the one step on this path that a
    # badge and a division count both delete. With no demotion it opens on the last match.
    opening = next((row["i"] for before, row in zip(ranked, ranked[1:])
                    if row["ordinal"] < before["ordinal"]), n - 1)
    marks.append('<line class="cross" data-track-cross x1="%.1f" x2="%.1f" y1="18" y2="%.1f"/>'
                 % (cx(opening), cx(opening), null_y + TRACK_HALF + 6))
    for row in track:
        marks.append('<rect class="hitbar" data-track-hit="%d" x="%.1f" y="18" width="%.1f" '
                     'height="%.1f"><title>%s</title></rect>'
                     % (row["i"], pad_l + row["i"] * step_w, step_w,
                        null_y + TRACK_HALF - 12, esc(track_line(player, row, plain=True))))

    label = ("Two panels on one axis of %s matches in the order they were played. Above, the "
             "division held at each match as a step path. Below, that match's %s as a bar from "
             "the null." % (count(n), label_for("mwpa")))
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
        ("", "%s %s %s" % (as_date(row["started_at"]), MIDDOT, row["map"]),
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
               (esc(label_for("agent")), ""), (esc(label_for("rounds")), "num"),
               (esc(label_for("won")), ""), (esc(label_for("mwpa")), "num"), (null_head(), "z"),
               (esc(label_for("attack_mwpa")), "num"), (esc(label_for("defense_mwpa")), "num")]
    rows = []
    for row in player["matches"]:
        result = result_word(row["match_id"], row["won"])
        rows.append([
            '<a href="../m/%s.html">%s</a>' % (esc(row["match_id"]),
                                               esc(as_date(row["started_at"]))),
            # badge=False: forty-five of these sixty rows are the same division. See rank_cell.
            esc(row["map"]), rank_cell(steps[row["match_id"]], "../", badge=False),
            esc(row["agent"]),
            '<span class="num">%s</span>' % esc(count(row["rounds"])),
            '<span class="%s">%s</span>' % (result, result),
            signed("mwpa", row["mwpa"]),
            mag_bar(row["mwpa"], SCALE["match_mwpa"],
                    "%s %s" % (spoken("mwpa", row["mwpa"]), DICT["mwpa"]["unit"])),
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


def interval_mark(cell, scale, matches_key="matches"):
    if one_cluster(cell, matches_key):
        return interval_bar(None, None, None, scale, "one match, so there is no interval")
    return interval_bar(cell["rate"], cell["lo"], cell["hi"], scale,
                        "%s, interval %s" % (num("rate", cell["rate"]),
                                             interval_text(cell["lo"], cell["hi"])))


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
    # The dimension's own label, not the payload's field name for the column
    # that holds it. "Cell" is what `key` is called in the contract; "Map" is
    # what the column says.
    # `l` on the weapon column, and only on it. The header of a breakdown's first column is
    # left-aligned everywhere on this site and its cells are right-aligned, which is survivable
    # for four words and wrong for a picture: right-aligned rows of a fixed-width chip give the
    # chips a ragged LEFT edge, which is the opposite of the only reason to have them. `l` is the
    # table system's own modifier — the same one the Tier column uses — and a header class travels
    # down its column, so the header and its cells agree for the first time in this table.
    headers = [(esc(label_for(dimension)), "l" if dimension == "weapon" else ""),
               (esc(label_for("rounds")), "num"),
               (esc(label_for("matches")), "num"),
               (esc(label_for("exposure")), "num"), (esc(label_for("rate")), "num"),
               ("%s interval" % confidence(), "num"),
               (null_head(), "z"), (esc(label_for("total")), "num")]
    rows = []
    for cell in cells:
        rows.append({
            "attrs": ' data-key="%s"%s' % (esc(cell["key"]),
                                           ' data-thin="1"' if cell["thin"] else ""),
            "cells": [
                breakdown_key_cell(dimension, cell["key"], root),
                '<span class="num">%s</span>' % esc(count(cell["rounds"])),
                '<span class="num">%s</span>' % esc(count(cell["matches"])),
                exposure_cell(cell),
                signed("rate", cell["rate"]),
                interval_cell(cell),
                interval_mark(cell, SCALE["rate"]),
                signed("total", cell["total"]),
            ],
        })
    return table(headers, rows, cls="tbl breakdown p-%s" % short)


def breakdowns_html(player, short, root):
    # ONE SENTENCE PER BLOCK, and only where the block cannot be read without it. Two payload
    # caveats used to print here in full; both are on methods. `by side` keeps a one-line
    # version because its two intervals are unreadable without the number that explains them,
    # and that number is `gate.side_split_rounds` rather than a literal in this file.
    note_for = {
        "side": "The split needs about %s rounds at this credit variance; the act has %s."
                % (count(GATE["side_split_rounds"]), count(META["rounds"])),
        "weapon": "The weapon is the one held at round start; the short tails are grouped "
                  "into Other.",
    }
    out = []
    for key in BREAKDOWN_ORDER:
        cells = player["breakdowns"][key]
        note = ('\n    <p class="note">%s</p>' % esc(note_for[key])) if key in note_for else ""
        out.append(
            '  <section class="breakdown-block" id="by-%s" aria-labelledby="by-%s-h">\n'
            '    <h3 id="by-%s-h">By %s</h3>\n'
            '    <p class="note">%s</p>\n'
            '    <div class="scroll" tabindex="0" role="region" aria-label="%s">%s</div>%s\n'
            '  </section>' % (
                esc(key), esc(key), esc(key), esc(label_for(key).lower()),
                esc("%s %s with rounds; a cell with none is not a row."
                    % (spell(len(cells)).capitalize(),
                       "cell" if len(cells) == 1 else "cells")),
                # R1: five breakdown scrollers per player page had no tabindex, no role and no
                # label, so a keyboard-only reader could not reach the columns they hide.
                esc("%s by %s, with its interval" % (label_for("mwpa"), label_for(key).lower())),
                breakdown_table(cells, key, short, root), note))
    return "\n".join(out)


def breakdown_unit_note(player):
    """Why these five tables are not in the unit at the top of the page, with the deciding number.

    The division would RUN — every breakdown cell carries a match count — and it would be wrong.
    The thinnest cell on martin's page is `Other` weapons at 1.2 rounds of a match against his
    act's 21.2, so its match count is a count of matches the cell APPEARED in and not an
    exposure. Per 100 rounds is the honest denominator for a slice of a match, and the column
    header says so on every one of these tables. The thin marker keeps its one clause here
    because it is the only legend the marker has.
    """
    head = player["headline"]
    thinnest = min((cell["rounds"] / float(cell["matches"]), key, cell["key"])
                   for key in BREAKDOWN_ORDER for cell in player["breakdowns"][key])
    per_match, dimension, name = thinnest
    return ("In %s, not per match: %s is %s rounds of a match against this player's %s, so a "
            "cell's match count is not its exposure. A cell under %s rounds is marked thin."
            % (label_for("rate"), name, format(per_match, ".1f"),
               format(head["rounds"] / float(head["matches"]), ".1f"),
               count(GATE["rate_floor_marker_rounds"])))


def synergy_table(player, short):
    headers = [(esc(label_for("partner_name")), ""), (esc(label_for("shared_matches")), "num"),
               (esc(label_for("shared_rounds")), "num"), (esc(label_for("rate")), "num"),
               (esc(label_for("exposure")), "num"),
               ("%s interval" % confidence(), "num"),
               (null_head(), "z")]
    rows = []
    for cell in player["synergy"]:
        empty = cell["rate"] is None
        reason = "never shared a round with this partner in this act"
        rows.append({
            "attrs": ' data-partner="%s"%s' % (esc(cell["partner_short"]),
                                               ' data-empty="1"' if empty else ""),
            "cells": [
                '<a href="%s.html">%s</a>' % (esc(cell["partner_short"]),
                                              esc(cell["partner_name"])),
                '<span class="num">%s</span>' % esc(count(cell["shared_matches"])),
                '<span class="num">%s</span>' % esc(count(cell["shared_rounds"])),
                signed("rate", cell["rate"], absent_reason=reason),
                ('<span class="marker empty">no shared rounds</span>' if empty
                 else exposure_cell(cell, "shared_rounds", "shared_matches")),
                ('<span class="num none" title="%s">%s</span>' % (esc(reason), EM) if empty
                 else interval_cell(cell, "shared_matches")),
                (interval_bar(None, None, None, SCALE["rate"], reason) if empty
                 else interval_mark(cell, SCALE["rate"], "shared_matches")),
            ],
        })
    return table(headers, rows, cls="tbl synergy p-%s" % short)


def components_sentence(player):
    """Whether the credit types reconcile to the headline, in the headline's own unit."""
    head = player["headline"]
    rows = player["components"]
    total = sum(component_impact(cell, head)[0] for cell in rows.values())
    gap = total - head["impact"]
    # Anything under half of what `impact`'s own format can write is rounding, and the format is
    # the field's rather than a literal: the reconciliation is checked at display precision.
    if abs(gap) < smallest_printable("impact") / 2.0:
        return ("The %s credit types sum to %s per match, which is the headline exactly."
                % (spell(len(rows)), num("impact", total)))
    return ("The %s credit types sum to %s per match against a headline of %s, a gap of %s."
            % (spell(len(rows)), num("impact", total), num("impact", head["impact"]),
               num("impact", gap)))


def build_player(site, player, entry, out_dir, matches):
    head = player["headline"]
    short = player["short"]
    grains = grains_of(player, matches)
    headline_block = (
        '    <p class="big">%s <span class="unit">%s</span></p>\n'
        '    <p class="ival-text">%s interval %s</p>\n'
        '    <p class="note">%s</p>\n'
        '    <dl class="facts">%s</dl>'
    ) % (
        # THE HEADLINE IS IMPACT PER MATCH. Same estimate, same BCa endpoints, divided by the
        # matches this player was in: +6.4% reads as six extra wins per hundred matches, which
        # the per-100-rounds rate it is rescaled from does not.
        signed("impact", head["impact"]), esc(label_for("impact").lower()),
        esc(confidence()),
        esc(interval_text(head["impact_lo"], head["impact_hi"], "impact")),
        esc(covers_zero_sentence(head)),
        facts([
            (label_for("total"), '%s <span class="unit">%s</span>' % (
                signed("total", head["total"]), esc(DICT["total"]["unit"]))),
            (label_for("matches"), '<span class="num">%s</span>' % esc(count(head["matches"]))),
            (label_for("rounds"), '<span class="num">%s</span>' % esc(count(head["rounds"]))),
            (label_for("rank"), '<span class="num">%s of %s</span>' % (
                esc(count(entry["rank"])), esc(count(len(site["players"]))))),
        ]))

    body = body_from(
        "player.html", root="../", title=esc(player["name"]),
        # The lede names the metric, the rank and the exposure, and stops. The null verdict was
        # added here and taken straight back out: it is four lines above the note that already
        # says it WITH the round count, and a verdict stated twice in four lines is the
        # repeated caveat this round is cutting everywhere else.
        headline_sentence=esc(
            "Ranked %s of %s by %s, over %s matches of act %s." % (
                count(entry["rank"]), count(len(site["players"])),
                label_for("impact").lower(), count(head["matches"]), META["act"])),
        headline=headline_block,
        grains_heading=esc("One player, one baseline, %s grains" % spell(len(grains))),
        grains_note=esc(grain_sentence(grains, player)),
        grains=grain_rail(grains, short),
        components_heading=esc("The %s parts, and the headline they sum to"
                               % spell(len(player["components"]))),
        components_note=esc(components_sentence(player)),
        components_rail=components_rail(player, short),
        ladder_heading=esc("The one thing that moved"),
        ladder_note=esc(ladder_sentence(player)),
        ladder_figure=rank_trajectory(player, short),
        # The full caveat is on methods. What has to survive next to the figure is the number
        # that stops the ladder being read as a second opinion on the rating.
        ladder_cav=esc("The ladder is a second instrument: across %s ranked lobbies it "
                       "correlates with that match's %s at r = %s."
                       % (count(META["ladder"]["n"]), label_for("mwpa"),
                          format(META["ladder"]["r_mwpa"], "+.3f"))),
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
        title="%s %s %s %s, act %s" % (player["name"], EM, num("impact", head["impact"]),
                                       label_for("impact").lower(), META["act"]),
        description="%s: %s %s over %s matches of act %s, %s interval %s, which %s." % (
            player["name"], num("impact", head["impact"]), label_for("impact").lower(),
            count(head["matches"]), META["act"], confidence(),
            interval_text(head["impact_lo"], head["impact_hi"], "impact"),
            null_verdict(head["covers_zero"])),
        page="player", root="../", active=player["short"], body=body,
        # A player page carries division badges on the trajectory axis and a weapon silhouette on
        # every `by weapon` row, so it gets the control that removes them. It had no imagery and
        # no control before this round.
        data=page_data("player", site, player=player), has_icons=True)


# ------------------------------------------------------------------------ methods page

def glossary_html():
    tiers = []
    for entry in DICT.values():
        if entry["tier"] not in tiers:
            tiers.append(entry["tier"])
    blocks = []
    for tier in tiers:
        rows = []
        for key, entry in DICT.items():
            if entry["tier"] != tier:
                continue
            rows.append([
                '<code>%s</code>' % esc(key),
                esc(entry["label"]),
                prose(entry["definition"]),
                esc(entry["unit"]) if entry["unit"] else
                '<span class="none" title="not a measured quantity">%s</span>' % EM,
                '<code>%s</code>' % esc(entry["format"]),
            ])
        blocks.append(
            '  <section class="tier" id="tier-%s" aria-labelledby="tier-%s-h">\n'
            '    <h3 id="tier-%s-h">%s <span class="count">%s fields</span></h3>\n'
            '    <div class="scroll" tabindex="0" role="region" aria-label="%s">%s</div>\n'
            '  </section>' % (
                esc(tier), esc(tier), esc(tier), esc(tier.capitalize()), esc(count(len(rows))),
                esc("%s fields, with their definitions" % tier.capitalize()),
                table([("Field", ""), ("Label", ""), ("Definition", ""), ("Unit", ""),
                       ("Format", "")], rows, cls="tbl glossary")))
    return "\n".join(blocks)


def impact_arithmetic_line(site):
    """The division, done in the act's own two extremes so the denominator is visible working.

    trzzcko and snorlax are 0.021 of season total apart across the whole act and 7.5 times
    apart on matches played, so the pair IS the argument for the denominator: one of them was
    worth about as much in eight matches as the other was in sixty.
    """
    players = site["players"]
    top = max(players, key=lambda p: p["impact"])
    busiest = max(players, key=lambda p: p["matches"])

    def who(entry):
        return entry["name"].split("#")[0]

    if top is busiest:
        return ("One division: a player's season total across the act, over the matches they "
                "played. %s's %s over %s matches is %s."
                % (who(top), num("total", top["total"]), count(top["matches"]),
                   num("impact", top["impact"])))
    return ("One division, and it happens once: a player's season total of %s across the act, "
            "over the matches they played. %s's %s over %s matches is %s. %s's %s over %s "
            "matches is %s. The two totals are %s apart; the two exposures are %s times apart, "
            "and it is the second number that separates the two headlines."
            % (label_for("mwpa"), who(top), num("total", top["total"]),
               count(top["matches"]), num("impact", top["impact"]),
               who(busiest), num("total", busiest["total"]), count(busiest["matches"]),
               num("impact", busiest["impact"]),
               magnitude("total", abs(top["total"] - busiest["total"])),
               format(busiest["matches"] / float(top["matches"]), ".1f")))


def impact_invariance_line(site):
    """Why there is no second bootstrap, with the spread of the constant that makes it true."""
    per_match = [p["rounds"] / float(p["matches"]) for p in site["players"]]
    return ("Inside one player the rescale is a positive constant — rounds per match runs %s to "
            "%s across the four — and BCa respects a monotone transformation, so the interval "
            "endpoints are the same endpoints and `covers_zero` is the same flag. There is no "
            "second bootstrap: the low end of an impact interval is the low end of the rate "
            "interval times that constant, and nothing was resampled again to get it."
            % (format(min(per_match), ".1f"), format(max(per_match), ".1f")))


def impact_reading_line(site):
    """How to read the headline, in the act's own largest one, ending on what it cannot say.

    It does NOT repeat "six extra wins per hundred matches": that is the second sentence of the
    definition at the top of this page, and the reading a reader still lacks after it is the
    multiplication back out — the headline times the matches behind it IS the season total.
    """
    players = site["players"]
    top = max(players, key=lambda p: p["impact"])
    covering = [p for p in players if p["covers_zero"]]
    if not covering:
        verdict = "No interval covers the null"
    elif len(covering) == len(players):
        verdict = "All %s intervals cover the null" % spell(len(players))
    else:
        verdict = "%s of the %s intervals cover the null" % (
            spell(len(covering)).capitalize(), spell(len(players)))
    return ("A percentage of a match win is a count of match wins, so the headline multiplies "
            "back out: %s across the %s matches behind it is %s of one match win, which is %s's "
            "season total. %s, so read a sign as a direction this much play cannot confirm."
            % (num("impact", top["impact"]), count(top["matches"]),
               num("total", top["total"]), top["name"].split("#")[0], verdict))


def build_methods(site, out_dir):
    scope_pairs = [
        ("Act", esc(META["act"])),
        ("Release", "<code>%s</code>" % esc(META["release"])),
        ("Built", esc(META["generated_at"])),
        (label_for("matches"), '<span class="num">%s</span>' % esc(count(META["matches"]))),
        (label_for("rounds"), '<span class="num">%s</span>' % esc(count(META["rounds"]))),
        ("Round-players", '<span class="num">%s</span>' % esc(count(META["round_players"]))),
        ("Distinct players", '<span class="num">%s</span>' % esc(count(META["players"]))),
        ("Bootstrap replicates", '<span class="num">%s</span>' % esc(count(META["bootstrap"]))),
        ("Seed", '<span class="num">%s</span>' % esc(META["seed"])),
        (label_for("confidence"), '<span class="num">%s</span>' % esc(confidence())),
        (label_for("mean_leverage"), '<span class="num">%s</span>'
         % esc(num("mean_leverage", META["mean_leverage"]))),
        ("Thin-cell marker", esc("below %s rounds" % count(GATE["rate_floor_marker_rounds"]))),
        ("Rate suppression", esc("off, the floor is %s rounds"
                                 % count(GATE["rate_floor_rounds"]))),
        # The front page used to carry this number in a paragraph above its own rail. The rail
        # still draws the rule and its one line still names the threshold; the fact itself
        # belongs in the scope list, with every other gate the build reads.
        ("Exposure threshold", esc("%s rounds"
                                   % count(GATE["exposure_threshold_rounds"]))),
        # "on" alone stopped being the whole fact when the ranking key changed: the gate says
        # players are ranked, and the reader's next question is on what. The separator that was
        # here rendered "on · by impact per match", which is a list of two things and not a
        # sentence.
        ("Ranking", esc("on, by %s" % label_for("impact").lower())
         if GATE["rank_players"] else esc("off")),
    ]
    cavs = "".join(
        '    <div id="cav-%s"><dt>%s</dt><dd>%s</dd></div>\n' % (
            esc(item["id"]), esc(humanize(item["id"])), prose(item["text"]))
        for item in META["cav"])

    body = body_from(
        "methods.html",
        definition=prose(DICT["mwpa"]["definition"]),
        leverage_line=esc(
            "The mean round in this act carries a marginal match value of %s, and the index "
            "printed beside a round's leverage is that round divided by this mean."
            % magnitude("mean_leverage", META["mean_leverage"])),
        unit_line=esc(
            "A season total is the product summed over the act, in %s." %
            DICT["total"]["unit"]),
        impact_heading=esc(label_for("impact")),
        impact_line=prose(DICT["impact"]["definition"]),
        impact_arithmetic=prose(impact_arithmetic_line(site)),
        impact_why=esc(
            "%s is the estimator's own denominator, and it is not one anybody plays. A match "
            "is what these four queue for and what a win is scored in, so the headline divides "
            "by matches. The order of the four is the same in either denominator, so the "
            "choice changes no finding on this site — only whether the number can be read "
            "without arithmetic." % label_for("rate")),
        impact_invariance=prose(impact_invariance_line(site)),
        impact_read=esc(impact_reading_line(site)),
        rate_line=esc(
            "%s is the same measurement in the other denominator: the season total divided by "
            "the rounds the player was credited in, times 100. It survives here, and on the "
            "five breakdown tables and the synergy table of a player page, where it is the "
            "only correct unit — those cells hold a slice of a match rather than a match, so "
            "their match count is a count of matches the cell appeared in and not an exposure "
            "to divide by. The component rail is the one cut that does convert, because its "
            "rounds and its matches are the headline's own, and it is drawn per match."
            % label_for("rate")),
        interval_line=esc(
            "Every interval here is a %s BCa bootstrap over %s replicates at seed %s, "
            "resampling whole matches so that the rounds of one match move together." % (
                confidence(), count(META["bootstrap"]), META["seed"])),
        thin_line=prose(cav("thin")),
        single_match_line=prose(cav("single_match")),
        abilities_cav=prose(cav("abilities")),
        causal_cav=prose(cav("causal")),
        pseudonym_cav=prose(cav("opponents")),
        bar_line=esc(
            "A bar fills against a fixed axis, never against the largest row on the screen, "
            "so the same value is the same width on every page. The axis is the %sth "
            "percentile of that quantity across the whole act: %s for a round ledger row, "
            "%s for a match, %s for a rate, %s for one credit type per match, and %s for one "
            "action's move on the win probability curve. The END that ran past its axis is "
            "the end that is flagged, so a bar which stopped at the axis cannot be read as "
            "one that stopped on its own. Three axes are not percentiles and here is why. A "
            "mark on the win probability curve has no number printed beside it, so a mark "
            "that clamped would simply be wrong: the gate an action must clear before it "
            "gets a mark of its own is the %sth percentile, %s, and only the act's top "
            "hundredth of moves are drawn as marks at all. The four grain bars on a "
            "player page share ONE ruler with each other and with the season total, at %s, "
            "which is the act's own maximum rather than a percentile, because a figure whose "
            "largest bar clipped would be making exactly the comparison it exists to refuse. "
            "And the front page's own rail runs to %s, the maximum of the twelve headline "
            "numbers: four players, three endpoints each, every one of them on screen at "
            "once. The %sth percentile of those twelve is %s and would clip two of the four "
            "intervals — on the one figure whose entire subject is how wide they are."
            % (
                count(SCALE["percentile"]), magnitude("mwpa", SCALE["round_mwpa"]),
                magnitude("mwpa", SCALE["match_mwpa"]), magnitude("rate", SCALE["rate"]),
                magnitude("impact", SCALE["component_impact"]),
                magnitude("dp", SCALE["action_dp"]),
                count(SCALE["marker_percentile"]), magnitude("dp", SCALE["marker_gate"]),
                magnitude("mwpa", SCALE["grain"]), magnitude("impact", SCALE["impact"]),
                count(SCALE["percentile"]),
                magnitude("impact", percentile(
                    [abs(v) for row in site["players"]
                     for v in (row["impact"], row["impact_lo"], row["impact_hi"])],
                    BAR_PERCENTILE)))),
        scope_facts=facts(scope_pairs),
        caveats_heading=esc("The %s caveats that come with these numbers"
                            % count(len(META["cav"]))),
        cavs=cavs,
        glossary_heading=esc("The %s fields the payload defines" % count(len(DICT))),
        glossary_note=esc(
            "A few round-grain columns carry no dictionary entry and are labelled by this "
            "build rather than by the payload: %s." % ", ".join(sorted(
                FALLBACK_LABEL[k].lower() for k in FALLBACK_LABEL if k not in DICT))),
        glossary=glossary_html())

    return render_page(
        out_dir / "methods.html", site,
        title="Methods %s %s, act %s" % (EM, label_for("impact").lower(), META["act"]),
        description="What %s is, why the denominator is matches rather than rounds, how to "
                    "read an interval that covers zero, and the %s caveats attached to these "
                    "numbers." % (label_for("impact").lower(), count(len(META["cav"]))),
        page="methods", root="", active="methods", body=body,
        data={"page": "methods", "meta": META, "scale": SCALE})


# ------------------------------------------------------------------------------- build

def main():
    global META, DICT, GATE, CAV, SCALE, ASSETS, ART, RESULT
    site, players, matches = load_payload()
    META = site["meta"]
    DICT = META["dict"]
    GATE = META["gate"]
    ASSETS = META.get("assets", {})
    ART = css_px("--icon-art", "--icon-slot", "--weapon-art-w", "--sp-2")

    CAV = dict((item["id"], item["text"]) for item in META["cav"])
    SCALE = bar_scales(site, players, matches)
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

    name_of = dict((p["short"], p["name"]) for p in site["players"])
    written = []
    sizes = {}

    sizes["index"] = build_index(site, HERE, name_of)
    written.append(HERE / "index.html")

    match_bytes = 0
    for entry in site["matches"]:
        match = matches[entry["match_id"]]
        match_bytes += build_match(entry, match, site, HERE)
        written.append(HERE / "m" / ("%s.html" % entry["match_id"]))
    sizes["match"] = match_bytes

    player_bytes = 0
    for entry in site["players"]:
        player_bytes += build_player(site, players[entry["short"]], entry, HERE, matches)
        written.append(HERE / "p" / ("%s.html" % entry["short"]))
    sizes["player"] = player_bytes

    sizes["methods"] = build_methods(site, HERE)
    written.append(HERE / "methods.html")

    (HERE / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    expected = META["matches"] + len(site["players"]) + 2
    if len(written) != expected:
        raise AssertionError("wrote %d pages against %d expected" % (len(written), expected))
    missing = [str(p) for p in written if not p.exists()]
    if missing:
        raise AssertionError("pages missing after write: %s" % ", ".join(missing))

    total = sum(p.stat().st_size for p in written) + (HERE / "robots.txt").stat().st_size
    print("pages       %d  (%d match, %d player, index, methods)"
          % (len(written), META["matches"], len(site["players"])))
    print("match pages %d rounds, %d round-players inlined"
          % (total_rounds, total_round_players))
    print("curve       %d nodes inlined  (%s)"
          % (total_nodes, ", ".join("%s %d" % (kind, node_kinds[kind]) for kind in KINDS)))
    print("bytes       index %d, methods %d, players %d, matches %d, total on disk %d"
          % (sizes["index"], sizes["methods"], sizes["player"], sizes["match"], total))
    print("bar axes    " + ", ".join("%s %.4f" % (k, v) for k, v in sorted(SCALE.items())
                                     if k != "percentile")
          + " (p%d)" % SCALE["percentile"])


if __name__ == "__main__":
    main()
