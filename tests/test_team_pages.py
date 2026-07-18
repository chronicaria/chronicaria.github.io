"""W2 regression tests: team-page immersion, Starting Five, banners, depth
chart, scoring share, four factors, honest preseason states, Franchise Arc."""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import league_generator as lg  # noqa: E402
from smp.pages import team as team_page  # noqa: E402


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


def _player(pid, first, last, tid=0, exp=2030, amount=10000, ovr=60, pos="PG", stats=None):
    return {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 2000},
        "contract": {"exp": exp, "amount": amount},
        "ratings": [{"season": 2029, "pos": pos, "ovr": ovr, "pot": ovr + 2}],
        "stats": stats or [],
    }


def _stat_row(season=2030, gp=40, pts=800, fga=600, ast=200, tid=0):
    return {"season": season, "playoffs": False, "gp": gp, "min": gp * 30.0,
            "pts": pts, "fga": fga, "fg": int(fga * 0.5), "fta": 100, "ft": 80,
            "tp": 50, "tpa": 140, "ast": ast, "orb": 40, "drb": 160,
            "stl": 30, "blk": 20, "tov": 80, "tid": tid}


def _playoff_series(season, home_tid, away_tid, home_won, away_won):
    return {
        "season": season,
        "series": [
            [  # semifinal round (2 matchups so expected rounds = 2)
                {"home": {"tid": home_tid, "won": 4}, "away": {"tid": 8, "won": 0}},
                {"home": {"tid": away_tid, "won": 4}, "away": {"tid": 9, "won": 1}},
            ],
            [  # final
                {"home": {"tid": home_tid, "won": home_won},
                 "away": {"tid": away_tid, "won": away_won}},
            ],
        ],
    }


class TestChampionsAndBanners(unittest.TestCase):
    def test_decided_final_yields_champion_and_runner_up(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2030, 2, 4, 4, 0)]}
        champs = team_page.champions_by_season(data)
        self.assertEqual(champs[2030]["champ"], 2)
        self.assertEqual(champs[2030]["runner_up"], 4)
        self.assertEqual(champs[2030]["rounds"], 2)

    def test_current_season_final_in_progress_is_not_a_title(self):
        # 2-1 in a best-of-7 (default games-to-win 4) must not mint a champion.
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2031, 2, 4, 2, 1)]}
        self.assertEqual(team_page.champions_by_season(data), {})

    def test_past_season_short_final_still_counts(self):
        # 2026 finals ended 3-2 (games-to-win was 3 then); past seasons read the
        # decided series even though the retained games are gone.
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2026, 5, 2, 3, 2)]}
        self.assertEqual(team_page.champions_by_season(data)[2026]["champ"], 5)

    def test_banner_history_and_kinds(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2029, 6, 2, 4, 1),
                                  _playoff_series(2030, 2, 4, 4, 0)]}
        entries = team_page.team_banner_history(data, 2)
        self.assertEqual([(e["season"], e["kind"]) for e in entries],
                         [(2029, "finals"), (2030, "title")])

    def test_banner_svg_variants(self):
        title = team_page.banner_svg(2030, "title", tid=2)
        finals = team_page.banner_svg(2029, "finals")
        self.assertIn("banner--title", title)
        self.assertIn("--team-primary", title)  # standalone: vars baked on
        self.assertIn("2030 League Champions", title)
        self.assertIn("banner--finals", finals)
        self.assertIn("FINALS", finals)

    def test_rafters_render_nothing_without_titles(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2030, 2, 4, 4, 0)]}
        self.assertEqual(team_page.team_rafters_html(data, _team(0, "DUR")), "")
        self.assertIn("tm-rafters", team_page.team_rafters_html(data, _team(2, "CAM")))


class TestStartingFive(unittest.TestCase):
    def test_vacancy_roundels_for_missing_positions(self):
        roster = [
            _player(1, "Point", "Guard", pos="PG"),
            _player(2, "Shooting", "Guard", pos="SG"),
            _player(3, "Big", "Center", pos="C"),
        ]
        html = team_page.starting_five_card(_team(0, "AAA"), roster, 2029)
        self.assertEqual(html.count("sfive-vacant"), 2)  # SF + PF empty
        self.assertIn("No natural SF", html)
        self.assertIn("No natural PF", html)
        self.assertIn("Point Guard", html)

    def test_bench_excludes_starters_and_sorts_by_overall(self):
        roster = [
            _player(1, "Star", "Point", pos="PG", ovr=80),
            _player(2, "Backup", "Point", pos="PG", ovr=60),
            _player(3, "Deep", "Point", pos="PG", ovr=50),
        ]
        html = team_page.starting_five_card(_team(0, "AAA"), roster, 2029)
        bench = html.split("sfive-bench-label")[1]
        self.assertNotIn("Star Point", bench)
        self.assertLess(bench.index("Backup Point"), bench.index("Deep Point"))

    def test_court_svg_is_present_and_decorative(self):
        html = team_page.starting_five_card(_team(0, "AAA"), [_player(1, "A", "B")], 2029)
        self.assertIn("sfive-court-svg", html)
        self.assertIn('aria-hidden="true"', html)


class TestHonestSeasonFallbacks(unittest.TestCase):
    def _items_2030(self):
        return [{
            "gid": 10, "day": 1, "season": 2030, "home_tid": 0, "away_tid": 1,
            "home_pts": 100, "away_pts": 90,
            "home_box": {"tid": 0, "pts": 100}, "away_box": {"tid": 1, "pts": 90},
            "game": {"gid": 10}, "playoffs": False,
        }]

    def test_games_table_falls_back_to_last_completed_season(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        html = lg.team_games_table(_team(0, "AAA"), self._items_2030(), teams_by_tid, 2031)
        self.assertIn("2030 Season Log", html)
        self.assertIn("no 2031 games yet", html)
        self.assertIn("2030 season game log", html)
        self.assertNotIn("current-season game log", html)

    def test_games_table_current_season_unchanged(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        html = lg.team_games_table(_team(0, "AAA"), self._items_2030(), teams_by_tid, 2030)
        self.assertIn("All Games", html)
        self.assertIn("current-season game log", html)

    def test_rotation_map_notes_fallback_season(self):
        data = {"games": [{
            "gid": 10, "season": 2030, "day": 1, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "players": [{"pid": 1, "name": "A Guard", "min": 30}]},
                {"tid": 1, "pts": 90, "players": [{"pid": 2, "name": "B Wing", "min": 30}]},
            ],
        }]}
        items = lg.completed_game_items(data, season=2030, playoffs=False)
        logs = lg.build_game_logs(data, 2030)
        html = lg.rotation_map_card(_team(0, "AAA"), [], items, logs, 2031,
                                    {0: _team(0, "AAA"), 1: _team(1, "BBB")})
        self.assertIn("in 2030 (no 2031 games yet)", html)
        self.assertIn("red to green = minutes", html)
        self.assertIn('data-gid="10"', html)


class TestDepthChartCards(unittest.TestCase):
    def test_card_rows_labels_vacancies_and_stat_lines(self):
        roster = [
            _player(1, "Point", "Guard", pos="PG", ovr=70,
                    stats=[_stat_row(gp=40, pts=800, ast=200)]),
            _player(2, "Backup", "Guard", pos="PG", ovr=60),
            _player(3, "Deep", "Guard", pos="PG", ovr=50),
            _player(4, "Fourth", "Guard", pos="PG", ovr=45),
            _player(5, "Big", "Center", pos="C", ovr=65),
        ]
        roster[0]["jerseyNumber"] = 7
        html = team_page.depth_chart_card(roster, 2031, 2026)
        for label in ("Starters", "2nd String", "3rd String", "4th String"):
            self.assertIn(label, html)
        self.assertNotIn("5th String", html)
        # 4 rows x 5 slots = 20 cards; 15 are vacancies (dashed empty cards)
        self.assertEqual(html.count("depth-card--vacant"), 15)
        self.assertIn("#7", html)                      # jersey number shown
        self.assertIn("depth-ovr", html)               # OVR chip
        self.assertIn("<strong>20.0</strong><small>PTS</small>", html)  # 800/40
        self.assertIn("<strong>—</strong><small>PTS</small>", html)     # no-stats line
        for p in roster:
            self.assertEqual(html.count(lg.player_url(p, "../")), 1)

    def test_minimum_three_rows_even_when_shallow(self):
        roster = [_player(1, "Only", "Guy", pos="PG", ovr=70)]
        html = team_page.depth_chart_card(roster, 2031, 2026)
        self.assertIn("3rd String", html)
        self.assertNotIn("4th String", html)


class TestScoringShare(unittest.TestCase):
    def test_sorted_segments_and_toggle(self):
        roster = [
            _player(1, "High", "Scorer", stats=[_stat_row(pts=1000, fga=700, ast=100)]),
            _player(2, "Low", "Scorer", stats=[_stat_row(pts=500, fga=500, ast=300)]),
            _player(3, "No", "Games", stats=[]),
        ]
        html = team_page.scoring_share_card(_team(0, "AAA"), roster, 2031)
        self.assertIn("data-share-card", html)
        for key in ("pts", "fga", "ast"):
            self.assertIn(f'data-share-panel="{key}"', html)
        pts_panel = html.split('data-share-panel="pts"')[1].split("</div>\n")[0]
        self.assertLess(pts_panel.index("High Scorer"), pts_panel.index("Low Scorer"))
        # AST panel sorted the other way
        ast_panel = html.split('data-share-panel="ast"')[1]
        self.assertLess(ast_panel.index("Low Scorer"), ast_panel.index("High Scorer"))
        self.assertNotIn("No Games", html)

    def test_empty_without_any_stats(self):
        roster = [_player(1, "No", "Games", stats=[])]
        self.assertEqual(team_page.scoring_share_card(_team(0, "AAA"), roster, 2031), "")


class TestFourFactors(unittest.TestCase):
    def _teams(self):
        def stat(tid, fg, oppfg):
            return {"season": 2030, "playoffs": False, "gp": 40, "tid": tid,
                    "fg": fg, "tp": 300, "fga": 3200, "tov": 500, "fta": 800,
                    "ft": 640, "orb": 400, "drb": 1200, "pts": 4200, "oppPts": 4100,
                    "oppFg": oppfg, "oppTp": 280, "oppFga": 3100, "oppTov": 480,
                    "oppFta": 700, "oppFt": 560, "oppOrb": 380, "oppDrb": 1150}
        a = dict(_team(0, "AAA"), seasons=[], stats=[stat(0, 1700, 1500)])
        b = dict(_team(1, "BBB"), seasons=[], stats=[stat(1, 1500, 1700)])
        return [a, b]

    def test_diverging_strip_renders_rows(self):
        teams = self._teams()
        html = team_page.four_factors_card({"games": []}, teams[0], teams, 2031)
        self.assertIn("Four Factors", html)
        self.assertIn("league average", html)
        self.assertIn("eFG%", html)
        self.assertIn("Opp eFG%", html)
        self.assertIn("ff-bar-good", html)   # team A shoots better than league avg
        self.assertIn("no 2031 team stats yet", html)

    def test_requires_two_teams_with_stats(self):
        team = dict(_team(0, "AAA"), stats=[])
        self.assertEqual(team_page.four_factors_card({"games": []}, team, [team], 2031), "")


class TestFranchiseArc(unittest.TestCase):
    def _data_and_teams(self):
        seasons = []
        for s, w, l, prw in ((2029, 30, 15, 1), (2030, 38, 7, 2), (2031, 0, 0, -1)):
            seasons.append({"season": s, "won": w, "lost": l, "playoffRoundsWon": prw})
        me = dict(_team(2, "CAM"), seasons=seasons, stats=[])
        other = dict(_team(4, "TOR"), seasons=[
            {"season": 2029, "won": 15, "lost": 30, "playoffRoundsWon": -1},
            {"season": 2030, "won": 7, "lost": 38, "playoffRoundsWon": 1},
        ], stats=[])
        data = {
            "gameAttributes": {"season": 2031},
            "teams": [me, other],
            "playoffSeries": [_playoff_series(2029, 2, 4, 1, 4),
                              _playoff_series(2030, 2, 4, 4, 0)],
            "events": [
                {"type": "trade", "season": 2029, "tids": [2, 4], "pids": [7, 8]},
                {"type": "teamExpansion", "season": 2028, "tids": [2]},
                {"type": "retired", "season": 2030, "pids": [55]},
            ],
            "players": [
                {"pid": 55, "firstName": "Old", "lastName": "Legend", "tid": -3,
                 "retiredYear": 2030,
                 "stats": [{"season": 2029, "playoffs": False, "tid": 2, "gp": 40}]},
            ],
        }
        return data, [me, other], me

    def test_franchise_seasons_labels(self):
        data, teams, me = self._data_and_teams()
        rows = team_page.franchise_seasons(me, data, teams)
        self.assertEqual([r["season"] for r in rows], [2029, 2030])  # 0-0 preseason row skipped
        by_season = {r["season"]: r for r in rows}
        # 2029: playoffSeries says tid 4 won the final; CAM (prw=1) lost the Finals
        self.assertEqual(by_season[2029]["result"], "Lost Finals")
        self.assertEqual(by_season[2030]["result"], "Champion")
        self.assertEqual(by_season[2030]["finish"], 1)

    def test_event_pins_cover_trades_retirements_expansion(self):
        data, teams, me = self._data_and_teams()
        pins = team_page.team_event_pins(me, data, {t["tid"]: t for t in teams})
        kinds = {s: sorted(p["kind"] for p in v) for s, v in pins.items()}
        self.assertEqual(kinds[2029], ["trade"])
        self.assertEqual(kinds[2030], ["retire"])
        self.assertEqual(kinds[2028], ["join"])
        self.assertIn("Trade with TOR", pins[2029][0]["label"])
        self.assertIn("Old Legend retired", pins[2030][0]["label"])

    def test_history_page_renders_arc_table_and_scope(self):
        data, teams, me = self._data_and_teams()
        html = team_page.render_team_history_page(me, [], teams, 2031, 2026, data=data)
        self.assertIn("team-scope", html)
        self.assertIn("Franchise Arc", html)
        self.assertIn("Season Results", html)
        self.assertIn("TITLE", html)          # champion marker on the ribbon
        self.assertIn("2028: Joined the league", html)  # snapped pin keeps true year
        self.assertIn('href="test-cam-2-history.html"', html)  # subnav self-link

    def test_empty_franchise_shows_honest_empty_state(self):
        me = dict(_team(9, "ITH"), seasons=[{"season": 2031, "won": 0, "lost": 0}], stats=[])
        data = {"gameAttributes": {"season": 2031}, "teams": [me], "playoffSeries": [],
                "events": [], "players": []}
        html = team_page.render_team_history_page(me, [], [me], 2031, 2026, data=data)
        self.assertIn("No completed seasons yet", html)


class TestImmersionAndPolish(unittest.TestCase):
    def test_scope_wrapper_stripe_and_subnav_on_all_pages(self):
        team = dict(_team(0, "AAA"), seasons=[], stats=[])
        teams = [team]
        pages = [
            lg.render_team_roster_page(team, [], teams, 2031, 2026),
            lg.render_team_games_page(team, [], teams, 2031, 2026),
            lg.render_team_finances_page(team, [], teams, 2031, 2026),
            team_page.render_team_history_page(team, [], teams, 2031, 2026),
        ]
        for html in pages:
            self.assertIn('class="team-scope"', html)
            self.assertIn("--team-primary:", html)
            self.assertIn("tm-stripe", html)
            self.assertIn("tm-watermark", html)
            self.assertIn(">History</a>", html)  # 4th subnav entry

    def test_zero_gp_rows_hidden_behind_toggle(self):
        roster = [
            _player(1, "Played", "Games", stats=[_stat_row()]),
            _player(2, "Never", "Played", stats=[]),
        ]
        html = team_page.roster_tabs(roster, 2031, 2026, "../", {}, None)
        self.assertIn("data-toggle-inactive", html)
        self.assertIn("1 player with 0 GP hidden", html)
        self.assertEqual(html.count('<tr class="inactive-row">'), 2)  # stats + advanced

    def test_all_zero_gp_roster_shows_everyone(self):
        roster = [_player(1, "Rookie", "One", stats=[]), _player(2, "Rookie", "Two", stats=[])]
        html = team_page.roster_tabs(roster, 2031, 2026, "../", {}, None)
        self.assertNotIn("data-toggle-inactive", html)
        self.assertNotIn("inactive-row", html)

    def test_finances_page_has_no_orphan_owed_payroll_heading(self):
        team = dict(_team(0, "AAA"), seasons=[], stats=[])
        html = lg.render_team_finances_page(team, [], [team], 2031, 2026)
        self.assertNotIn("block-title", html)
        self.assertIn("<h2>Salaries</h2>", html)

    def test_luxury_tax_tiles_have_explainers(self):
        tfin = {"payroll": 310000.0, "luxtax": 10000.0, "over_cap": True, "under_cap": False,
                "tax_share": 0.0, "cash_now": 0.0, "cash_proj": 0.0}
        html = team_page.luxury_tax_card(tfin, {"soft_cap": 300000, "pool": 10000,
                                                "share": 1250.0, "n_under": 8})
        self.assertIn("has-tip", html)
        self.assertIn('title="', html)

    def test_team_color_ramp_is_deterministic_and_distinct(self):
        ramp1 = team_page.team_color_ramp(2, 8)
        ramp2 = team_page.team_color_ramp(2, 8)
        self.assertEqual(ramp1, ramp2)
        self.assertEqual(len(set(ramp1)), 8)


if __name__ == "__main__":
    unittest.main()
