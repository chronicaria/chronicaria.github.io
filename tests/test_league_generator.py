"""Focused regression tests for scripts/league_generator.py."""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import league_generator as lg  # noqa: E402


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


def _player(pid, first, last, tid=0, exp=2030, amount=10000, ovr=60):
    return {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 2000},
        "contract": {"exp": exp, "amount": amount},
        "ratings": [{"season": 2029, "pos": "G", "ovr": ovr, "pot": ovr + 2}],
    }


class TestContractExpiryMarket(unittest.TestCase):
    def test_rostered_expiring_contracts_exclude_free_agents_and_retired_players(self):
        players = [
            _player(1, "Rostered", "Guard", tid=0, exp=2029),
            _player(2, "Free", "Agent", tid=lg.FREE_AGENT_TID, exp=2029),
            _player(3, "Future", "Deal", tid=1, exp=2030),
            {**_player(4, "Retired", "Player", tid=lg.RETIRED_TID, exp=2029), "retiredYear": 2028},
        ]

        rows = lg.contract_expiring_players(players, 2029, rostered_only=True)

        self.assertEqual([p["pid"] for p in rows], [1])

class TestTeamGameViews(unittest.TestCase):
    def test_team_finances_limit_years_and_omit_expiry_badges(self):
        short = _player(21, "Short", "Deal", tid=0, exp=2029, amount=5000)
        long = _player(22, "Long", "Deal", tid=0, exp=2034, amount=7000)

        html = lg.team_finances_table([short, long], 2029)

        self.assertIn("2033", html)
        self.assertNotIn("2034", html)
        self.assertNotIn("2035", html)
        self.assertNotIn("2029 expiring", html)
        self.assertNotIn(">exp</span>", html)
        self.assertNotIn("expiring-cell", html)

    def test_team_finances_after_2033_still_includes_current_season(self):
        player = _player(23, "Future", "Season", tid=0, exp=2035, amount=5000)

        html = lg.team_finances_table([player], 2034)

        self.assertIn("2034", html)
        self.assertNotIn("2035", html)

    def test_depth_chart_assigns_each_player_once(self):
        players = [
            {**_player(31, "Combo", "Guard", ovr=70), "hgt": 75},
            {**_player(32, "Swing", "Wing", ovr=68), "hgt": 80},
            {**_player(33, "Front", "Court", ovr=66), "hgt": 83},
        ]
        players[0]["ratings"][-1].update({"pos": "G", "pss": 80, "drb": 72, "tp": 45, "fg": 50})
        players[1]["ratings"][-1].update({"pos": "GF"})
        players[2]["ratings"][-1].update({"pos": "FC"})

        html = lg.depth_chart_card(players, 2029)

        for player in players:
            self.assertEqual(html.count(lg.player_url(player, "../")), 1)

    def test_team_games_table_includes_completed_and_upcoming_regular_games(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        game_items = [
            {
                "gid": 1,
                "day": 1,
                "season": 2029,
                "home_tid": 0,
                "away_tid": 1,
                "home_pts": 101,
                "away_pts": 99,
                "home_box": {"tid": 0, "pts": 101},
                "away_box": {"tid": 1, "pts": 99},
                "game": {"gid": 1},
                "playoffs": False,
            },
            {
                "gid": 2,
                "day": 2,
                "season": 2029,
                "home_tid": 1,
                "away_tid": 0,
                "home_pts": None,
                "away_pts": None,
                "playoffs": False,
            },
            {
                "gid": 3,
                "day": 3,
                "season": 2029,
                "home_tid": 0,
                "away_tid": 1,
                "home_pts": 80,
                "away_pts": 90,
                "home_box": {"tid": 0, "pts": 80},
                "away_box": {"tid": 1, "pts": 90},
                "game": {"gid": 3},
                "playoffs": True,
            },
        ]

        html = lg.team_games_table(_team(0, "AAA"), game_items, teams_by_tid, 2029)

        self.assertIn("1 completed · 1 upcoming", html)
        self.assertIn("AAA current-season game log", html)
        self.assertEqual(html.count('class="click-row'), 2)
        self.assertIn("Upcoming", html)

    def test_rotation_map_uses_logged_team_not_current_roster_team(self):
        current_guard = _player(1, "Current", "Guard", tid=0)
        former_wing = _player(2, "Former", "Wing", tid=1)
        current_forward = _player(4, "Current", "Forward", tid=0)
        original_players = dict(lg.ALL_PLAYERS_BY_PID)
        lg.ALL_PLAYERS_BY_PID.clear()
        lg.ALL_PLAYERS_BY_PID.update({
            1: current_guard,
            2: former_wing,
            4: current_forward,
        })

        def restore_players():
            lg.ALL_PLAYERS_BY_PID.clear()
            lg.ALL_PLAYERS_BY_PID.update(original_players)

        self.addCleanup(restore_players)
        data = {
            "games": [
                {
                    "gid": 101,
                    "season": 2029,
                    "day": 1,
                    "playoffs": False,
                    "teams": [
                        {
                            "tid": 0,
                            "pts": 100,
                            "players": [
                                {"pid": 1, "name": "Current Guard", "min": 10},
                                {"pid": 2, "name": "Former Wing", "min": 22},
                            ],
                        },
                        {"tid": 1, "pts": 90, "players": [{"pid": 3, "name": "Opponent", "min": 30}]},
                    ],
                },
                {
                    "gid": 102,
                    "season": 2029,
                    "day": 2,
                    "playoffs": False,
                    "teams": [
                        {"tid": 1, "pts": 110, "players": [{"pid": 1, "name": "Current Guard", "min": 33}]},
                        {"tid": 0, "pts": 95, "players": [{"pid": 4, "name": "Current Forward", "min": 12}]},
                    ],
                },
            ]
        }
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        game_items = lg.completed_game_items(data, season=2029, playoffs=False)
        logs = lg.build_game_logs(data, 2029)

        html = lg.rotation_map_card(_team(0, "AAA"), [current_guard, current_forward], game_items, logs, 2029, teams_by_tid)

        self.assertEqual([entry["tid"] for entry in logs[1]], [0, 1])
        self.assertIn("Former Wing", html)
        self.assertIn("Current Forward", html)
        self.assertIn(">10</td>", html)
        self.assertNotIn(">33</td>", html)
        self.assertIn("hsla(", html)
        self.assertIn("red to green = minutes load", html)


class TestTeamFinances(unittest.TestCase):
    def _team_s(self, tid, abbrev, won, lost):
        return {"tid": tid, "abbrev": abbrev, "region": "City", "name": abbrev,
                "seasons": [{"season": 2030, "won": won, "lost": lost}]}

    def _pl(self, tid, amount):
        return {"pid": tid * 100, "firstName": "P", "lastName": str(tid), "tid": tid,
                "contract": {"amount": amount, "exp": 2031},
                "ratings": [{"season": 2030, "ovr": 60}]}

    def test_regular_season_ledger_and_luxury_tax_redistribution(self):
        teams = [self._team_s(0, "AAA", 10, 0), self._team_s(1, "BBB", 5, 5)]
        players = [self._pl(0, 320000), self._pl(1, 200000)]  # A over the $300M cap, B under
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        a, b = lf["teams"][0], lf["teams"][1]
        # A over cap: pays luxury tax, no playoff bonus during the regular season
        self.assertEqual(a["luxtax"], 20000)
        self.assertEqual(a["earned_playoff"], 0)
        self.assertEqual(a["rev_now"], lg.FIN_BASE + lg.FIN_PER_WIN * 10)
        self.assertEqual(a["tax_share"], 0)
        self.assertAlmostEqual(a["cash_now"], lg.FIN_START + a["rev_now"] - 320000 - 20000)
        # B under cap: collects the whole pool (only under-cap team)
        self.assertEqual(b["luxtax"], 0)
        self.assertEqual(b["tax_share"], 20000)
        self.assertAlmostEqual(b["cash_now"], lg.FIN_START + (lg.FIN_BASE + lg.FIN_PER_WIN * 5) - 200000 + 20000)
        # luxury-tax pool is conserved: collected == redistributed
        self.assertEqual(lf["pool"], 20000)
        self.assertAlmostEqual(sum(t["tax_share"] for t in lf["teams"].values()), lf["pool"])

    def test_manual_adjustment_moves_cash_and_nets_to_zero(self):
        # Cambridge (tid 2) sends $1M to Waltham (tid 6) via FIN_ADJUSTMENTS.
        teams = [self._team_s(2, "CAM", 5, 5), self._team_s(6, "WAL", 5, 5)]
        players = [self._pl(2, 100000), self._pl(6, 100000)]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        cam, wal = lf["teams"][2], lf["teams"][6]
        self.assertEqual(cam["adj"], -1000)
        self.assertEqual(wal["adj"], 1000)
        # adjustment is included in cash on hand and conserved across the two teams
        self.assertAlmostEqual(cam["cash_now"] + wal["cash_now"],
                               lf["teams"][2]["cash_proj"] + lf["teams"][6]["cash_proj"])
        self.assertAlmostEqual(cam["adj"] + wal["adj"], 0)

    def test_salary_retention_moves_payroll_between_teams(self):
        # Cody Williams (pid 1789) sits on the Gooners (tid 5) at $42M; Waltham (tid 6) retains $17M.
        cody = {"pid": 1789, "firstName": "Cody", "lastName": "Williams", "tid": 5,
                "contract": {"amount": 42000, "exp": 2034}, "ratings": [{"season": 2030, "ovr": 65}]}
        teams = [self._team_s(5, "GOO", 5, 5), self._team_s(6, "WAL", 5, 5)]
        players = [cody, self._pl(6, 50000)]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        saved = dict(lg.ALL_PLAYERS_BY_PID)
        lg.ALL_PLAYERS_BY_PID.clear()
        lg.ALL_PLAYERS_BY_PID.update({1789: cody})
        try:
            lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        finally:
            lg.ALL_PLAYERS_BY_PID.clear()
            lg.ALL_PLAYERS_BY_PID.update(saved)
        goo, wal = lf["teams"][5], lf["teams"][6]
        # Gooners are relieved of $17M: they pay $25M of Cody's $42M
        self.assertAlmostEqual(goo["retained"], -17000)
        self.assertAlmostEqual(goo["payroll"], 42000 - 17000)
        # Waltham carries the retained $17M on top of its own $50M roster
        self.assertAlmostEqual(wal["retained"], 17000)
        self.assertAlmostEqual(wal["payroll"], 50000 + 17000)
        # retention nets to zero across the league
        self.assertAlmostEqual(sum(t["retained"] for t in lf["teams"].values()), 0)

    def test_playoff_bonuses_stack_only_when_earned(self):
        complete = {"season": 2030, "series": [
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 4}, "away": {"tid": 2, "won": 2}}],
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 1, "won": 2}}],
        ]}
        data = {"playoffSeries": [complete]}
        self.assertEqual(lg.playoff_status(data, 0, 2030), (True, True, True))    # champion -> 25+30+40
        self.assertEqual(lg.playoff_status(data, 1, 2030), (True, True, False))   # finalist -> 25+30
        self.assertEqual(lg.playoff_status(data, 2, 2030), (True, False, False))  # 1st-round out -> 25

    def test_no_false_finalists_mid_round_one(self):
        # Only round 1 exists; tid0 has already clinched its series 4-1. The Finals
        # round does not exist yet, so nobody may be crowned finalist/champion.
        midway = {"season": 2030, "series": [
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 2}, "away": {"tid": 2, "won": 1}}],
        ]}
        data = {"playoffSeries": [midway]}
        self.assertEqual(lg.playoff_status(data, 0, 2030), (True, False, False))
        self.assertEqual(lg.playoff_status(data, 1, 2030), (True, False, False))

    def test_finals_in_progress_is_not_yet_a_championship(self):
        inprog = {"season": 2030, "series": [
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 3, "won": 0}},
             {"home": {"tid": 1, "won": 4}, "away": {"tid": 2, "won": 1}}],
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 1, "won": 2}}],  # 3-2, unclinched
        ]}
        data = {"playoffSeries": [inprog]}
        self.assertEqual(lg.playoff_status(data, 0, 2030), (True, True, False))
        self.assertEqual(lg.playoff_status(data, 1, 2030), (True, True, False))


if __name__ == "__main__":
    unittest.main()
