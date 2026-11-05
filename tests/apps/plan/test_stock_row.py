"""The stock branch of the book build: what it does with a missing price.

`float('nan') or avg` returns nan, because bool(nan) is True -- so a halted ticker
used to write NaN into spot/mark/delta_notional_usd and poison the whole scenario
ladder. These are the cases that fix that. See test_stock_row_shape for the columns.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan import stock_row


class FakeCon:
    def __init__(self):
        self.sql = self.params = None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params


SECTOR = ("Equity", "Tech", "Software", "Systems Software")


def run(spot_for_returns, avg=100.0, qty=-10):
    con = FakeCon()
    got = stock_row.insert(con, "acct", "Schwab", "XYZ", qty, avg,
                           spot_for=lambda c, u: spot_for_returns,
                           spot_meta=lambda u: {"source": "alpaca", "quote_class": "live",
                                                "is_realtime": True},
                           sector={"XYZ": SECTOR})
    return con, got


class TestTheSpotIsNeverNaN(unittest.TestCase):
    def test_a_nan_spot_falls_back_to_the_entry(self):
        # THE regression. A halted or delisted ticker gives nan; `nan or avg` is nan.
        con, got = run(float("nan"), avg=42.5)
        self.assertEqual(got, 42.5)
        self.assertEqual(con.params[9], 42.5)          # spot
        self.assertEqual(con.params[11], 42.5)         # mark
        self.assertEqual(con.params[16], -10 * 42.5)   # delta_notional

    def test_a_zero_spot_falls_back_to_the_entry(self):
        _, got = run(0.0, avg=42.5)
        self.assertEqual(got, 42.5)

    def test_a_real_spot_wins(self):
        _, got = run(37.25)
        self.assertEqual(got, 37.25)


class TestALegWithNoPriceIsSkippedNotWritten(unittest.TestCase):
    def test_a_nan_spot_and_no_entry_writes_nothing(self):
        # Returns None so the caller does not count the row. A leg with a NULL spot
        # in the book is a position with zero risk, which reads as safety.
        con, got = run(float("nan"), avg=None)
        self.assertIsNone(got)
        self.assertIsNone(con.sql)

    def test_a_spot_of_none_with_no_entry_writes_nothing(self):
        con, got = run(None, avg=None)
        self.assertIsNone(got)
        self.assertIsNone(con.sql)
