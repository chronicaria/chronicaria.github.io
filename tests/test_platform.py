"""Tests for the W10 platform layer in scripts/smp/core.py.

Covers the nav IA, page shell (footer / meta / config payload), table_html
column groups + sticky year detection, tr_html data-tid tagging, the skill
legend, and register_site_meta determinism.
"""

import json
import os
import re
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import core  # noqa: E402


def _teams():
    return [
        {"tid": 0, "abbrev": "DUR", "region": "Durham", "name": "Destroyers"},
        {"tid": 3, "abbrev": "QNS", "region": "Queens", "name": "Pigeons"},
    ]


def _cells(n=4):
    return "".join(core.td(i) for i in range(n))


class TestNavHtml(unittest.TestCase):
    def test_final_ia_dropdowns_present(self):
        nav = core.nav_html(_teams(), root="")
        for label in ["Home", "Schedule", "Players", "Teams", "League", "Tools"]:
            self.assertIn(f">{label}<", nav.replace("</summary>", "<"))
        for href in ["rivalries.html", "classics.html", "wrapped.html", "lineup.html", "simulator.html", "trade.html", "compare.html"]:
            self.assertIn(f'href="{href}"', nav)

    def test_active_child_marks_dropdown_parent(self):
        nav = core.nav_html(_teams(), root="", active="rivalries")
        league = nav.split("<summary>League</summary>")[0].rsplit("<details", 1)[1]
        self.assertIn("active", league)
        self.assertIn('aria-current="page"', nav)

    def test_header_controls_rendered(self):
        nav = core.nav_html(_teams(), root="")
        self.assertIn("data-my-team-picker", nav)
        self.assertIn("data-theme-toggle", nav)
        self.assertIn('<option value="3">QNS — Queens Pigeons</option>', nav)
        # Three theme icons, one per state.
        for cls in ["tt-auto", "tt-dark", "tt-light"]:
            self.assertIn(cls, nav)

    def test_team_links_keep_data_tid(self):
        nav = core.nav_html(_teams(), root="../")
        self.assertIn('data-tid="0"', nav)
        self.assertIn('data-abbrev="DUR"', nav)


class TestPageHtml(unittest.TestCase):
    def setUp(self):
        core.SITE_META.update({"season": 2031, "phase": 0, "games": 479, "export": "2031_preseason.json"})

    def test_footer_and_meta(self):
        html = core.page_html("Records", "<h1>Records</h1>", _teams())
        self.assertIn('<footer class="site-footer">', html)
        self.assertIn("Season 2031 · Preseason", html)
        self.assertIn("Generated from 2031_preseason.json · 479 games", html)
        self.assertIn('<meta property="og:title" content="Records — SMP Basketball League">', html)
        self.assertIn('<meta property="og:site_name" content="SMP Basketball League">', html)
        self.assertIn('<meta property="og:type" content="website">', html)
        self.assertIn('<meta name="description"', html)

    def test_custom_description(self):
        html = core.page_html("Draft", "<p>x</p>", _teams(), description='All picks & "grades"')
        self.assertIn('content="All picks &amp; &quot;grades&quot;"', html)

    def test_no_wall_clock_dates(self):
        html = core.page_html("Home", "<p>x</p>", _teams())
        # Determinism: nothing resembling a generated-on timestamp.
        self.assertNotRegex(html, r"Generated (on|at)")
        self.assertNotIn("datetime.now", html)

    def test_config_payload(self):
        html = core.page_html("Home", "<p>x</p>", _teams())
        match = re.search(r'<script type="application/json" id="smp-config" data-team-colors>(.*?)</script>', html, re.S)
        self.assertIsNotNone(match)
        config = json.loads(match.group(1).replace("<\\/", "</"))
        self.assertEqual(config["season"], 2031)
        self.assertEqual(config["phaseLabel"], "Preseason")
        self.assertEqual(config["teamColors"]["0"]["abbrev"], "DUR")
        for key in ("primary", "secondary", "chart", "on"):
            self.assertRegex(config["teamColors"]["0"][key], r"^#[0-9A-Fa-f]{6}$")
        page_urls = {p["url"] for p in config["pages"]}
        self.assertIn("rivalries.html", page_urls)
        self.assertIn("index.html", page_urls)
        self.assertEqual(config["skills"]["Di"], "Interior defender")

    def test_deterministic(self):
        first = core.page_html("Home", "<p>x</p>", _teams())
        second = core.page_html("Home", "<p>x</p>", _teams())
        self.assertEqual(first, second)

    def test_footer_without_export_name(self):
        core.SITE_META["export"] = None
        html = core.page_html("Home", "<p>x</p>", _teams())
        self.assertIn("Generated from the league export · 479 games", html)


class TestRegisterSiteMeta(unittest.TestCase):
    def test_records_games_phase_season(self):
        data = {
            "gameAttributes": {"season": 2031, "phase": 3},
            "games": [{"season": 2031}, {"season": 2031}],
        }
        core.register_site_meta(data, "day9.json")
        self.assertEqual(core.SITE_META["games"], 2)
        self.assertEqual(core.SITE_META["phase"], 3)
        self.assertEqual(core.SITE_META["season"], 2031)
        self.assertEqual(core.SITE_META["export"], "day9.json")
        # A later call without a filename resets it (no stale carryover).
        core.register_site_meta(data)
        self.assertIsNone(core.SITE_META["export"])

    def test_normalize_positions_registers_meta(self):
        data = {"gameAttributes": {"season": 2030, "phase": 8}, "games": [], "players": []}
        core.normalize_positions(data)
        self.assertEqual(core.SITE_META["phase"], 8)
        self.assertEqual(core.SITE_META["games"], 0)


class TestTableHtml(unittest.TestCase):
    def test_plain_table_unchanged_shape(self):
        html = core.table_html(["Player", "PTS"], [_cells(2)], table_id="t1")
        self.assertIn("data-sortable", html)
        self.assertNotIn("data-colgroup", html)
        self.assertNotIn("sticky-col2", html)

    def test_colgroups_annotate_and_toggle(self):
        html = core.table_html(
            ["Player", "PTS", "TRB", "TS%"],
            [_cells(4), _cells(4)],
            table_id="t2",
            colgroups=[("Base", [1, 2]), ("Advanced", [3])],
            default_colgroup="Base",
        )
        self.assertIn('data-colgroup-toggle="t2"', html)
        self.assertIn('data-colgroup-default="base"', html)
        # All + the two groups; Base preselected.
        self.assertIn('data-colgroup="all"', html)
        self.assertIn('class="cg-btn active" data-colgroup="base" aria-pressed="true"', html)
        self.assertIn('data-colgroup="advanced"', html)
        # th and td of column 1 tagged; column 0 untouched.
        self.assertEqual(html.count('<th data-colgroup="base"'), 2)
        self.assertEqual(html.count('<td data-colgroup="base"'), 4)
        self.assertEqual(html.count('<td data-colgroup="advanced"'), 2)
        first_cell = html.split("<tbody>")[1].lstrip().splitlines()[0]
        self.assertTrue("<td>0</td>" in first_cell or "<td >0" in first_cell)

    def test_colgroups_shared_column(self):
        html = core.table_html(
            ["Player", "PTS", "TS%"],
            [_cells(3)],
            table_id="t3",
            colgroups=[("Base", [1]), ("Key", [1, 2])],
        )
        self.assertIn('data-colgroup="base key"', html)

    def test_colgroups_skipped_without_table_id(self):
        html = core.table_html(["A", "B"], [_cells(2)], colgroups=[("G", [1])])
        self.assertNotIn("data-colgroup", html)

    def test_sticky_year_autodetect(self):
        auto = core.table_html(["Season", "Team", "GP"], [_cells(3)], table_id="t4")
        self.assertIn('class="sticky-col2"', auto)
        off = core.table_html(["Player", "Team", "GP"], [_cells(3)], table_id="t5")
        self.assertNotIn("sticky-col2", off)
        forced = core.table_html(["Player", "Team", "GP"], [_cells(3)], table_id="t6", sticky_year=True)
        self.assertIn("sticky-col2", forced)
        suppressed = core.table_html(["Season", "Team", "GP"], [_cells(3)], table_id="t7", sticky_year=False)
        self.assertNotIn("sticky-col2", suppressed)

    def test_prewrapped_rows_still_annotated(self):
        row = core.tr_html(_cells(2), tid=3)
        html = core.table_html(["Player", "PTS"], [row], table_id="t8", colgroups=[("Base", [1])])
        self.assertIn('data-tid="3"', html)
        self.assertIn('<td data-colgroup="base"', html)


class TestTrHtml(unittest.TestCase):
    def test_data_tid_and_class(self):
        self.assertEqual(core.tr_html("<td>x</td>", tid=4), '<tr data-tid="4"><td>x</td></tr>')
        self.assertEqual(core.tr_html(["<td>x</td>"], cls="avg-row"), '<tr class="avg-row"><td>x</td></tr>')
        self.assertEqual(core.tr_html("<td>x</td>"), "<tr><td>x</td></tr>")


class TestSkillLegend(unittest.TestCase):
    def test_labels_cover_export_codes(self):
        for code in ["3", "A", "B", "Di", "Dp", "Po", "Ps", "R", "V"]:
            self.assertIn(code, core.SKILL_LABELS)

    def test_player_link_titles_mini_skills(self):
        player = {
            "pid": 1, "firstName": "Test", "lastName": "Player", "tid": 0,
            "ratings": [{"season": 2031, "skills": ["Di", "3"]}],
        }
        html = core.player_link(player, root="")
        self.assertIn('<span class="mini-skill" title="Interior defender">Di</span>', html)
        self.assertIn('<span class="mini-skill" title="Three-point shooter">3</span>', html)

    def test_glossary_has_fpts(self):
        self.assertIn("FPTS", core.GLOSSARY)


if __name__ == "__main__":
    unittest.main()
