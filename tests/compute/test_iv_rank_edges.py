"""IVR windows, distinct trading dates and source eligibility."""
import datetime as dt
import unittest

from compute.iv_rank import rank_series, range_rank
from tests.compute.test_iv_rank import rows
from apps.screener.cn_iv import board, windows


class TestIVRankEdges(unittest.TestCase):
    def test_old_spike_does_not_affect_default_252_session_rank(self):
        data = rows([2.0] + [0.1] * 251 + [0.2])
        self.assertAlmostEqual(rank_series(data)["ivr"], 100.0)
        self.assertAlmostEqual(rank_series(data, lookback=None)["ivr"], 100 / 19)

    def test_duplicate_rows_do_not_make_60_daily_points(self):
        result = rank_series(rows([0.1, 0.2]) * 30)
        self.assertIsNone(result["ivr"])
        self.assertEqual(result["n"], 2)
        self.assertIn("partial history", result["kind"])

    def test_conflicting_daily_observations_are_not_arbitrarily_ranked(self):
        data = rows([0.1] * 59 + [0.2])
        data.append((data[-1][0], data[-1][1], 0.3))
        self.assertIsNone(rank_series(data)["ivr"])

    def test_flat_preferred_source_does_not_hide_usable_alternative(self):
        data = rows([0.1] * 60, "futu_panel") + rows([0.1] * 59 + [0.2], "alpaca_atm")
        result = rank_series(data)
        self.assertEqual(result["source"], "alpaca_atm")
        self.assertEqual(result["ivr"], 100.0)

    def test_invalid_history_outside_window_does_not_poison_current_rank(self):
        data = rows([float("nan")] + [0.1] * 251 + [0.2])
        self.assertEqual(rank_series(data)["ivr"], 100.0)

    def test_impossible_iv_or_value_outside_window_is_unrankable(self):
        for values, current in (([0.0, 0.2], 0.2), ([-0.1, 0.2], 0.2),
                                ([0.1, 0.2], 0.3), ([0.1, 0.2], 0.05)):
            with self.subTest(values=values, current=current):
                self.assertIsNone(range_rank(values, current))

    def test_cn_full_rank_still_uses_full_history(self):
        data = rows([2.0] + [0.1] * 251 + [0.2], "s")
        points = [(day, iv) for _, day, iv in data]
        result = board.build_board([("SR", "CZCE", "sugar")], {"SR": {"s": points}}, {})
        self.assertAlmostEqual(result[0]["res"]["ivr"], 100 / 19)

    def test_cn_source_choice_checks_usable_rank(self):
        flat = [(d, v) for _, d, v in rows([0.2] * 100)]
        usable = [(d, v) for _, d, v in rows([0.1] * 59 + [0.2])]
        self.assertEqual(board.pick_series({"flat": flat, "usable": usable})[0], "usable")

    def test_unrankable_cn_product_never_passes_a_zero_threshold(self):
        points = [(d, v) for _, d, v in rows([0.2] * 60)]
        result = board.build_board([("SR", "CZCE", "sugar")], {"SR": {"s": points}}, {})
        text = board.render(result, points[-1][0], 0)
        self.assertIn("Pass at IVR >= 0: 0 of 0 rankable", text)
        self.assertIn("pending", text)

    def test_cn_missing_dates_are_unrankable_without_crashing(self):
        result = board.build_board([("SR", "CZCE", "sugar")], {"SR": {"s": [(None, 0.2)]}}, {})
        self.assertIsNone(result[0]["res"])

    def test_cn_window_deduplicates_dates(self):
        end = dt.date(2026, 10, 16)
        points = [(end - dt.timedelta(days=365), 0.1), (end, 0.2)] * 60
        result = windows.rank_windows(points)["1Y"]
        self.assertIsNone(result["ivr"])
        self.assertEqual(result["n"], 1)


if __name__ == "__main__":
    unittest.main()
