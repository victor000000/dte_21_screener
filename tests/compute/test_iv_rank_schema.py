"""Both schema generations and both screener callers must read the same IV values."""
import datetime as dt
import unittest

import duckdb
from compute.iv_rank import fetch_series, rank_series
from apps.screener.screener_21dte_v2 import iv_column


class TestIVSchema(unittest.TestCase):
    def test_legacy_new_and_partially_populated_schema_agree(self):
        for columns, values in (("atm_iv DOUBLE", "?"), ("iv DOUBLE", "?"),
                                ("iv DOUBLE, atm_iv DOUBLE", "NULL, ?")):
            with self.subTest(columns=columns), duckdb.connect(":memory:") as con:
                con.execute("CREATE SCHEMA mh")
                con.execute(f"CREATE TABLE mh.iv_history (underlying TEXT, source TEXT, day DATE, {columns})")
                for i in range(60):
                    con.execute(f"INSERT INTO mh.iv_history VALUES ('META', 's', ?, {values})",
                                [dt.date(2026, 1, 1) + dt.timedelta(days=i), 0.2 if i == 59 else 0.1])
                universe, _ = fetch_series(con)
                screen, _ = fetch_series(con, col=iv_column(con))
                self.assertEqual(universe, screen)
                self.assertEqual(rank_series(universe["META"])["ivr"], 100.0)


if __name__ == "__main__":
    unittest.main()
