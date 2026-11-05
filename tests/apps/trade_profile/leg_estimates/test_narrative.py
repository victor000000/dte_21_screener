"""Tests for the narrative — the "read" printed under the per-leg table.

This is the function that turns numbers into the sentences a decision is made
from ("these are closes, not holds"), so its thresholds are behaviour, not
formatting. It is pure: no database, no network, no globals.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

# Import the FUNCTION, not the submodule: the package __init__ re-exports the
# function under the same name, so `from ... import narrative` resolves to the
# function (which is the public API the shim promises). The submodule is still
# reachable as `apps.trade_profile.leg_estimates.narrative` only via importlib
# once the package attribute has been shadowed -- which is fine, nothing needs it.
from apps.trade_profile.leg_estimates.narrative import narrative
from apps.trade_profile.leg_estimates.constants import HARVEST, NEAR, STALE


def leg(underlying="EWZ", **kw):
    """A collected row with only the fields the narrative reads."""
    row = {"underlying": underlying, "leg": "43C", "broker": "Schwab", "qty": -50,
           "sec_type": "OPT", "pnl_mark": 0.0, "pnl_est": 0.0, "delta": 0.0}
    row.update(kw)
    return row


class TestHarvestLine(unittest.TestCase):
    def test_above_the_target_is_called_a_close(self):
        out = "\n".join(narrative([leg(pnl_est=HARVEST + 14.0)], {}))
        self.assertIn("closes, not holds", out)
        self.assertIn("+64.0%", out)

    def test_exactly_at_the_target_counts_as_over(self):
        # >=, not >: the rule is "captured half the credit", and exactly half is half.
        out = "\n".join(narrative([leg(pnl_est=HARVEST)], {}))
        self.assertIn("closes, not holds", out)

    def test_below_the_target_says_so_instead_of_staying_silent(self):
        out = "\n".join(narrative([leg(pnl_est=HARVEST - 0.1)], {}))
        self.assertIn("Nothing is past the 50% target yet", out)

    def test_names_the_mark_gap_when_the_mark_disagrees(self):
        # The case this report exists for: on the stored mark alone you would not
        # have flagged the leg, because the underlying moved and the mark has not.
        out = "\n".join(narrative(
            [leg(pnl_est=+64.0, pnl_mark=+44.0)], {}))
        self.assertIn("the mark has not caught up", out)

    def test_no_mark_gap_sentence_when_the_mark_agrees(self):
        out = "\n".join(narrative([leg(pnl_est=+64.0, pnl_mark=+56.0)], {}))
        self.assertNotIn("has not caught up", out)


class TestApproaching(unittest.TestCase):
    def test_inside_the_near_band_is_listed(self):
        out = "\n".join(narrative([leg(pnl_est=HARVEST - NEAR + 1.0)], {}))
        self.assertIn("Approaching it", out)

    def test_outside_the_near_band_is_not(self):
        out = "\n".join(narrative([leg(pnl_est=HARVEST - NEAR - 1.0)], {}))
        self.assertNotIn("Approaching it", out)

    def test_a_harvested_leg_is_not_also_approaching(self):
        # The bands must not overlap, or one leg appears twice with two verdicts.
        out = "\n".join(narrative([leg(pnl_est=HARVEST + 1.0)], {}))
        self.assertNotIn("Approaching it", out)


if __name__ == "__main__":
    unittest.main()
