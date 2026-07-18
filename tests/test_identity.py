"""Tests for scripts/smp/identity.py (TEAM_IDENTITY registry + SVG builders)."""

import os
import sys
import unittest
import xml.etree.ElementTree as ET


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import identity  # noqa: E402


_HEX = frozenset("0123456789ABCDEFabcdef")


def _is_hex_color(value):
    return (
        isinstance(value, str)
        and value.startswith("#")
        and len(value) == 7
        and all(c in _HEX for c in value[1:])
    )


def _parse_svg(markup):
    """Round-trip through an XML parser; raises if the SVG is malformed."""
    return ET.fromstring(markup)


class TestRegistry(unittest.TestCase):
    def test_registry_complete_for_tids_0_through_9(self):
        for tid in range(10):
            self.assertIn(tid, identity.TEAM_IDENTITY)
            ident = identity.TEAM_IDENTITY[tid]
            for key in ("primary", "secondary", "chart", "on_primary"):
                self.assertTrue(
                    _is_hex_color(ident[key]),
                    "tid %d key %s not a hex color: %r" % (tid, key, ident[key]),
                )
            self.assertEqual(len(ident["abbrev"]), 3)
            self.assertEqual(ident["abbrev"], ident["abbrev"].upper())

    def test_expected_abbrevs(self):
        expected = ["DUR", "ROC", "CAM", "QNS", "TOR", "GOO", "WAL", "STO", "MAN", "ITH"]
        got = [identity.TEAM_IDENTITY[t]["abbrev"] for t in range(10)]
        self.assertEqual(got, expected)

    def test_unknown_tid_falls_back_without_crashing(self):
        for tid in (10, 99, -1, None):
            ident = identity.TEAM_IDENTITY[tid]
            self.assertEqual(ident, identity.FALLBACK_IDENTITY)
            self.assertTrue(_is_hex_color(ident["primary"]))
        # .get is fallback-aware too
        self.assertEqual(identity.TEAM_IDENTITY.get(42), identity.FALLBACK_IDENTITY)
        # fallback lookups must not pollute the registry
        self.assertNotIn(99, identity.TEAM_IDENTITY)
        self.assertEqual(sorted(dict.keys(identity.TEAM_IDENTITY)), list(range(10)))

    def test_fallback_copies_are_independent(self):
        a = identity.team_identity(1234)
        a["primary"] = "#000000"
        self.assertEqual(identity.team_identity(1234)["primary"],
                         identity.FALLBACK_IDENTITY["primary"])


class TestValidation(unittest.TestCase):
    def test_validate_identity_passes(self):
        self.assertTrue(identity.validate_identity())

    def test_on_primary_contrast_meets_aa(self):
        for tid in range(10):
            ident = identity.TEAM_IDENTITY[tid]
            ratio = identity.contrast_ratio(ident["on_primary"], ident["primary"])
            self.assertGreaterEqual(
                ratio, 4.5, "tid %d contrast %.2f below AA" % (tid, ratio)
            )

    def test_chart_colors_pairwise_distinct(self):
        charts = [identity.TEAM_IDENTITY[t]["chart"] for t in range(10)]
        self.assertEqual(len(set(charts)), 10)
        for i in range(10):
            for j in range(i + 1, 10):
                d = identity._chart_distance(charts[i], charts[j])
                self.assertGreaterEqual(
                    d,
                    identity.CHART_DISTINCT_MIN,
                    "tids %d/%d chart colors too close (%.1f)" % (i, j, d),
                )

    def test_contrast_ratio_sanity(self):
        self.assertAlmostEqual(identity.contrast_ratio("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(identity.contrast_ratio("#123456", "#123456"), 1.0, places=3)


class TestCssVars(unittest.TestCase):
    def test_team_css_vars_fragment(self):
        frag = identity.team_css_vars(0)
        ident = identity.TEAM_IDENTITY[0]
        for var, key in (
            ("--team-primary", "primary"),
            ("--team-secondary", "secondary"),
            ("--team-on-primary", "on_primary"),
            ("--team-chart", "chart"),
        ):
            self.assertIn("%s:%s" % (var, ident[key]), frag)
        self.assertNotIn('"', frag)  # must be safe inside style="..."

    def test_team_css_vars_fallback_tid(self):
        frag = identity.team_css_vars(777)
        self.assertIn("--team-primary:%s" % identity.FALLBACK_IDENTITY["primary"], frag)

    def test_team_chart_color(self):
        self.assertEqual(identity.team_chart_color(7), identity.TEAM_IDENTITY[7]["chart"])
        self.assertEqual(identity.team_chart_color(500), identity.FALLBACK_IDENTITY["chart"])


class TestMonogram(unittest.TestCase):
    def test_monogram_is_valid_svg_with_team_vars(self):
        svg = identity.monogram_svg("DUR", 0)
        root = _parse_svg(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("--team-primary:#1B2440", svg)
        self.assertIn("var(--team-primary)", svg)
        self.assertIn("var(--team-on-primary)", svg)
        self.assertIn(">DUR</text>", svg)
        self.assertIn('viewBox="0 0 64 64"', svg)
        # sized by CSS class, not fixed pixels
        self.assertNotIn("width=", svg.split(">")[0])
        self.assertIn('class="monogram"', svg)

    def test_monogram_jersey_number_and_class(self):
        svg = identity.monogram_svg("AB", 4, jersey_number=23, css_class="monogram monogram--lg")
        _parse_svg(svg)
        self.assertIn(">23</text>", svg)
        self.assertIn('class="monogram monogram--lg"', svg)
        # no jersey bubble when omitted
        plain = identity.monogram_svg("AB", 4)
        self.assertNotIn(">23</text>", plain)

    def test_monogram_escapes_and_truncates(self):
        svg = identity.monogram_svg('<x>&"', 1)
        _parse_svg(svg)
        self.assertNotIn("<x>", svg)

    def test_monogram_fallback_tid_and_empty_text(self):
        svg = identity.monogram_svg("", 999)
        _parse_svg(svg)
        self.assertIn(">?</text>", svg)
        self.assertIn("--team-primary:%s" % identity.FALLBACK_IDENTITY["primary"], svg)


class TestCrests(unittest.TestCase):
    def test_all_twelve_plus_kinds_render_valid_svg(self):
        self.assertGreaterEqual(len(identity.CREST_KINDS), 12)
        for kind in identity.CREST_KINDS:
            svg = identity.crest_svg(kind)
            root = _parse_svg(svg)
            self.assertTrue(root.tag.endswith("svg"))
            self.assertIn("currentColor", svg)
            self.assertIn('class="crest crest-%s"' % kind, svg)
            self.assertIn('viewBox="0 0 24 24"', svg)
            self.assertIn("aria-label=", svg)
            # tintable: no hardcoded hex colors inside crests
            self.assertNotIn("#", svg.replace("&#", ""))

    def test_crest_custom_class(self):
        svg = identity.crest_svg("mvp", css_class="crest crest--gold")
        self.assertIn('class="crest crest--gold"', svg)

    def test_unknown_crest_kind_raises(self):
        with self.assertRaises(KeyError):
            identity.crest_svg("nope")


if __name__ == "__main__":
    unittest.main()
