"""Tests for scripts/smp/pages/home.py (phase-aware home page, W4).

Covers the phase composition switch, the odds-river chart (including a
synthetic multi-point ledger and the graceful single-point state), the
fantasy-leaders card, the four-factors quadrant scatter, and the
offseason-digest event selection.
"""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.core import SITE_META  # noqa: E402
from smp.identity import team_chart_color  # noqa: E402
from smp.pages import home  # noqa: E402


def _team(tid, abbrev, season=2031, stats=None, seasons=None):
    return {
        "tid": tid,
        "cid": 0,
        "abbrev": abbrev,
        "region": f"Region{tid}",
        "name": f"Name{tid}",
        "seasons": seasons if seasons is not None else [{"season": season, "won": 0, "lost": 0, "cid": 0}],
        "stats": stats or [],
    }


def _team_stat_row(season, gp=45, pts=5000, opp_pts=4900):
    return {
        "season": season, "playoffs": False, "gp": gp,
        "fg": 1800, "fga": 3900, "tp": 550, "tpa": 1500, "ft": 850, "fta": 1080,
        "orb": 500, "drb": 1450, "tov": 700, "pts": pts,
        "oppFg": 1780, "oppFga": 3880, "oppTp": 540, "oppFt": 840, "oppFta": 1075,
        "oppOrb": 470, "oppDrb": 1430, "oppTov": 680, "oppPts": opp_pts,
    }


def _snapshot(season, phase, games_played, odds_by_tid):
    return {
        "season": season,
        "phase": phase,
        "games_played": games_played,
        "teams": {
            str(tid): {"po": po, "finals": po / 2, "title": po / 4, "proj_w": 22.0, "proj_l": 23.0}
            for tid, po in odds_by_tid.items()
        },
    }


class TestHomePhaseKind(unittest.TestCase):
    def _data(self, phase, games=None):
        return {"gameAttributes": {"season": 2031, "phase": phase}, "games": games or []}

    def _completed_game(self, season):
        return {
            "gid": 1, "season": season, "day": 3, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "players": []},
                {"tid": 1, "pts": 90, "players": []},
            ],
        }

    def test_preseason_phase(self):
        self.assertEqual(home.home_phase_kind(self._data(0), 2031), "preseason")

    def test_regular_phase_without_games_composes_as_preseason(self):
        self.assertEqual(home.home_phase_kind(self._data(1), 2031), "preseason")

    def test_regular_phase_with_games(self):
        data = self._data(1, games=[self._completed_game(2031)])
        self.assertEqual(home.home_phase_kind(data, 2031), "regular")

    def test_playoffs_phase(self):
        data = self._data(3, games=[self._completed_game(2031)])
        self.assertEqual(home.home_phase_kind(data, 2031), "playoffs")

    def test_offseason_phases(self):
        for phase in (4, 5, 6, 7, 8):
            self.assertEqual(home.home_phase_kind(self._data(phase), 2031), "offseason")

    def test_last_completed_season(self):
        data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": [self._completed_game(2030)]}
        self.assertEqual(home.last_completed_season(data, 2031), 2030)


class TestOddsRiverCard(unittest.TestCase):
    def setUp(self):
        self.teams = [_team(0, "AAA"), _team(1, "BBB")]
        self.data = {"gameAttributes": {"season": 2031, "phase": 1}, "games": []}

    def test_multi_point_ledger_draws_team_lines(self):
        history = [
            _snapshot(2031, 0, 0, {0: 0.60, 1: 0.40}),
            _snapshot(2031, 1, 10, {0: 0.70, 1: 0.30}),
            _snapshot(2031, 1, 20, {0: 0.80, 1: 0.20}),
        ]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        self.assertIn("<polyline", html)
        self.assertEqual(html.count('class="oddsr-line"'), 2)  # one line per team
        # Snapshot ticks: unique phases stay bare, repeats get numbered.
        self.assertIn(">Pre</text>", html)
        self.assertIn(">RS 1</text>", html)
        self.assertIn(">RS 2</text>", html)
        # Team-identity chart colors drive the strokes.
        self.assertIn(team_chart_color(0), html)
        self.assertIn(team_chart_color(1), html)
        # Hover plumbing (payload + crosshair + tooltip) is emitted.
        self.assertIn('id="oddsr-data"', html)
        self.assertIn("data-oddsr", html)
        self.assertIn("data-oddsr-hline", html)
        self.assertIn("data-oddsr-tooltip", html)

    def test_missing_snapshot_breaks_line_instead_of_faking_data(self):
        history = [
            _snapshot(2031, 0, 0, {0: 0.60, 1: 0.40}),
            _snapshot(2031, 1, 10, {0: 0.70}),  # team 1 missing mid-season
            _snapshot(2031, 1, 20, {0: 0.80, 1: 0.20}),
        ]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        # Team 0 keeps its full line; team 1 gets no bridged polyline.
        self.assertEqual(html.count('class="oddsr-line"'), 1)
        self.assertIn('class="oddsr-dot"', html)

    def test_single_point_ledger_renders_graceful_state(self):
        history = [_snapshot(2031, 0, 0, {0: 0.55, 1: 0.45})]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        self.assertNotIn("<polyline", html)
        self.assertIn("one snapshot so far", html)
        self.assertIn('class="oddsr-dot"', html)
        self.assertIn(">AAA</text>", html)  # labels sit next to the dots
        self.assertNotIn("data-oddsr", html)  # no hover plumbing for one point
        self.assertNotIn('id="oddsr-data"', html)

    def test_no_snapshots_for_season_renders_nothing(self):
        history = [_snapshot(2030, 1, 10, {0: 0.5, 1: 0.5})]
        self.assertEqual(home.odds_river_card(self.data, self.teams, 2031, history=history), "")


class TestFantasyLeadersCard(unittest.TestCase):
    def _player(self, pid, name, tid, season, gp, stat_overrides=None):
        stat = {
            "season": season, "playoffs": False, "tid": tid, "gp": gp,
            "pts": 20 * gp, "fg": 8 * gp, "fga": 16 * gp, "tp": 2 * gp,
            "ft": 2 * gp, "fta": 3 * gp, "trb": 8 * gp, "ast": 5 * gp,
            "stl": 1 * gp, "blk": 1 * gp, "tov": 2 * gp, "min": 30 * gp,
        }
        stat.update(stat_overrides or {})
        first, last = name.split(" ", 1)
        return {
            "pid": pid, "firstName": first, "lastName": last, "tid": tid,
            "retiredYear": None, "born": {"year": 2000},
            "ratings": [{"season": season, "pos": "G", "ovr": 60, "pot": 65}],
            "stats": [stat],
        }

    def setUp(self):
        self.teams = [_team(0, "AAA", stats=[_team_stat_row(2030)]),
                      _team(1, "BBB", stats=[_team_stat_row(2030)])]
        self.data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": []}

    def test_orders_by_fantasy_points_per_game_with_min_gp_filter(self):
        star = self._player(1, "Big Star", 0, 2030, 40, {"pts": 30 * 40, "ast": 8 * 40})
        role = self._player(2, "Role Guy", 1, 2030, 40)
        cameo = self._player(3, "Small Sample", 1, 2030, 5, {"pts": 60 * 5})  # under min GP
        html = home.fantasy_leaders_card(self.data, [star, role, cameo], self.teams, 2030, 2031)
        self.assertIn("Big Star", html)
        self.assertIn("Role Guy", html)
        self.assertNotIn("Small Sample", html)
        self.assertLess(html.find("Big Star"), html.find("Role Guy"))
        # Preseason fallback is labeled honestly; the stat is plain FPTS.
        self.assertIn("2030 · last completed season", html)
        self.assertIn("FPTS/G", html)
        self.assertNotIn("ESPN", html)

    def test_fantasy_scoring_value_is_integer(self):
        # Per game: pts20 fg8 fga16 tp2 ft2 fta3 trb8 ast5 stl1 blk1 tov2
        # = 20 + 2 + 16 - 16 + 2 - 3 + 8 + 10 + 4 + 4 - 4 = 43 FPTS/G, shown as an int
        player = self._player(1, "Known Line", 0, 2030, 40)
        html = home.fantasy_leaders_card(self.data, [player], self.teams, 2030, 2031)
        self.assertIn(">43</span>", html)
        self.assertNotIn(">43.0</span>", html)

    def test_no_team_games_renders_nothing(self):
        teams = [_team(0, "AAA"), _team(1, "BBB")]  # no 2030 stat rows
        player = self._player(1, "Someone Good", 0, 2030, 40)
        self.assertEqual(home.fantasy_leaders_card(self.data, [player], teams, 2030, 2031), "")


class TestFourFactorsScatter(unittest.TestCase):
    def test_renders_dots_labels_and_quadrants(self):
        teams = [
            _team(0, "AAA", stats=[_team_stat_row(2030, pts=5100, opp_pts=4800)]),
            _team(1, "BBB", stats=[_team_stat_row(2030, pts=4800, opp_pts=5100)]),
        ]
        data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": []}
        html = home.four_factors_scatter_card(data, teams, 2030, 2031)
        self.assertIn('class="ff4-chart"', html)
        self.assertEqual(html.count('class="ff4-dot"'), 2)
        self.assertIn(">AAA</text>", html)
        self.assertIn(">BBB</text>", html)
        self.assertIn(team_chart_color(0), html)
        self.assertIn("+ offense · + defense", html)
        self.assertIn("2030 · last completed season", html)  # honest fallback label
        self.assertIn('href="teams/region0-name0-0.html"', html)

    def test_no_played_games_renders_nothing(self):
        teams = [_team(0, "AAA", stats=[_team_stat_row(2031, gp=0)]),
                 _team(1, "BBB", stats=[_team_stat_row(2031, gp=0)])]
        data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": []}
        self.assertEqual(home.four_factors_scatter_card(data, teams, 2031, 2031), "")


class TestOffseasonEvents(unittest.TestCase):
    def test_boundary_keeps_offseason_moves_and_drops_in_season_ones(self):
        data = {
            "events": [
                {"type": "freeAgent", "season": 2030, "eid": 5},               # in-season signing
                {"type": "trade", "season": 2030, "eid": 6, "phase": 1},       # deadline trade
                {"type": "trade", "season": 2030, "eid": 7, "phase": 5},       # offseason trade (phase)
                {"type": "playoffs", "season": 2030, "eid": 10},               # boundary marker
                {"type": "freeAgent", "season": 2030, "eid": 12},              # offseason signing
                {"type": "draft", "season": 2030, "eid": 3},                   # draft is always offseason
                {"type": "retired", "season": 2030, "eid": 4},                 # retirement news is excluded
                {"type": "hallOfFame", "season": 2030, "eid": 8},              # HoF news is excluded
                {"type": "freeAgent", "season": 2029, "eid": 99},              # wrong season
                {"type": "injured", "season": 2030, "eid": 13},                # not a transaction
            ]
        }
        eids = [e["eid"] for e in home.offseason_events(data, 2030)]
        self.assertEqual(eids, [3, 7, 12])


class TestPreseasonComposition(unittest.TestCase):
    """The dash-wall acceptance test: a preseason render must not emit the
    zero-data standings/team-stats/award-sentiment tables, and the stake chips
    must link to team pages instead of '#'."""

    def setUp(self):
        SITE_META.pop("sim", None)
        SITE_META["prev_ranks"] = None
        self._real_league_sim = home.league_sim
        # simulate_league runs 10,000 Monte Carlo sims — stub it for the
        # composition test (its own behavior is covered elsewhere).
        home.league_sim = lambda data, teams, season: {
            "teams": {
                0: {"po": 0.6, "finals": 0.3, "champ": 0.2, "seeds": [0.5, 0.5], "proj_w": 24.0, "games_left": 45},
                1: {"po": 0.4, "finals": 0.2, "champ": 0.1, "seeds": [0.5, 0.5], "proj_w": 21.0, "games_left": 45},
            },
            "stakes": [{"gid": "proj-1", "day": 1, "home_tid": 0, "away_tid": 1,
                        "home_swing": 0.12, "away_swing": 0.10}],
            "day": 1,
            "fresh": True,
        }

    def tearDown(self):
        home.league_sim = self._real_league_sim
        SITE_META.pop("sim", None)

    def _data(self):
        game = {
            "gid": 1, "season": 2030, "day": 3, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "ptsQtrs": [25, 25, 25, 25], "players": []},
                {"tid": 1, "pts": 90, "ptsQtrs": [22, 23, 22, 23], "players": []},
            ],
        }
        return {
            "gameAttributes": {"season": 2031, "phase": 0, "numGames": 45,
                               "confs": [{"cid": 0, "name": "League"}]},
            "games": [game],
            "events": [
                {"type": "playoffs", "season": 2030, "eid": 10, "text": "Race note."},
                {"type": "freeAgent", "season": 2030, "eid": 12, "pids": [1], "tids": [0],
                 "contract": {"amount": 30000, "exp": 2033}},
            ],
            "players": [],
            "awards": [],
        }

    def test_preseason_page_has_no_dash_walls_and_no_dead_links(self):
        teams = [
            _team(0, "AAA", stats=[_team_stat_row(2030), _team_stat_row(2031, gp=0)],
                  seasons=[{"season": 2030, "won": 30, "lost": 15, "cid": 0},
                           {"season": 2031, "won": 0, "lost": 0, "cid": 0}]),
            _team(1, "BBB", stats=[_team_stat_row(2030), _team_stat_row(2031, gp=0)],
                  seasons=[{"season": 2030, "won": 15, "lost": 30, "cid": 0},
                           {"season": 2031, "won": 0, "lost": 0, "cid": 0}]),
        ]
        html = home.render_home_page(self._data(), teams, [], 2031, 2026, odds_history=[])
        # Phase banner replaces the zero-data cards with one line of copy.
        self.assertIn("hm-banner", html)
        self.assertIn("season hasn't tipped off yet", html)
        # The dash walls are gone.
        self.assertNotIn('id="standings-', html)
        self.assertNotIn('id="team-stats"', html)
        self.assertNotIn('id="award-sentiment"', html)
        # Stake chips link to team pages, never '#'.
        self.assertNotIn('href="#"', html)
        self.assertIn("hm-stake-team", html)
        self.assertIn('href="teams/region0-name0-0.html"', html)
        # The offseason digest replaces the empty in-season news feed.
        self.assertIn("Offseason Digest", html)
        # No hollow side-column markup when cards are missing.
        self.assertNotIn('<div class="home-side"></div>', html)


class TestPlayoffOddsPrecision(unittest.TestCase):
    """PO% / Finals% / Title% show one decimal; per-seed cells stay integers."""

    def setUp(self):
        self._real_league_sim = home.league_sim
        home.league_sim = lambda data, teams, season: {
            "teams": {
                0: {"po": 0.745, "finals": 0.475, "champ": 0.301, "seeds": [0.62, 0.38], "proj_w": 24.0, "games_left": 40},
                1: {"po": 0.2551, "finals": 0.0004, "champ": 0.0, "seeds": [0.38, 0.62], "proj_w": 21.0, "games_left": 40},
            },
            "stakes": [], "day": 5, "fresh": False,
        }

    def tearDown(self):
        home.league_sim = self._real_league_sim

    def test_headline_odds_have_one_decimal(self):
        teams = [_team(0, "AAA"), _team(1, "BBB")]
        data = {"gameAttributes": {"season": 2031, "phase": 1, "numGames": 45}, "games": []}
        html = home.playoff_odds_card(data, teams, 2031)
        self.assertIn("74.5%", html)
        self.assertIn("47.5%", html)
        self.assertIn("30.1%", html)
        self.assertIn("25.5%", html)     # rounds to one decimal, not an int
        self.assertIn("&lt;0.1%", html)  # trace odds floor, not "0.0%"
        self.assertIn(">—<", html)       # exactly zero stays a dash
        # Seed-distribution cells stay integers.
        self.assertIn(">62<", html)
        self.assertIn(">38<", html)
        self.assertNotIn(">62.0<", html)

    def test_odds_pct_formatter(self):
        self.assertEqual(home._odds_pct(0.0), "—")
        self.assertEqual(home._odds_pct(0.04), "&lt;0.1%")
        self.assertEqual(home._odds_pct(0.05), "0.1%")
        self.assertEqual(home._odds_pct(74.5), "74.5%")
        self.assertEqual(home._odds_pct(100.0), "100.0%")


class TestHomeFinancesTable(unittest.TestCase):
    """The home finance table reads the ledger defensively and shows the
    budget/committed/surplus columns (new finance semantics)."""

    def setUp(self):
        self._real_fin = home.compute_league_finances
        self._real_sim = home.league_sim
        home.league_sim = lambda data, teams, season: {"teams": {}}
        self.ledger = {
            "teams": {
                0: {"won": 30, "lost": 15, "revenue_proj": 340000, "net_proj": 330000,
                    "committed_next": 290000, "surplus_next": 40000},
                1: {"won": 15, "lost": 30, "revenue_proj": 260000, "net_proj": 270000,
                    "committed_next": 305000, "surplus_next": -35000},
            }
        }
        home.compute_league_finances = lambda *args: self.ledger

    def tearDown(self):
        home.compute_league_finances = self._real_fin
        home.league_sim = self._real_sim

    def _teams(self):
        return [_team(0, "AAA"), _team(1, "BBB")]

    def test_new_columns_and_color_coded_surplus(self):
        html = home.home_finances_table({}, self._teams(), [], 2031)
        self.assertIn('id="home-finances"', html)
        for header in ("Proj revenue", "2032 budget", "2032 committed payroll", "Surplus"):
            self.assertIn(header, html)
        # No cash-on-hand language in the new model.
        self.assertNotIn("Cash on Hand", html)
        self.assertNotIn("bankroll", html)
        # Signed, color-coded surplus.
        self.assertIn('<span class="delta-up">+$40M</span>', html)
        self.assertIn('<span class="delta-down">-$35M</span>', html)
        # Sorted by budget, biggest first.
        self.assertLess(html.find("Region0"), html.find("Region1"))

    def test_falls_back_to_legacy_ledger_keys(self):
        # Old finance.py shape (rev_proj / luxtax / tax_share / payroll_next): the
        # table must still compose sane budget and surplus figures.
        self.ledger = {
            "teams": {
                0: {"won": 20, "lost": 25, "rev_proj": 320000, "luxtax": 10000,
                    "tax_share": 0.0, "adj": 0.0, "payroll_next": 280000},
            }
        }
        html = home.home_finances_table({}, [_team(0, "AAA")], [], 2031)
        self.assertIn("$320M", html)                                # projected revenue
        self.assertIn("$310M", html)                                # budget = 320 − 10 tax
        self.assertIn("$280M", html)                                # committed payroll
        self.assertIn('<span class="delta-up">+$30M</span>', html)  # surplus = 310 − 280


class TestHomeColumns(unittest.TestCase):
    def test_empty_side_collapses_wrapper(self):
        out = home._home_columns(["<section>a</section>"], ["", ""])
        self.assertNotIn("home-side", out)
        self.assertNotIn("home-columns", out)
        self.assertIn("<section>a</section>", out)

    def test_both_sides_render_columns(self):
        out = home._home_columns(["<section>a</section>"], ["<section>b</section>"])
        self.assertIn("home-columns", out)
        self.assertIn("home-main", out)
        self.assertIn("home-side", out)


if __name__ == "__main__":
    unittest.main()
