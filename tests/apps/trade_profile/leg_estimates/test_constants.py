"""Tests for the leg_estimates thresholds."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.leg_estimates import constants as C


class TestThresholds(unittest.TestCase):
    def test_harvest_is_the_users_fifty_percent_rule(self):
        # The user's own close rule. If this moves, every "these are closes" line
        # in the narrative moves with it, so pin it explicitly.
        self.assertEqual(C.HARVEST, 50.0)

    def test_near_band_is_inside_the_target(self):
        # "Approaching" must be a band BELOW the target; a NEAR larger than
        # HARVEST would make the band start below zero and sweep in winners.
        self.assertGreater(C.NEAR, 0)
        self.assertLess(C.NEAR, C.HARVEST)

    def test_stale_is_positive(self):
        # A zero or negative STALE would make every leg "disagreeing".
        self.assertGreater(C.STALE, 0)

    def test_rate_is_the_shared_one(self):
        # The split must not have re-introduced a private copy of the rate.
        from shared.rates import R_US
        self.assertIs(C.R, R_US)


if __name__ == "__main__":
    unittest.main()
