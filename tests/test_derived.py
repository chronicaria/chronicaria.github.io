"""Tests for scripts/smp/derived.py and scripts/smp/appdata.py."""

import json
import math
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import appdata, derived  # noqa: E402
from smp.core import ALL_PLAYERS_BY_PID, RATING_LABELS  # noqa: E402
from smp.simmodel import SIM_HCA, SIM_LOGISTIC_K, sim_client_inputs, simulate_league  # noqa: E402


# ---------------------------------------------------------------------------
# fantasy_pts
# ---------------------------------------------------------------------------

class TestFantasyPts(unittest.TestCase):
    def test_hand_computed_example(self):
        # 30 pts / 10 reb / 5 ast on 12-20 FG, 3-5 3P, 3-4 FT, 2 TOV, 1 STL, 1 BLK:
        #   PTS 30 + 3PM 3 + FGM 24 - FGA 20 + FTM 3 - FTA 4 + REB 10
        #   + AST 10 + STL 4 + BLK 4 - TOV 4 = 60
        row = {
            "pts": 30, "fg": 12, "fga": 20, "tp": 3, "tpa": 5, "ft": 3, "fta": 4,
            "orb": 3, "drb": 7, "ast": 5, "stl": 1, "blk": 1, "tov": 2,
        }
        self.assertEqual(derived.fantasy_pts(row), 60.0)

    def test_accepts_trb_style_rows(self):
        # Season-aggregate style rows that carry trb instead of orb/drb split.
        row = {
            "pts": 30, "fg": 12, "fga": 20, "tp": 3, "ft": 3, "fta": 4,
            "trb": 10, "ast": 5, "stl": 1, "blk": 1, "tov": 2,
        }
        self.assertEqual(derived.fantasy_pts(row), 60.0)

    def test_missing_inputs_return_none(self):
        self.assertIsNone(derived.fantasy_pts(None))
        self.assertIsNone(derived.fantasy_pts({}))
        self.assertIsNone(derived.fantasy_pts({"pts": 10, "fg": 4}))  # no fga


# ---------------------------------------------------------------------------
# four_factors
# ---------------------------------------------------------------------------

class TestFourFactors(unittest.TestCase):
    def test_known_values(self):
        row = {
            "fg": 40, "tp": 10, "fga": 90, "tov": 15, "fta": 20, "ft": 16,
            "orb": 12, "drb": 33,
            "oppFg": 35, "oppTp": 8, "oppFga": 88, "oppTov": 12, "oppFta": 25,
            "oppFt": 18, "oppOrb": 10, "oppDrb": 30,
        }
        ff = derived.four_factors(row)
        self.assertAlmostEqual(ff["efg"], 100 * (40 + 5) / 90)          # 50.0
        self.assertAlmostEqual(ff["tov_pct"], 100 * 15 / (90 + 0.44 * 20 + 15))
        self.assertAlmostEqual(ff["orb_pct"], 100 * 12 / (12 + 30))
        self.assertAlmostEqual(ff["ft_rate"], 16 / 90)
        self.assertAlmostEqual(ff["opp_efg"], 100 * (35 + 4) / 88)
        self.assertAlmostEqual(ff["opp_tov_pct"], 100 * 12 / (88 + 0.44 * 25 + 12))
        self.assertAlmostEqual(ff["opp_orb_pct"], 100 * 10 / (10 + 33))
        self.assertAlmostEqual(ff["opp_ft_rate"], 18 / 88)

    def test_zero_denominators_yield_none(self):
        ff = derived.four_factors({"fg": 0, "fga": 0})
        self.assertIsNone(ff["efg"])
        self.assertIsNone(ff["ft_rate"])
        self.assertIsNone(ff["orb_pct"])


# ---------------------------------------------------------------------------
# drama_index
# ---------------------------------------------------------------------------

def _game(gid, home_qtrs, away_qtrs, overtimes=0, clutch=0):
    return {
        "gid": gid,
        "season": 2030,
        "overtimes": overtimes,
        "clutchPlays": ["play"] * clutch,
        "teams": [
            {"tid": 0, "pts": sum(home_qtrs), "ptsQtrs": list(home_qtrs)},
            {"tid": 1, "pts": sum(away_qtrs), "ptsQtrs": list(away_qtrs)},
        ],
    }


class TestDramaIndex(unittest.TestCase):
    def test_ot_comeback_beats_blowout(self):
        # Home trails by 20 after two quarters, forces OT, wins by 2.
        thriller = _game(1, [15, 20, 30, 25, 12], [30, 25, 20, 15, 10], overtimes=1, clutch=2)
        # 40-point wire-to-wire blowout: no OT, no comeback, no clutch plays.
        blowout = _game(2, [35, 30, 28, 27], [20, 20, 20, 20])
        hi = derived.drama_index(thriller)
        lo = derived.drama_index(blowout)
        self.assertGreater(hi, lo)
        self.assertGreater(hi, 50.0)
        self.assertLess(lo, 10.0)

    def test_comeback_size_from_quarter_margins(self):
        thriller = _game(1, [15, 20, 30, 25, 12], [30, 25, 20, 15, 10])
        self.assertEqual(derived.comeback_size(thriller), 20.0)

    def test_bounded_and_feats_counted(self):
        game = _game(3, [25, 25, 25, 26], [25, 25, 25, 25], overtimes=3, clutch=9)
        feats = {"3": [{"pid": 1}, {"pid": 2}, {"pid": 3}]}
        score = derived.drama_index(game, feats)
        self.assertLessEqual(score, 100.0)
        self.assertGreater(score, derived.drama_index(game))  # feats add drama

    def test_unfinished_game_scores_zero(self):
        self.assertEqual(derived.drama_index({"teams": [{"tid": 0}, {"tid": 1}]}), 0.0)


# ---------------------------------------------------------------------------
# led_league
# ---------------------------------------------------------------------------

class TestLedLeague(unittest.TestCase):
    def test_shape_and_values(self):
        data = {
            "seasonLeaders": [
                {"season": 2029, "regularSeason": {"pts": 31.2, "trb": 13.1, "ast": 10.4}},
                {"season": 2030, "regularSeason": {"pts": 33.0, "trb": 12.0, "ast": 9.8, "bad": "x"}},
            ]
        }
        led = derived.led_league(data)
        self.assertEqual(sorted(led.keys()), [2029, 2030])
        self.assertEqual(led[2030]["pts"], 33.0)
        self.assertNotIn("bad", led[2030])  # non-numeric values dropped
        marks = derived.led_league_stats(led, 2030, {"pts": 33.0, "ast": 5.0}, ["pts", "ast"])
        self.assertEqual(marks, {"pts"})

    def test_empty_export(self):
        self.assertEqual(derived.led_league({}), {})


# ---------------------------------------------------------------------------
# shot zones
# ---------------------------------------------------------------------------

class TestShotZones(unittest.TestCase):
    def test_aggregation_and_league_average(self):
        box = {"pid": 7, "fgAtRim": 4, "fgaAtRim": 5, "fgLowPost": 1, "fgaLowPost": 2,
               "fgMidRange": 2, "fgaMidRange": 6, "tp": 3, "tpa": 8}
        data = {"games": [
            {"season": 2030, "teams": [{"tid": 0, "players": [dict(box)]}, {"tid": 1, "players": []}]},
            {"season": 2030, "teams": [{"tid": 0, "players": [dict(box)]}, {"tid": 1, "players": []}]},
        ]}
        zones = derived.player_shot_zones(data, 7, 2030)
        self.assertEqual(zones["rim"]["fg"], 8)
        self.assertEqual(zones["rim"]["fga"], 10)
        self.assertAlmostEqual(zones["rim"]["pct"], 80.0)
        # The only shooter IS the league here, so lg_pct matches his pct.
        self.assertAlmostEqual(zones["rim"]["lg_pct"], 80.0)
        self.assertAlmostEqual(zones["three"]["pct"], 100 * 6 / 16)
        self.assertIsNone(derived.player_shot_zones(data, 7, 2029))  # no boxes that season
        self.assertIsNone(derived.player_shot_zones(data, 99, 2030))  # unknown pid


# ---------------------------------------------------------------------------
# app-data payload
# ---------------------------------------------------------------------------

_RATING_KEYS = list(RATING_LABELS)


def _rating_row(season, ovr, pot, pos="PG"):
    row = {"season": season, "pos": pos, "ovr": ovr, "pot": pot, "skills": []}
    for key in _RATING_KEYS:
        row[key] = 50
    return row


def _league_player(pid, tid, ovr, season=2030):
    return {
        "pid": pid,
        "firstName": "Player",
        "lastName": str(pid),
        "tid": tid,
        "retiredYear": None,
        "born": {"year": season - 25},
        "jerseyNumber": str(pid),
        "value": 40.0 + pid,
        "contract": {"amount": 10000 + 100 * pid, "exp": season + 2},
        "ratings": [_rating_row(season, ovr, ovr + 2)],
        "stats": [{
            "season": season - 1, "playoffs": False, "tid": tid, "gp": 10,
            "min": 300, "pts": 150, "fg": 60, "fga": 120, "tp": 10, "tpa": 30,
            "ft": 20, "fta": 25, "orb": 10, "drb": 40, "ast": 30, "stl": 8,
            "blk": 5, "tov": 12, "obpm": 1.0, "dbpm": 0.5,
        }],
    }


def _league_export():
    teams = []
    for tid, abbrev in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        teams.append({
            "tid": tid,
            "abbrev": abbrev,
            "region": f"Region{tid}",
            "name": f"Name{tid}",
            "seasons": [{"season": 2029, "won": 20 + tid, "lost": 25 - tid}],
            "stats": [{"season": 2029, "playoffs": False, "gp": 45,
                       "pts": 45 * (110 + 2 * tid), "oppPts": 45 * 110}],
        })
    players = []
    pid = 0
    for tid in range(4):
        for _ in range(6):
            # team 3 gets the strongest roster, team 0 the weakest
            players.append(_league_player(pid, tid, 55 + 6 * tid))
            pid += 1
    return {
        "gameAttributes": {"season": 2030, "phase": 0, "numGames": 6},
        "teams": teams,
        "players": players,
        "games": [],
        "seasonLeaders": [],
    }


class TestAppData(unittest.TestCase):
    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def test_schema_keys_present(self):
        data = _league_export()
        app = appdata.build_app_data(data)
        self.assertEqual(sorted(app.keys()), ["finance", "players", "season", "sim", "teams"])
        self.assertEqual(app["season"], 2030)
        self.assertEqual(app["finance"], {"tax_line": 300000, "notes": "thousands"})

        player = app["players"][0]
        for key in ["pid", "name", "pos", "age", "tid", "jersey", "ovr", "pot",
                    "salary", "exp", "value", "pg", "ratings", "skills"]:
            self.assertIn(key, player)
        self.assertEqual(
            sorted(player["pg"].keys()),
            sorted(["pts", "trb", "ast", "stl", "blk", "tov", "min",
                    "fg_pct", "tp_pct", "ft_pct", "fpts"]),
        )
        self.assertEqual(sorted(player["ratings"].keys()), sorted(_RATING_KEYS))
        # players sorted by ovr desc: top player is from the strongest team (tid 3)
        self.assertEqual(player["tid"], 3)
        self.assertEqual(player["ovr"], 73)
        # per-game averages come from the 10-gp stat row: 150 pts -> 15.0/g
        self.assertEqual(player["pg"]["pts"], 15.0)
        self.assertEqual(player["pg"]["trb"], 5.0)
        self.assertAlmostEqual(player["pg"]["fg_pct"], 50.0)
        self.assertIsNotNone(player["pg"]["fpts"])

        team = app["teams"][0]
        for key in ["tid", "abbrev", "region", "name", "colors", "strength", "payroll", "record"]:
            self.assertIn(key, team)
        self.assertEqual(sorted(team["colors"].keys()), ["chart", "primary", "secondary"])
        self.assertEqual(team["record"], {"w": 0, "l": 0})  # fresh season starts 0-0
        # payroll: 6 rostered players on tid 0 -> pids 0..5
        self.assertEqual(team["payroll"], sum(10000 + 100 * p for p in range(6)))

        sim = app["sim"]
        self.assertEqual(sorted(sim.keys()), ["hca", "logistic_k", "schedule", "strengths"])
        self.assertEqual(sim["hca"], SIM_HCA)
        self.assertEqual(sim["logistic_k"], SIM_LOGISTIC_K)
        self.assertEqual(sorted(sim["strengths"].keys()), ["0", "1", "2", "3"])
        self.assertTrue(sim["schedule"])
        for entry in sim["schedule"]:
            self.assertEqual(len(entry), 3)  # [day, home_tid, away_tid]
        # strongest roster should carry the highest strength
        self.assertEqual(max(sim["strengths"], key=lambda t: sim["strengths"][t]), "3")

    def test_deterministic_double_build_and_write(self):
        data = _league_export()
        first = json.dumps(appdata.build_app_data(data), sort_keys=True)
        ALL_PLAYERS_BY_PID.clear()
        second = json.dumps(appdata.build_app_data(_league_export()), sort_keys=True)
        self.assertEqual(first, second)

        with tempfile.TemporaryDirectory() as tmp:
            path_a = appdata.write_app_data(os.path.join(tmp, "a"), _league_export())
            path_b = appdata.write_app_data(os.path.join(tmp, "b"), _league_export())
            self.assertTrue(str(path_a).endswith(os.path.join("assets", "app-data.json")))
            with open(path_a, encoding="utf-8") as fh:
                blob_a = fh.read()
            with open(path_b, encoding="utf-8") as fh:
                blob_b = fh.read()
            self.assertEqual(blob_a, blob_b)
            parsed = json.loads(blob_a)
            self.assertEqual(parsed["season"], 2030)


class TestSimParity(unittest.TestCase):
    """The client logistic model must agree with simulate_league's Monte Carlo."""

    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def test_expected_wins_match_server_sim(self):
        data = _league_export()
        teams = data["teams"]
        players = data["players"]
        season = 2030
        inputs = sim_client_inputs(data, teams, players, season)
        strengths = inputs["strengths"]

        # Client-side expectation: sum of logistic win probs over the schedule.
        expected = {tid: 0.0 for tid in strengths}
        for day, home, away in inputs["schedule"]:
            diff = (strengths[home] - strengths[away]) + inputs["hca"]
            p_home = 1.0 / (1.0 + math.exp(-diff * inputs["logistic_k"]))
            expected[home] += p_home
            expected[away] += 1.0 - p_home

        sims = 4000
        results = simulate_league(data, teams, players, season, sims=sims)["teams"]
        for tid, exp_wins in expected.items():
            proj_w = results[tid]["proj_w"]
            # Monte Carlo std error over `sims` runs is well under 0.05 wins here.
            self.assertLess(abs(proj_w - exp_wins), 0.2,
                            msg=f"tid {tid}: client {exp_wins:.3f} vs server {proj_w:.3f}")


if __name__ == "__main__":
    unittest.main()
