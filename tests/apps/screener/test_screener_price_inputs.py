"""Regression cases for mixed expiry dates and unusable underlying closes."""
import datetime as dt
import math
import unittest
from unittest import mock

from tests.apps.screener.test_screener_21dte_v2 import (
    core, con_with, ladder, EXPIRY, TODAY,
)


class TestPriceInputs(unittest.TestCase):
    def test_newer_other_expiry_does_not_hide_target_chain(self):
        old = TODAY - dt.timedelta(days=14)
        rows = ladder(old)
        rows.append(("META", dt.date(2027, 1, 15), 100.0, "C", TODAY, 10.0))
        with con_with(rows) as con, mock.patch.object(core.clock, "today", return_value=TODAY):
            put, call, _, note = core.smile_legs(con, "META", EXPIRY, 100.0)
        self.assertIsNotNone(put)
        self.assertIsNotNone(call)
        self.assertEqual(put["expiry"], EXPIRY)
        self.assertEqual(note, f"bars to {old}")

    def test_fallback_chain_uses_its_own_date_and_the_application_clock(self):
        old = TODAY - dt.timedelta(days=14)
        rows = ladder(old)
        # A later expiry has fresher data but must not suppress the nearer chain.
        rows.append(("META", dt.date(2027, 1, 15), 100.0, "C", TODAY, 10.0))
        with con_with(rows) as con, mock.patch.object(core.clock, "today", return_value=TODAY):
            put, call, _, note = core.smile_legs(con, "META", dt.date(2026, 11, 20), 100.0)
        self.assertIsNotNone(put)
        self.assertIsNotNone(call)
        self.assertEqual(put["expiry"], EXPIRY)
        self.assertIn(f"legs on {EXPIRY}", note)
        self.assertIn(f"bars to {old}", note)

    def test_bad_tail_close_does_not_replace_valid_warehouse_close(self):
        for bad in (None, 0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(bad=bad), con_with([]) as con:
                con.execute("INSERT INTO yh.prices VALUES ('META', ?, 100)", [TODAY])
                con.execute("INSERT INTO mh.underlying_daily VALUES ('META', ?, ?)", [TODAY, bad])
                self.assertEqual(core.spot_and_hv(con, "META"), (100.0, None))

    def test_invalid_historical_closes_do_not_crash_hv(self):
        with con_with([]) as con:
            rows = [("META", TODAY - dt.timedelta(days=i), 100.0 + i) for i in range(40)]
            if rows:
                con.executemany("INSERT INTO yh.prices VALUES (?, ?, ?)", rows)
            con.execute("INSERT INTO mh.underlying_daily VALUES ('META', ?, 0)",
                        [TODAY - dt.timedelta(days=10)])
            spot, hv = core.spot_and_hv(con, "META")
        self.assertEqual(spot, 100.0)
        self.assertTrue(math.isfinite(hv))


if __name__ == "__main__":
    unittest.main()
