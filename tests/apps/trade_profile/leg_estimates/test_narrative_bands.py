"""Tests for the narrative's loss, staleness and caveat sections.

Split out of test_narrative.py: the test file must stay under 100 lines too, so a
module with this much behaviour gets two. The harness accepts `test_<stem>_*.py`
for exactly this reason.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.leg_estimates.narrative import narrative
from apps.trade_profile.leg_estimates.constants import STALE


def leg(underlying="EWZ", **kw):
    """A collected row with only the fields the narrative reads."""
    row = {"underlying": underlying, "leg": "43C", "broker": "Schwab", "qty": -50,
           "sec_type": "OPT", "pnl_mark": 0.0, "pnl_est": 0.0, "delta": 0.0}
    row.update(kw)
    return row


class TestWorstLoss(unittest.TestCase):
    def test_a_lossing_leg_is_named(self):
        out = "\n".join(narrative([leg("EWZ", pnl_est=-267.9)], {}))
        self.assertIn("The loss that matters", out)
        self.assertIn("-267.9%", out)

    def test_an_all_winner_book_has_no_loss_section(self):
        out = "\n".join(narrative([leg(pnl_est=+10.0)], {}))
        self.assertNotIn("The loss that matters", out)

    def test_the_move_is_quoted_when_the_gap_is_large(self):
        out = "\n".join(narrative(
            [leg("EWZ", pnl_est=-267.9, pnl_mark=-257.0, delta=-10.9)],
            {"EWZ": +12.2}))
        self.assertIn("+12.2%", out)
        self.assertIn("went through the strike", out)

    def test_the_move_is_not_quoted_for_a_small_gap(self):
        out = "\n".join(narrative(
            [leg("EWZ", pnl_est=-10.0, pnl_mark=-10.5, delta=-0.5)], {"EWZ": +1.0}))
        self.assertNotIn("went through the strike", out)


class TestStaleSection(unittest.TestCase):
    def test_gap_at_the_threshold_is_reported(self):
        out = "\n".join(narrative([leg(pnl_mark=0.0, pnl_est=STALE, delta=STALE)], {}))
        self.assertIn("the mark and the model disagree", out)

    def test_gap_below_the_threshold_is_not(self):
        out = "\n".join(narrative(
            [leg(pnl_mark=0.0, pnl_est=STALE - 0.1, delta=STALE - 0.1)], {}))
        self.assertNotIn("the mark and the model disagree", out)

    def test_sorted_by_the_size_of_the_gap(self):
        rows = [leg("AAA", delta=+6.0, pnl_est=1.0), leg("BBB", delta=-30.0, pnl_est=2.0)]
        out = "\n".join(narrative(rows, {}))
        self.assertLess(out.index("BBB"), out.index("AAA"))


class TestCaveatAlwaysPresent(unittest.TestCase):
    def test_the_iv_held_fixed_caveat_is_never_dropped(self):
        # The estimate is a spot-sensitivity, not a price. If this line can go
        # missing, the numbers above it read as quotable.
        for rows in ([leg(pnl_est=+64.0)], [leg(pnl_est=-267.9)], []):
            with self.subTest(rows=len(rows)):
                self.assertIn("holds IV fixed", "\n".join(narrative(rows, {})))


class TestStockRows(unittest.TestCase):
    def test_stock_legs_are_excluded_from_the_option_sections(self):
        # A stock has no strike and no 50% credit; including it would put a
        # meaningless percentage in a list the user acts on.
        out = "\n".join(narrative(
            [leg("IXC", sec_type="STOCK", pnl_est=-99.0)], {}))
        self.assertNotIn("IXC", out)


if __name__ == "__main__":
    unittest.main()
