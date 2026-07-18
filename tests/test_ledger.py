"""Tests for scripts/smp/ledger.py (odds-history ledger, PLAN idea B14)."""

import json
import os
import shutil
import sys
import tempfile
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.ledger import load_odds_history, update_odds_ledger  # noqa: E402


def _export(season, phase, n_games, num_games=45):
    return {
        "gameAttributes": {"season": season, "phase": phase, "numGames": num_games},
        "games": [{"season": season, "gid": i} for i in range(n_games)],
    }


def _odds(po=0.5, champ=0.1, finals=0.2, proj_w=22.5):
    return {
        "teams": {
            0: {"po": po, "finals": finals, "champ": champ, "proj_w": proj_w, "games_left": 10},
            1: {"po": 1 - po, "finals": 0.3, "champ": 0.05, "proj_w": 20.0, "games_left": 10},
        },
        "stakes": [],
        "day": 5,
        "fresh": False,
    }


class OddsLedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "league-data", "odds_history.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_file_created_when_absent(self):
        self.assertFalse(os.path.exists(self.path))
        appended = update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path)
        self.assertTrue(appended)
        self.assertTrue(os.path.exists(self.path))
        history = load_odds_history(self.path)
        self.assertEqual(len(history), 1)
        snap = history[0]
        self.assertEqual(snap["season"], 2031)
        self.assertEqual(snap["phase"], 1)
        self.assertEqual(snap["games_played"], 5)
        self.assertEqual(set(snap["teams"].keys()), {"0", "1"})
        team0 = snap["teams"]["0"]
        self.assertEqual(set(team0.keys()), {"po", "title", "finals", "proj_w", "proj_l"})
        self.assertAlmostEqual(team0["po"], 0.5)
        self.assertAlmostEqual(team0["title"], 0.1)  # champ -> title
        self.assertAlmostEqual(team0["finals"], 0.2)
        self.assertAlmostEqual(team0["proj_w"], 22.5)
        self.assertAlmostEqual(team0["proj_l"], 45 - 22.5)

    def test_append_advances(self):
        update_odds_ledger(_export(2031, 1, 5), _odds(po=0.5), path=self.path)
        appended = update_odds_ledger(_export(2031, 1, 12), _odds(po=0.7), path=self.path)
        self.assertTrue(appended)
        history = load_odds_history(self.path)
        self.assertEqual([s["games_played"] for s in history], [5, 12])
        self.assertAlmostEqual(history[1]["teams"]["0"]["po"], 0.7)

    def test_duplicate_key_noop(self):
        update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path)
        with open(self.path, "rb") as handle:
            before = handle.read()
        appended = update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path)
        self.assertFalse(appended)
        with open(self.path, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after)  # byte-identical: idempotent rebuilds
        self.assertEqual(len(load_odds_history(self.path)), 1)

    def test_duplicate_key_refreshes_changed_odds(self):
        # Same (season, phase, games_played) but different odds — e.g. a
        # re-export after a preseason roster move: refresh in place, no dupe.
        update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path)
        update_odds_ledger(_export(2031, 1, 5), _odds(po=0.9), path=self.path)
        history = load_odds_history(self.path)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["teams"]["0"]["po"], 0.9)

    def test_older_key_noop(self):
        update_odds_ledger(_export(2031, 1, 12), _odds(), path=self.path)
        self.assertFalse(update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path))
        self.assertFalse(update_odds_ledger(_export(2030, 3, 40), _odds(), path=self.path))
        self.assertEqual(len(load_odds_history(self.path)), 1)

    def test_cross_season_ordering(self):
        update_odds_ledger(_export(2030, 1, 40), _odds(), path=self.path)
        update_odds_ledger(_export(2030, 3, 45), _odds(), path=self.path)
        # New season: games list resets to fewer games, but season advances.
        appended = update_odds_ledger(_export(2031, 0, 3), _odds(), path=self.path)
        self.assertTrue(appended)
        history = load_odds_history(self.path)
        keys = [(s["season"], s["phase"], s["games_played"]) for s in history]
        self.assertEqual(keys, [(2030, 1, 40), (2030, 3, 45), (2031, 0, 3)])
        self.assertEqual(keys, sorted(keys))

    def test_phase_advances_within_season(self):
        update_odds_ledger(_export(2031, 1, 45), _odds(), path=self.path)
        appended = update_odds_ledger(_export(2031, 3, 45), _odds(), path=self.path)
        self.assertTrue(appended)
        self.assertEqual([s["phase"] for s in load_odds_history(self.path)], [1, 3])

    def test_load_missing_or_invalid(self):
        self.assertEqual(load_odds_history(self.path), [])
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("not json{")
        self.assertEqual(load_odds_history(self.path), [])

    def test_deterministic_serialization(self):
        update_odds_ledger(_export(2031, 1, 5), _odds(), path=self.path)
        with open(self.path, "rb") as handle:
            first = handle.read()
        other = os.path.join(self.dir, "other.json")
        update_odds_ledger(_export(2031, 1, 5), _odds(), path=other)
        with open(other, "rb") as handle:
            second = handle.read()
        self.assertEqual(first, second)
        # Human-readable, ends with newline, parses as a JSON list.
        self.assertTrue(first.endswith(b"\n"))
        self.assertIsInstance(json.loads(first.decode("utf-8")), list)

    def test_empty_odds_noop(self):
        self.assertFalse(update_odds_ledger(_export(2031, 1, 5), {"teams": {}}, path=self.path))
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
