"""Which shapes chain_leg REFUSES, and what it returns when it refuses.

None, not a 3-tuple of Nones: callers write `if leg and spot`, so a tuple of Nones would
sail past that guard and reach the pricing arithmetic -- the `qty * None` crash that once
killed a whole build.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan import chain_leg
from tests.apps.plan.test_chain_leg import FakeTicker, leg


class TestItRefusesRatherThanGuessing(unittest.TestCase):
    def test_a_strike_the_chain_does_not_have_is_none(self):
        # None, not a 3-tuple of Nones: callers test `if leg and spot`.
        # The chain holds strike 100; the leg asks for 999. The ROW must be the miss,
        # not the query -- an earlier version of this test had both at 999 and passed
        # through to the pricing path.
        self.assertIsNone(leg({"strike": 100.0, "bid": 1.0, "ask": 1.2,
                               "impliedVolatility": 0.5, "lastPrice": 1.1},
                              strike=999.0))

    def test_no_book_and_no_last_trade_is_none(self):
        self.assertIsNone(leg({"strike": 100.0, "bid": 0.0, "ask": 0.0,
                               "impliedVolatility": 0.5, "lastPrice": 0.0}))

    def test_a_nan_vol_is_not_passed_through(self):
        # NaN is truthy, so it would sail past `if leg and spot` and turn every greek
        # into NaN, poisoning the scenario ladder exactly as a NaN spot would.
        px, iv, is_book, _q = leg({"strike": 100.0, "bid": 2.0, "ask": 2.4,
                               "impliedVolatility": float("nan"), "lastPrice": 2.2})
        self.assertIsNone(iv, "NaN must arrive as None so the caller solves from the mid")
        self.assertTrue(is_book)


if __name__ == "__main__":
    unittest.main()
