"""Tests for scripts/smp/pages/extras.py (rivalries + classics pages)."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.pages import extras  # noqa: E402


def _team(tid, abbrev, region, name):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name}


def _game(gid, day, season, home_tid, home_pts, home_q, away_tid, away_pts, away_q,
          overtimes=0, playoffs=False):
    return {
        "gid": gid,
        "day": day,
        "season": season,
        "overtimes": overtimes,
        "playoffs": playoffs,
        "clutchPlays": [],
        "teams": [
            {"tid": home_tid, "pts": home_pts, "ptsQtrs": home_q},
            {"tid": away_tid, "pts": away_pts, "ptsQtrs": away_q},
        ],
    }


def _mini_data():
    """3-team league: 2026/2027 head-to-heads, 2027 retained games, one trade."""
    return {
        "gameAttributes": {"season": 2028, "phase": 0},
        "players": [],
        "teams": [
            _team(0, "AAA", "Alpha", "Aces"),
            _team(1, "BBB", "Beta", "Bears"),
            _team(2, "CCC", "Gamma", "Cats"),
        ],
        "headToHeads": [
            {
                "season": 2026,
                "regularSeason": {
                    "0": {
                        "1": {"won": 2, "lost": 1, "pts": 310, "oppPts": 290},
                        "2": {"won": 3, "lost": 0, "pts": 330, "oppPts": 270},
                    },
                    "1": {"2": {"won": 1, "lost": 2, "pts": 300, "oppPts": 305}},
                },
                "playoffs": {
                    "0": {"1": {"round": 0, "result": "won", "won": 2, "lost": 1, "pts": 210, "oppPts": 200}},
                },
            },
            {
                "season": 2027,
                "regularSeason": {
                    "0": {
                        "1": {"won": 2, "lost": 1, "pts": 330, "oppPts": 296},
                        "2": {"won": 0, "lost": 1, "pts": 88, "oppPts": 90},
                    },
                    "1": {"2": {"won": 2, "lost": 1, "pts": 310, "oppPts": 300}},
                },
                "playoffs": {
                    "0": {"1": {"round": 0, "result": "lost", "won": 0, "lost": 1, "pts": 95, "oppPts": 105}},
                },
            },
        ],
        "playoffSeries": [
            {
                "season": 2026,
                "series": [[{
                    "home": {"tid": 0, "seed": 1, "won": 2, "pts": 210},
                    "away": {"tid": 1, "seed": 2, "won": 1, "pts": 200},
                    "gids": [90, 91, 92],
                }]],
            },
        ],
        "games": [
            # AAA over BBB by 10, then a 30-point AAA blowout, then two BBB wins.
            _game(1, 1, 2027, 0, 110, [28, 27, 27, 28], 1, 100, [25, 25, 25, 25]),
            _game(2, 2, 2027, 1, 90, [22, 23, 22, 23], 0, 120, [30, 30, 30, 30]),
            # BBB trailed by 12 entering the 3rd and came back to win by 2.
            _game(3, 3, 2027, 0, 97, [30, 27, 20, 20], 1, 99, [20, 25, 20, 34]),
            _game(4, 5, 2027, 1, 105, [26, 26, 26, 27], 0, 95, [24, 24, 24, 23], playoffs=True),
        ],
        "playerFeats": [
            {"gid": 3, "season": 2027, "name": "Test Star", "pid": 77, "tid": 1,
             "stats": {"pts": 45, "td": 0, "dd": 1}},
        ],
        "events": [
            {
                "type": "trade", "season": 2027, "eid": 5, "tids": [0, 1],
                "teams": [
                    {"assets": [{"pid": 11, "name": "Player One"}]},
                    {"assets": [{"dpid": 1, "season": 2028, "round": 1, "originalTid": 0}]},
                ],
            },
        ],
        "seasonLeaders": [],
    }


class TestRenderExtrasPages(unittest.TestCase):
    def setUp(self):
        self.data = _mini_data()
        self.teams = self.data["teams"]
        self.pages = extras.render_extras_pages(self.data, self.teams)

    def test_output_filenames(self):
        # grid + classics + C(3,2)=3 pair pages, pair slugs ordered by tid
        self.assertIn("rivalries.html", self.pages)
        self.assertIn("classics.html", self.pages)
        pair_keys = sorted(k for k in self.pages if k.startswith("rivalries/"))
        self.assertEqual(pair_keys, [
            "rivalries/alpha-aces-0-vs-beta-bears-1.html",
            "rivalries/alpha-aces-0-vs-gamma-cats-2.html",
            "rivalries/beta-bears-1-vs-gamma-cats-2.html",
        ])
        self.assertEqual(len(self.pages), 5)

    def test_grid_records_and_diagonal(self):
        grid = self.pages["rivalries.html"]
        # AAA vs BBB all-time incl. playoffs: (2+1) + (2+0) = 6 wins, (1+1)+(1+1) = 4 losses
        self.assertIn(">6-4</a>", grid)
        self.assertEqual(grid.count('class="rv-diag"'), 3)
        # every cell links to a rendered pair page
        for key in self.pages:
            if key.startswith("rivalries/"):
                self.assertIn(f'href="{key}"', grid)
        # team chips carry team colors and abbrevs
        self.assertIn("--team-primary:", grid)
        self.assertIn(">AAA</a>", grid)

    def test_pair_page_content(self):
        pair = self.pages["rivalries/alpha-aces-0-vs-beta-bears-1.html"]
        # root-relative assets from the rivalries/ subdirectory
        self.assertIn('href="../assets/styles.css"', pair)
        self.assertIn("Alpha Aces lead the all-time series 6-4", pair)
        # streak: BBB won meetings on day 3 and day 5 (playoffs)
        self.assertIn("Beta Bears has won 2 straight in the series.", pair)
        # extremes from retained games
        self.assertIn("Biggest blowout", pair)
        self.assertIn("margin 30", pair)
        self.assertIn("Closest game", pair)
        self.assertIn("margin 2", pair)
        # honest retention note (single retained season, one sentence)
        self.assertIn("Game details cover retained box scores (2027)", pair)
        # playoff series from playoffSeries with round name and result
        self.assertIn("2026 Finals", pair)
        self.assertIn("won 2-1", pair)
        # trade history between the pair
        self.assertIn("Player One", pair)
        # meeting log links to game pages that exist (2027 regular season AND
        # 2027 playoffs — build.py also writes pages for the latest completed
        # game season's playoff games)
        self.assertIn('href="../games/1.html"', pair)
        self.assertIn('href="../games/4.html"', pair)

    def test_pair_page_without_history(self):
        pair = self.pages["rivalries/beta-bears-1-vs-gamma-cats-2.html"]
        self.assertIn("never met in the playoffs", pair)
        self.assertIn("No trades on record", pair)

    def test_classics_ranking_and_blurbs(self):
        classics = self.pages["classics.html"]
        # game 3 (2-point comeback win with a feat) is the most dramatic
        first_anchor = classics.index('<article class="cl-game')
        self.assertIn('id="g3"', classics[first_anchor:first_anchor + 200])
        # factual blurb: comeback size + boundary + score + feat
        self.assertIn("Down 12 entering the 3rd, BBB stormed back to win 99-97", classics)
        self.assertIn("Test Star finished with 45 points", classics)
        # drama badge + permalink anchor
        self.assertIn('class="cl-badge"', classics)
        self.assertIn('href="#g3"', classics)
        # 4 completed games -> all featured; no honorable-mentions section
        self.assertEqual(classics.count('<article class="cl-game'), 4)
        self.assertNotIn("Honorable Mentions", classics)
        self.assertIn("Top 4 of 4 retained games (2027) by drama index", classics)
        # box-score links for every game that gets a page (incl. last season's playoffs)
        self.assertIn('href="games/3.html"', classics)
        self.assertIn('href="games/4.html"', classics)

    def test_classics_gallery_treatment(self):
        classics = self.pages["classics.html"]
        # top-3 medallions are distinct; the rest share the standard medal
        for cls in ("cl-medal-1", "cl-medal-2", "cl-medal-3"):
            self.assertEqual(classics.count(f'cl-medal {cls}'), 1)
        self.assertEqual(classics.count("cl-medal cl-medal-std"), 1)
        self.assertEqual(classics.count("cl-top3"), 3)
        # drama-score column with a 0-100 meter per game
        self.assertEqual(classics.count('class="cl-drama-num"'), 4)
        self.assertEqual(classics.count("cl-drama-fill"), 4)
        # scoreline typography wraps the matchup score
        self.assertEqual(classics.count('class="cl-scoreline"'), 4)

    def test_deterministic_output(self):
        again = extras.render_extras_pages(_mini_data(), _mini_data()["teams"])
        self.assertEqual(self.pages, again)


class TestHeadToHeadIndex(unittest.TestCase):
    def test_mirroring(self):
        h2h = extras.head_to_head_index(_mini_data())
        fwd = h2h[2026]["regularSeason"][(0, 1)]
        rev = h2h[2026]["regularSeason"][(1, 0)]
        self.assertEqual((fwd["won"], fwd["lost"]), (2.0, 1.0))
        self.assertEqual((rev["won"], rev["lost"]), (1.0, 2.0))
        self.assertEqual(fwd["pts"], rev["oppPts"])

    def test_all_time_record_includes_playoffs(self):
        h2h = extras.head_to_head_index(_mini_data())
        rec = extras.all_time_record(h2h, 0, 1)
        self.assertEqual((rec["won"], rec["lost"]), (6.0, 4.0))


if __name__ == "__main__":
    unittest.main()
