"""The no-book branch: a last trade is not an observation.

Outside the option's own session yfinance has no two-sided quote, and `lastPrice` carries
the previous session's CLOSE. That is a real price and a stale one, so the caller must
reprice it at the live spot -- which is what `is_book=False` tells it to do.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from tests.apps.plan.test_chain_leg import leg


class TestNoBookFallsBackToTheLastTrade(unittest.TestCase):
    def test_a_zero_bid_is_not_a_book(self):
        # yfinance serves bid 0 outside regular hours. `bid and ask` is falsy, so the mid
        # is None and this takes the last-trade branch.
        px, iv, is_book, _q = leg({"strike": 100.0, "bid": 0.0, "ask": 0.0,
                               "impliedVolatility": 0.5, "lastPrice": 2.38})
        self.assertAlmostEqual(px, 2.38)
        self.assertFalse(is_book, "a last trade must be repriced by the caller")
        self.assertIsNone(iv, "no book means no vol to quote")

    def test_a_one_sided_quote_is_not_a_book(self):
        # `broker_marks` refuses this shape as a data fault, and accepting it here would
        # undo that: the broker rejects the quote, the chain is asked second, and a lone
        # bid would come back as a current observation.
        px, _iv, is_book, _q = leg({"strike": 100.0, "bid": 2.0, "ask": 0.0,
                                "impliedVolatility": 0.5, "lastPrice": 2.1})
        self.assertFalse(is_book, "one side is not a market")
        self.assertAlmostEqual(px, 2.1, "so it falls back to the last trade")

    def test_a_crossed_quote_is_not_a_book_either(self):
        px, _iv, is_book, _q = leg({"strike": 100.0, "bid": 2.4, "ask": 2.0,
                                "impliedVolatility": 0.5, "lastPrice": 2.1})
        self.assertFalse(is_book)


if __name__ == "__main__":
    unittest.main()
