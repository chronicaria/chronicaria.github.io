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


if __name__ == "__main__":
    unittest.main()
