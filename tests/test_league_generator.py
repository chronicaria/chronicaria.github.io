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


class TestFreeAgentSalary(unittest.TestCase):
    def test_worked_examples_from_formula(self):
        # 1-year asking salary ($M) must match the formula's worked examples.
        self.assertEqual(lg.fa_salary_millions(67, 73, 24), 31)  # Cody Williams -> $31M
        self.assertEqual(lg.fa_salary_millions(72, 72, 28), 37)  # Tyrese Maxey -> $37M
        self.assertEqual(lg.fa_salary_millions(79, 87, 22), 50)  # AJ Dybantsa (80+ capped) -> $50M

    def test_bounds_and_curve_ends(self):
        self.assertEqual(lg.fa_salary_millions(40, 40, 30), 1)   # score <= 52 -> $1M floor
        self.assertEqual(lg.fa_salary_millions(90, 90, 27), 50)  # score >= 80 -> $50M cap

    def test_by_length_first_year_matches_single(self):
        vals = lg.fa_salary_by_length(67, 73, 24)
        self.assertEqual(len(vals), 5)
        self.assertEqual(vals[0], lg.fa_salary_millions(67, 73, 24))  # 1-yr == pure formula
        # aging a 24yo whose upside premium fades should not raise the annual on longer deals
        self.assertLessEqual(vals[4], vals[0])


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
        self.assertIn("2034", html)  # salary charts now extend through 2034
        self.assertNotIn("2035", html)
        self.assertNotIn("2029 expiring", html)
        self.assertNotIn(">exp</span>", html)
        self.assertNotIn("expiring-cell", html)

    def test_team_finances_shows_next_five_seasons(self):
        player = _player(23, "Future", "Season", tid=0, exp=2035, amount=5000)

        html = lg.team_finances_table([player], 2034)

        self.assertNotIn("2034", html)  # the finished season column is dropped
        self.assertIn("2035", html)     # window is season+1 .. season+5
        self.assertIn("2039", html)
        self.assertNotIn("2040", html)

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
        self.assertIn("red to green = minutes", html)


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
        # revenue = $180M league share + $5M per win (+ bonuses/adjustments)
        self.assertEqual(a["revenue_now"], lg.FIN_SHARE + lg.FIN_PER_WIN * 10)
        self.assertEqual(a["revenue_now"], 230000)
        self.assertEqual(a["tax_share_in"], 0)
        # net revenue = the whole next-season budget: revenue − tax + tax share
        self.assertAlmostEqual(a["net_revenue_now"], 230000 - 20000)
        self.assertAlmostEqual(a["season_balance_now"], a["net_revenue_now"] - 320000)
        # B under cap: collects the whole pool (only under-cap team)
        self.assertEqual(b["luxtax"], 0)
        self.assertEqual(b["tax_share_in"], 20000)
        self.assertAlmostEqual(b["net_revenue_now"],
                               lg.FIN_SHARE + lg.FIN_PER_WIN * 5 + 20000)
        # surplus vs committed 2031 payroll (contracts run through exp 2031)
        self.assertAlmostEqual(b["committed_next"], 200000)
        self.assertAlmostEqual(b["surplus_next"], b["net_revenue_proj"] - 200000)
        # luxury-tax pool is conserved: collected == redistributed
        self.assertEqual(lf["pool"], 20000)
        self.assertAlmostEqual(sum(t["tax_share_in"] for t in lf["teams"].values()), lf["pool"])

    def test_manual_adjustment_moves_cash_and_nets_to_zero(self):
        # 2030: Cambridge (tid 2) sends $1M to Waltham (tid 6) via FIN_ADJUSTMENTS.
        teams = [self._team_s(2, "CAM", 5, 5), self._team_s(6, "WAL", 5, 5)]
        players = [self._pl(2, 100000), self._pl(6, 100000)]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        cam, wal = lf["teams"][2], lf["teams"][6]
        self.assertEqual(cam["adj"], -1000)
        self.assertEqual(wal["adj"], 1000)
        # adjustment is baked into revenue/net revenue and conserved across the two teams
        self.assertAlmostEqual(cam["revenue_now"],
                               lg.FIN_SHARE + lg.FIN_PER_WIN * 5 - 1000)
        self.assertAlmostEqual(cam["net_revenue_now"] + wal["net_revenue_now"],
                               2 * (lg.FIN_SHARE + lg.FIN_PER_WIN * 5))
        self.assertAlmostEqual(cam["adj"] + wal["adj"], 0)

    def test_2031_peterson_trade_cash(self):
        # 2031: Gooners (tid 5) send $30M to Waltham (tid 6) in the Darryn Peterson trade.
        teams = [self._team_s(5, "GOO", 5, 5), self._team_s(6, "WAL", 5, 5)]
        players = [self._pl(5, 100000), self._pl(6, 100000)]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        lf = lg.compute_league_finances(data, teams, players, 2031, odds={})
        goo, wal = lf["teams"][5], lf["teams"][6]
        self.assertEqual(goo["adj"], -30000)
        self.assertEqual(wal["adj"], 30000)
        self.assertIn("Darryn Peterson", goo["adj_note"])
        self.assertIn("Darryn Peterson", wal["adj_note"])
        # a 2031 adjustment must not leak into another season's ledger
        lf30 = lg.compute_league_finances(data, teams, players, 2030, odds={})
        self.assertEqual(lf30["teams"][5]["adj"], 0)

    def test_adjustments_net_to_zero_every_season(self):
        for season, entries in lg.FIN_ADJUSTMENTS.items():
            net = sum(e.get("amount", 0) for e in entries.values())
            self.assertEqual(net, 0, f"FIN_ADJUSTMENTS for {season} must net to zero")

    def test_salary_retention_moves_payroll_between_teams(self):
        # Mechanism test: a player (pid 1789) sits on tid 5 at $42M; tid 6 retains $17M.
        # FIN_RETENTION is injected here so the test doesn't depend on live trade data.
        cody = {"pid": 1789, "firstName": "Cody", "lastName": "Williams", "tid": 5,
                "contract": {"amount": 42000, "exp": 2034}, "ratings": [{"season": 2030, "ovr": 65}]}
        teams = [self._team_s(5, "GOO", 5, 5), self._team_s(6, "WAL", 5, 5)]
        players = [cody, self._pl(6, 50000)]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        saved = dict(lg.ALL_PLAYERS_BY_PID)
        saved_ret = dict(lg.FIN_RETENTION)
        lg.ALL_PLAYERS_BY_PID.clear()
        lg.ALL_PLAYERS_BY_PID.update({1789: cody})
        lg.FIN_RETENTION.clear()
        lg.FIN_RETENTION.update({1789: {"held_by": 6, "amount": 17000, "note": "Waltham (trade)"}})
        try:
            lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        finally:
            lg.ALL_PLAYERS_BY_PID.clear()
            lg.ALL_PLAYERS_BY_PID.update(saved)
            lg.FIN_RETENTION.clear()
            lg.FIN_RETENTION.update(saved_ret)
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
        self.assertEqual(lg.playoff_status(data, 0, 2030), (True, True, True))    # champion -> 10+10+15
        self.assertEqual(lg.playoff_status(data, 1, 2030), (True, True, False))   # finalist -> 10+10
        self.assertEqual(lg.playoff_status(data, 2, 2030), (True, False, False))  # 1st-round out -> 10

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

    def test_average_net_revenue_identity_is_300m(self):
        # Synthetic full league: 225 total wins, 4 playoff teams, 2 finalists,
        # 1 champion. Average net revenue (= next-season budget) must be exactly
        # $300.0M: (10*180 + 225*5 + 4*10 + 2*10 + 15)/10 = 300.0 (luxury tax and
        # manual adjustments net to zero league-wide).
        wins = [30, 28, 26, 25, 24, 22, 20, 18, 17, 15]  # sums to 225
        self.assertEqual(sum(wins), 225)
        teams = [self._team_s(tid, f"T{tid}", w, 45 - w) for tid, w in enumerate(wins)]
        players = [self._pl(tid, 282900) for tid in range(10)]  # avg payroll 282.9M
        finished = {"season": 2030, "series": [
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 4}, "away": {"tid": 2, "won": 2}}],
            [{"home": {"tid": 0, "won": 4}, "away": {"tid": 1, "won": 2}}],
        ]}
        data = {"teams": teams, "players": players, "playoffSeries": [finished], "releasedPlayers": []}
        lf = lg.compute_league_finances(data, teams, players, 2030, odds={})
        self.assertEqual(len(lf["teams"]), 10)
        # champion stacks berth + finals + title = $35M
        self.assertEqual(lf["teams"][0]["earned_playoff"],
                         lg.FIN_PLAYOFF + lg.FIN_FINALS + lg.FIN_CHAMP)
        self.assertEqual(lf["teams"][0]["earned_playoff"], 35000)
        avg_net = sum(f["net_revenue_now"] for f in lf["teams"].values()) / 10
        self.assertAlmostEqual(avg_net, 300000.0)
        # season balance = net revenue − payroll; league-average ≈ +$17.1M here
        avg_balance = sum(f["season_balance_now"] for f in lf["teams"].values()) / 10
        self.assertAlmostEqual(avg_balance, 300000.0 - 282900.0)


class TestCanonicalPositions(unittest.TestCase):
    def _rating(self, pos, **kw):
        return {"season": 2031, "pos": pos, "pss": 40, "drb": 40, "tp": 40, "fg": 40, **kw}

    def test_canonical_labels_pass_through(self):
        for pos in ("PG", "SG", "SF", "PF", "C"):
            self.assertEqual(lg.canonical_pos({"hgt": 78}, self._rating(pos)), pos)

    def test_guard_splits_on_playmaking_vs_scoring(self):
        pg = self._rating("G", pss=60, drb=60, tp=30, fg=30)
        sg = self._rating("G", pss=30, drb=30, tp=60, fg=60)
        self.assertEqual(lg.canonical_pos({"hgt": 74}, pg), "PG")
        self.assertEqual(lg.canonical_pos({"hgt": 74}, sg), "SG")

    def test_frontcourt_middles_round_by_height(self):
        self.assertEqual(lg.canonical_pos({"hgt": 78}, self._rating("GF")), "SG")
        self.assertEqual(lg.canonical_pos({"hgt": 80}, self._rating("GF")), "SF")
        self.assertEqual(lg.canonical_pos({"hgt": 80}, self._rating("F")), "SF")
        self.assertEqual(lg.canonical_pos({"hgt": 82}, self._rating("F")), "PF")
        self.assertEqual(lg.canonical_pos({"hgt": 82}, self._rating("FC")), "PF")
        self.assertEqual(lg.canonical_pos({"hgt": 84}, self._rating("FC")), "C")

    def test_normalize_rewrites_ratings_and_box_scores_in_place(self):
        data = {
            "players": [{"pid": 7, "hgt": 84, "ratings": [self._rating("FC"), self._rating("F", tp=30, fg=30)]}],
            "games": [{"teams": [{"players": [{"pid": 7, "pos": "GF"}, {"pid": 99, "pos": "SF"}]}]}],
        }
        lg.normalize_positions(data)
        self.assertEqual([r["pos"] for r in data["players"][0]["ratings"]], ["C", "PF"])
        # box score maps by pid to the player's latest canonical pos; unknown pid untouched
        box = data["games"][0]["teams"][0]["players"]
        self.assertEqual(box[0]["pos"], "PF")
        self.assertEqual(box[1]["pos"], "SF")

    def test_no_middle_labels_survive_on_the_real_export(self):
        import glob, json
        matches = glob.glob(os.path.join(_REPO, "league-data", "2031_preseason.json"))
        if not matches:
            self.skipTest("2031 preseason export not present")
        data = json.load(open(matches[0]))
        lg.normalize_positions(data)
        seen = {r.get("pos") for p in data["players"] for r in (p.get("ratings") or [])}
        self.assertTrue(seen.issubset(set(lg.CANONICAL_POS)), seen)


if __name__ == "__main__":
    unittest.main()
