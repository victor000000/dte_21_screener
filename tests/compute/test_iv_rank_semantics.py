"""IV rank measures the position in a range; IV percentile measures frequency."""
import datetime as dt
import unittest

from compute import iv_rank
from apps.screener.cn_iv.windows import rank_windows
from tests.compute.test_iv_rank import rows


class TestIVRankSemantics(unittest.TestCase):
    def test_skewed_series_separates_rank_from_percentile(self):
        result = iv_rank.rank_series(rows([0.1] * 58 + [1.1, 0.2]))
        self.assertAlmostEqual(result["ivr"], 10.0)
        self.assertAlmostEqual(result["ivp"], 59 / 60 * 100)

    def test_latest_low_has_zero_rank_but_nonzero_percentile(self):
        result = iv_rank.rank_series(rows([0.5] * 59 + [0.1]))
        self.assertEqual(result["ivr"], 0.0)
        self.assertAlmostEqual(result["ivp"], 100 / 60)

    def test_flat_range_is_unrankable_but_percentile_is_defined(self):
        result = iv_rank.rank_series(rows([0.2] * 60))
        self.assertIsNone(result["ivr"])
        self.assertEqual(result["ivp"], 100.0)
        self.assertIn("flat", result["kind"])

    def test_range_rank_handles_empty_flat_and_invalid_inputs(self):
        for values, current in (([], 0.2), ([0.2], 0.2), ([0.2, 0.2], 0.2),
                                ([0.1, float("nan")], 0.2),
                                ([0.1, 0.5], float("inf"))):
            with self.subTest(values=values, current=current):
                self.assertIsNone(iv_rank.range_rank(values, current))
        self.assertAlmostEqual(iv_rank.range_rank([0.1, 1.1], 0.2), 10.0)

    def test_cn_window_uses_range_rank(self):
        end = dt.date(2026, 10, 16)
        values = [0.1] * 398 + [1.1, 0.2]
        series = [(end - dt.timedelta(days=399 - i), value) for i, value in enumerate(values)]
        result = rank_windows(series)
        self.assertAlmostEqual(result["1Y"]["ivr"], 10.0)

    def test_flat_cn_window_is_unrankable(self):
        end = dt.date(2026, 10, 16)
        series = [(end - dt.timedelta(days=i), 0.2) for i in range(400)]
        self.assertIsNone(rank_windows(series)["1Y"]["ivr"])


if __name__ == "__main__":
    unittest.main()
