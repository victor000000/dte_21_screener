"""test_iv_rank.py — one ranker, two callers, and they must agree.

The download filter (build_screen_universe) and the screen (screener_21dte_v2) both decide
scope from this, so a disagreement is not cosmetic: the filter would admit names the screen
then reports as PASS, or the reverse. The rules are the user's (2026-10-04) — rank the LATEST
IV inside its OWN source's series, never pool sources, and answer None rather than guess when
the series is too short.
"""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from compute.iv_rank import MIN_POINTS, SOURCE_RANK, percentile, rank_series  # noqa: E402


def rows(ivs, source="ibkr_tws30d"):
    """(source, day, iv) triples -- rank_series' real input shape, not (underlying, ...)."""
    d0 = dt.date(2026, 1, 1)
    return [(source, d0 + dt.timedelta(days=i), iv) for i, iv in enumerate(ivs)]


class TestPercentile(unittest.TestCase):
    def test_it_counts_values_AT_OR_BELOW(self):
        self.assertEqual(percentile([1, 2, 3, 4], 4), 100.0)
        self.assertEqual(percentile([1, 2, 3, 4], 1), 25.0)   # inclusive: the 1 counts
        self.assertEqual(percentile([1, 2, 3, 4], 0), 0.0)

    def test_a_single_value_series_is_not_a_division_by_zero(self):
        self.assertEqual(percentile([5.0], 5.0), 100.0)


class TestRankSeries(unittest.TestCase):
    def test_the_latest_high_ranks_at_the_top(self):
        got = rank_series(rows([0.10 + i * 0.001 for i in range(MIN_POINTS)]))
        self.assertEqual(got["ivr"], 100)

    def test_the_latest_low_ranks_at_the_bottom(self):
        got = rank_series(rows([0.90 - i * 0.001 for i in range(MIN_POINTS)]))
        self.assertLess(got["ivr"], 5, "the lowest value in its own series")

    def test_too_short_a_series_is_None_rather_than_a_guess(self):
        got = rank_series(rows([0.2] * (MIN_POINTS - 1)))
        self.assertIsNone(got["ivr"], "a short series must not be ranked off a proxy")
        self.assertIn("needs", got["kind"], "and the reason is carried, not just the None")

    def test_no_rows_at_all_is_None(self):
        self.assertIsNone(rank_series([]))

    def test_sources_are_never_pooled(self):
        """A 3-row live panel and a 500-row daily series are different measurements."""
        mixed = rows([0.10, 0.20, 0.30], source="futu_panel")
        mixed += rows([0.30] * (MIN_POINTS - 1) + [0.90], source="ibkr_tws30d")
        got = rank_series(mixed)
        self.assertEqual(got["source"], SOURCE_RANK[1], "futu_panel is too short to be ranked")
        self.assertEqual(got["ivr"], 100, "ranked inside its own series, not across both")

    def test_a_NaN_latest_IV_is_unrankable_not_the_lowest(self):
        """Every comparison against NaN is False, so the percentile would read 0.0 -- 'the
        lowest IVR in its own history' -- where the truth is 'no usable latest value'."""
        got = rank_series(rows([0.2] * (MIN_POINTS - 1) + [float("nan")]))
        self.assertIsNone(got["iv"])
        self.assertIsNone(got["ivr"])
        self.assertIn("NaN", got["kind"])
