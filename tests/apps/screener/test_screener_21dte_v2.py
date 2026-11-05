"""The smile window survives a lagging feed, with prices matched by observation day."""
import datetime as dt
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import duckdb  # noqa: E402

from apps.screener import screener_21dte_v2 as core  # noqa: E402
from compute.bs import bs_price  # noqa: E402

SCHEMA = """CREATE SCHEMA mh; CREATE SCHEMA yh;
CREATE TABLE mh.option_bars (source VARCHAR, symbol VARCHAR, underlying VARCHAR, expiry DATE,
    strike DOUBLE, call_put VARCHAR, day DATE, close DOUBLE);
CREATE TABLE yh.prices (symbol TEXT, date DATE, close DOUBLE);
CREATE TABLE mh.underlying_daily (symbol TEXT, day DATE, close DOUBLE)"""
EXPIRY = dt.date(2026, 12, 18)
TODAY = dt.date(2026, 10, 16)


def con_with(rows, spot=100.0):
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    if rows:
        con.executemany("INSERT INTO mh.option_bars VALUES ('s','X',?,?,?,?,?,?)", rows)
        if spot is not None:
            prices = [(u, day, spot) for u, day in {(r[0], r[4]) for r in rows}]
            if prices:
                con.executemany("INSERT INTO yh.prices VALUES (?,?,?)", prices)
    return con


def ladder(asof, spot=100.0, sigma=0.55):
    """A full chain priced from Black-Scholes, so strikes really do land in the 0.16-0.22Δ
    band `nearest` requires. A hand-picked ladder narrow enough to miss the band returns no
    legs and would pass these tests for the wrong reason."""
    T = max((EXPIRY - asof).days, 1) / 365.0
    return [("META", EXPIRY, float(K), cp, asof, bs_price(spot, float(K), T, core.R, sigma, cp == "C"))
            for K in (60, 70, 80, 85, 90, 95, 100, 105, 110, 115, 125, 135) for cp in ("C", "P")]


class TestSmileLegs(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(core.clock, "today", return_value=TODAY))

    def test_a_feed_older_than_the_window_still_yields_legs(self):
        """The regression: bars to 10-02 against a window from 10-05 returned nothing."""
        old = core.clock.today() - dt.timedelta(days=10)
        put, call, _skew, note = core.smile_legs(con_with(ladder(old)), "META", EXPIRY, 100.0)
        self.assertIsNotNone(put, "a 10-day-stale feed must still price the smile")
        self.assertIsNotNone(call)
        self.assertEqual(note, f"bars to {old}")     # ...but it must not look live

    def test_a_current_feed_carries_no_note(self):
        fresh = core.clock.today() - dt.timedelta(days=1)
        _put, _call, _skew, note = core.smile_legs(con_with(ladder(fresh)), "META", EXPIRY, 100.0)
        self.assertIsNone(note)

    def test_no_bars_at_all_is_named_rather_than_guessed(self):
        for sym in ("ZZZZ",):
            with self.subTest(sym=sym):
                self.assertEqual(core.smile_legs(con_with([]), sym, EXPIRY, 100.0)[3],
                                 "no option bars for this name")

    def test_the_window_is_anchored_to_the_bar_date_not_to_today(self):
        """Two years stale must still find its own 7-day window, not an empty one."""
        with mock.patch.object(core.clock, "today", return_value=dt.date(2026, 10, 12)):
            stale = dt.date(2026, 10, 2)
            put, _call, _skew, note = core.smile_legs(con_with(ladder(stale)), "META", EXPIRY, 100.0)
        self.assertIsNotNone(put)
        self.assertEqual(note, "bars to 2026-10-02")


if __name__ == "__main__":
    unittest.main()
