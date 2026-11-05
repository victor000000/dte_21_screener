"""Tests for the broker option marks that replaced a stale lastPrice.

The live path needs a gateway, so most of this is the CONTRACT: what counts as a
usable quote, what happens when the broker is unreachable, and that a bad quote
falls through rather than being written. The shape assertions are what caught
the real defect -- ``option_marks`` wants a date and the book stores a string,
and the AttributeError was swallowed into "no broker quotes this run", which
reads exactly like a gateway that is down.
"""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan import broker_marks


class TestQuoteFiltering(unittest.TestCase):
    """_usable is the whole rule; exercise it without a broker."""

    @staticmethod
    def usable(bid, ask):
        return bool(bid and ask and ask >= bid > 0)

    def test_a_two_sided_quote_is_usable(self):
        self.assertTrue(self.usable(2.03, 2.29))

    def test_a_zero_bid_is_not(self):
        # IB returns 0 where it has nothing. yfinance does the same, and that is
        # precisely how the book ended up priced off `lastPrice`.
        self.assertFalse(self.usable(0.0, 2.29))

    def test_a_zero_ask_is_not(self):
        self.assertFalse(self.usable(2.03, 0.0))

    def test_a_crossed_book_is_not(self):
        # bid > ask is a data fault, not a market. yfinance served CRWD as
        # 272.09 / 272.00 on this book and it was correctly refused.
        self.assertFalse(self.usable(2.29, 2.03))

    def test_a_one_sided_quote_is_not(self):
        self.assertFalse(self.usable(None, 2.29))


class TestExpiryNormalisation(unittest.TestCase):
    def test_a_string_expiry_becomes_a_date_before_the_call(self):
        # THE regression. `US` stores '2026-11-20'; option_marks calls strftime on
        # it. The AttributeError was caught by the broad except and reported as
        # "no broker quotes", so the book silently kept using Monday's close.
        seen = {}

        def fake_option_marks(legs, client_id=0):
            seen["legs"] = list(legs)
            return {}

        import datasources.tws as real_tws
        original = real_tws.option_marks
        real_tws.option_marks = fake_option_marks
        try:
            broker_marks.tws_option_marks([("EWZ", "2026-12-18", 43.0, "P")])
        finally:
            real_tws.option_marks = original
        self.assertEqual(seen["legs"][0][1], dt.date(2026, 12, 18))

    def test_an_empty_leg_list_returns_empty_without_connecting(self):
        self.assertEqual(broker_marks.tws_option_marks([]), {})


class TestFailureIsNotEmptyTruthy(unittest.TestCase):
    def test_an_unreachable_broker_returns_an_empty_mapping(self):
        # Never None and never raises: callers do `.get()` on the result, and an
        # exception here would take the whole book build down over a quote.
        import datasources.tws as real_tws
        original = real_tws.option_marks

        def boom(*a, **k):
            raise ConnectionError("no gateway")

        real_tws.option_marks = boom
        try:
            self.assertEqual(broker_marks.tws_option_marks([("EWZ", "2026-12-18", 43.0, "P")]), {})
        finally:
            real_tws.option_marks = original


if __name__ == "__main__":
    unittest.main()
