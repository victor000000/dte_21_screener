"""Round-trip known historical IV while the spot and date both change."""
import datetime as dt
import unittest
from unittest.mock import patch

from apps.screener import screener_21dte_v2 as core
from apps.screener.smile_marks import price_legs
from compute import bs
from tests.apps.screener.test_screener_21dte_v2 import con_with, EXPIRY, TODAY


class TestMatchedBarDates(unittest.TestCase):
    def setUp(self):
        self.old = dt.date(2026, 10, 2)
        T = (EXPIRY - self.old).days / 365.0
        self.rows = [("META", EXPIRY, float(K), cp, self.old,
                      bs.bs_price(100., K, T, core.R, .30, cp == "C"))
                     for K in range(70, 151) for cp in ("C", "P")]
        self.con = con_with(self.rows)
        self.addCleanup(self.con.close)

    def test_moved_spot_does_not_invent_iv_or_select_out_of_band_legs(self):
        with patch.object(core.clock, "today", return_value=TODAY):
            put, call, skew, note = core.smile_legs(self.con, "META", EXPIRY, 110.)
        self.assertIsNotNone(put)
        self.assertIsNotNone(call)
        for cp, leg in (("P", put), ("C", call)):
            self.assertAlmostEqual(leg["iv"], .30, places=6)
            expected = bs.bs_delta(110., leg["K"], (EXPIRY - TODAY).days / 365.,
                                   core.R, .30, cp == "C")
            self.assertAlmostEqual(leg["delta"], expected, places=6)
            self.assertTrue(.16 <= abs(expected) <= .22)
            self.assertNotAlmostEqual(leg["mark"], leg["close"], places=2)
        self.assertAlmostEqual(skew, 0., places=5)
        self.assertIn(str(self.old), note)

    def test_a_bar_without_its_own_days_spot_is_rejected(self):
        self.con.execute("DELETE FROM yh.prices")
        self.con.execute("INSERT INTO yh.prices VALUES ('META', ?, 110)", [TODAY])
        with patch.object(core.clock, "today", return_value=TODAY):
            put, call, _, note = core.smile_legs(self.con, "META", EXPIRY, 110.)
        self.assertIsNone(put)
        self.assertIsNone(call)
        self.assertIn("missing underlying closes", note)

    def test_the_fresh_tail_can_supply_the_matched_spot(self):
        self.con.execute("DELETE FROM yh.prices")
        self.con.execute("INSERT INTO mh.underlying_daily VALUES ('META', ?, 100)", [self.old])
        bars = [(K, cp, day, close) for _, _, K, cp, day, close in self.rows]
        legs, missing = price_legs(self.con, "META", EXPIRY, 110., bars, TODAY)
        self.assertFalse(missing)
        self.assertTrue(legs["P"])
        self.assertTrue(legs["C"])
        self.assertAlmostEqual(legs["P"][0]["iv"], .30, places=6)
