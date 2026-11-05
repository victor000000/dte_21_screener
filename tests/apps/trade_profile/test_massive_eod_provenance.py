"""A fallback vendor's cache must contain only that vendor's observations."""
import datetime as dt
import unittest
from unittest import mock

import duckdb
from apps.trade_profile import complete_risk_analysis as core
from datasources import massive


class TestMassiveProvenance(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.execute("""CREATE TABLE theta_eod_marks (
            as_of_utc TIMESTAMP, kind TEXT, symbol TEXT, expiration TEXT,
            strike DOUBLE, call_put TEXT, close DOUBLE, source TEXT)""")
        self.expiry = dt.date(2026, 12, 18)
        self.rows = [("META", self.expiry, 100.0, "C")]
        self.key = ("META", self.expiry.isoformat(), 100.0, "C")
        self.client = mock.Mock(api_key="test")
        self.enterContext(mock.patch.object(massive, "get_client", return_value=self.client))

    def cached(self):
        return self.con.execute("SELECT kind, close, source FROM theta_eod_marks ORDER BY kind").fetchall()

    def test_theta_prices_keep_priority_but_are_not_cached_as_massive(self):
        self.client.grouped_stocks.return_value = {"META": {"close": 101.0}}
        self.client.option_daily.return_value = [{"close": 6.0}]
        closes, marks = core.fetch_massive_eod(self.con, self.rows, {"META": 102.0}, {self.key: 7.0})
        self.assertEqual(closes, {"META": 102.0})
        self.assertEqual(marks, {self.key: 7.0})
        self.assertEqual(self.cached(), [("option", 6.0, "massive_eod"),
                                         ("underlying", 101.0, "massive_eod")])
        self.client.option_daily.reset_mock()
        core.fetch_massive_eod(self.con, self.rows, {}, {self.key: 8.0})
        self.client.option_daily.assert_not_called()
        self.assertEqual(self.con.execute("SELECT DISTINCT close FROM theta_eod_marks WHERE kind='option'").fetchall(),
                         [(6.0,)])

    def test_vendor_outage_does_not_cache_theta_values(self):
        self.client.grouped_stocks.side_effect = RuntimeError("offline")
        self.client.option_daily.side_effect = RuntimeError("offline")
        core.fetch_massive_eod(self.con, self.rows, {"META": 102.0}, {self.key: 7.0})
        self.assertEqual(self.cached(), [])


if __name__ == "__main__":
    unittest.main()
