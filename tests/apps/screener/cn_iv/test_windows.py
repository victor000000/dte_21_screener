"""test_windows.py — per-horizon IVR over one product's own series."""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from apps.screener.cn_iv import windows as W  # noqa: E402
from compute.iv_rank import MIN_POINTS  # noqa: E402

DAY = dt.date(2026, 9, 30)


def series(n, end=DAY, step_days=1):
    """n points ending at `end`, IV rising from 0.10 — so the latest is the series maximum."""
    return [(end - dt.timedelta(days=step_days * (n - 1 - i)), 0.10 + i * 0.001)
            for i in range(n)]


class TestRankWindows(unittest.TestCase):
    def test_a_covered_window_ranks_only_that_window(self):
        # 1,100 daily points. A rising series makes the latest the maximum, so the 1Y column
        # reads 100 only if the window really was the 365 days and not the whole series.
        w = W.rank_windows(series(1100))
        self.assertTrue(w["1Y"]["covered"])
        self.assertEqual(w["1Y"]["n"], 365)
        self.assertEqual(w["1Y"]["ivr"], 100.0)

    def test_a_window_the_history_cannot_cover_is_never_a_number(self):
        # ~1.4 years stored: 2Y is not a 2-year reading, so it must not produce a rank
        # that would print beside a genuine one and be indistinguishable from it.
        w = W.rank_windows(series(500))
        self.assertTrue(w["1Y"]["covered"])
        self.assertFalse(w["2Y"]["covered"])
        self.assertIsNone(w["2Y"]["ivr"])
        self.assertIsNone(w["10Y"]["ivr"])

    def test_a_covered_but_thin_window_is_not_ranked(self):
        # Monthly-ish points over two years: the window is covered by DATE but holds too few
        # observations to rank, which is a different answer from "covered".
        w = W.rank_windows(series(36, step_days=20))
        self.assertTrue(w["1Y"]["covered"])
        self.assertLess(w["1Y"]["n"], MIN_POINTS)
        self.assertIsNone(w["1Y"]["ivr"])

    def test_asof_is_the_data_day_not_todays_clock(self):
        # This series stopped in Jan 2025. Measured from today's clock a 1Y window would be
        # EMPTY and uncovered; measured from its own last day it is a full year.
        w = W.rank_windows(series(400, end=dt.date(2025, 1, 1)))
        self.assertTrue(w["1Y"]["covered"])
        self.assertEqual(w["1Y"]["ivr"], 100.0)

    def test_asof_excludes_days_after_it(self):
        # A collapse printed after the day being ranked must not enter that day's window, nor
        # become the value the window is ranked against.
        later = DAY + dt.timedelta(days=1)
        rows = series(400) + [(later, 0.01)]
        self.assertEqual(W.rank_windows(rows, asof=DAY)["1Y"]["ivr"], 100.0)
        self.assertLess(W.rank_windows(rows)["1Y"]["ivr"], 1.0)

    def test_no_rows_no_windows(self):
        self.assertEqual(W.rank_windows([]), {})


if __name__ == "__main__":
    unittest.main()
