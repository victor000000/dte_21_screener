"""Provenance checks distinguish observations from operational receipts."""
import unittest

import duckdb
from apps.audit import selfcheck


class TestProvenance(unittest.TestCase):
    def test_ingestion_receipts_do_not_need_a_vendor_source(self):
        with duckdb.connect(":memory:") as con:
            con.execute("CREATE TABLE futures_ingestion_checks (run_id TEXT, status TEXT)")
            con.execute("CREATE TABLE option_bars (source TEXT, close DOUBLE)")
            self.assertEqual(selfcheck.missing_sources(con), [])

    def test_observations_still_require_a_source(self):
        with duckdb.connect(":memory:") as con:
            con.execute("CREATE TABLE futures_ingestion_checks (run_id TEXT, status TEXT)")
            con.execute("CREATE TABLE us_futures_daily (close DOUBLE)")
            self.assertEqual(selfcheck.missing_sources(con), ["us_futures_daily"])


if __name__ == "__main__":
    unittest.main()
