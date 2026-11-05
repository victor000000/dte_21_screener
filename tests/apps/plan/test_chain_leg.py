"""One option's price from the chain, and what the last two elements promise.

`is_book` (third): True = an OBSERVATION the caller may use as current; False = a stale
last trade it must reprice at the live spot. Fourth is the quote `(bid, ask)`, which the
report needs to say what closing would cost. See test_chain_leg_refusals for the shapes
this refuses.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import pandas as pd

from apps.plan import chain_leg


class FakeChain:
    def __init__(self, rows):
        self.calls = pd.DataFrame(rows)
        self.puts = pd.DataFrame(rows)


class FakeTicker:
    """Stands in for yf.Ticker, returning one chain row."""

    def __init__(self, row):
        self.row = row

    def option_chain(self, exp):
        return FakeChain([self.row])


def leg(row, strike=100.0):
    """(price, iv, is_book) or None -- the function returns None, not a tuple, when the
    chain has no row for the strike at all."""
    chain_leg._chain_cache.clear()
    import yfinance as yf
    original = yf.Ticker
    yf.Ticker = lambda u: FakeTicker(row)
    try:
        return chain_leg.yf_leg("TEST", "2026-11-20", strike, "P")
    finally:
        yf.Ticker = original


class TestABookIsAnObservation(unittest.TestCase):
    def test_a_two_sided_quote_returns_the_mid(self):
        px, iv, is_book, _q = leg({"strike": 100.0, "bid": 2.00, "ask": 2.40,
                               "impliedVolatility": 0.55, "lastPrice": 2.1})
        self.assertAlmostEqual(px, 2.20)
        self.assertTrue(is_book, "a live two-sided book is an observation")
        self.assertAlmostEqual(iv, 0.55)


class TestItHandsBackTheQuote(unittest.TestCase):
    def test_a_book_returns_both_sides(self):
        # The callers need the ASK: you buy a short back at it, so on a wide market the
        # mid overstates what closing realises -- CRWD's 225P was $2,492 against $1,742.
        _px, _iv, is_book, q = leg({"strike": 100.0, "bid": 2.00, "ask": 2.40,
                                    "impliedVolatility": 0.55, "lastPrice": 2.1})
        self.assertTrue(is_book)
        self.assertEqual(q, (2.00, 2.40))

    def test_a_last_trade_returns_no_quote(self):
        # No market to quote means no spread to report.
        _px, _iv, is_book, q = leg({"strike": 100.0, "bid": 0.0, "ask": 0.0,
                                    "impliedVolatility": 0.5, "lastPrice": 2.38})
        self.assertFalse(is_book)
        self.assertIsNone(q)


if __name__ == "__main__":
    unittest.main()
