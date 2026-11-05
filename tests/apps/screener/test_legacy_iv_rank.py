"""The legacy screen must not label a percentile or an HV proxy as IV rank."""
import datetime as dt
import unittest

import duckdb
from apps.screener.screener_21dte import iv_rank_for


class TestLegacyIVRank(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.execute("CREATE SCHEMA mh")
        self.con.execute("CREATE TABLE mh.iv_history (underlying TEXT, source TEXT, day DATE, atm_iv DOUBLE)")
        self.today = dt.date(2026, 10, 16)

    def seed(self, source, values):
        for i, value in enumerate(values):
            self.con.execute("INSERT INTO mh.iv_history VALUES ('META', ?, ?, ?)",
                             [source, self.today - dt.timedelta(days=len(values) - i), value])

    def test_range_rank_includes_today_without_pooling_other_vendors(self):
        self.seed("yf_chain", [0.1] * 58 + [1.1])
        self.seed("ibkr_tws30d", [9.0] * 80)
        self.assertAlmostEqual(iv_rank_for(self.con, "META", self.today, 0.2)["ivr"], 10.0)

    def test_missing_own_history_is_unrankable(self):
        self.seed("ibkr_tws30d", [0.1] * 60)
        self.assertIsNone(iv_rank_for(self.con, "META", self.today, 0.2)["ivr"])

    def test_same_day_stored_observation_is_replaced_by_current_iv(self):
        self.seed("yf_chain", [0.1] * 58 + [1.1])
        self.con.execute("INSERT INTO mh.iv_history VALUES ('META', 'yf_chain', ?, 5)", [self.today])
        self.assertAlmostEqual(iv_rank_for(self.con, "META", self.today, 0.2)["ivr"], 10.0)


if __name__ == "__main__":
    unittest.main()
