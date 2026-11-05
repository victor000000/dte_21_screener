"""Tests for the ThetaData EOD fetch."""
import inspect
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk import theta_eod


class TestContract(unittest.TestCase):
    def test_table_exists_probe_is_separate_from_the_fetch(self):
        # _table_exists is its own function because the fetch asks it twice, for
        # two different tables, and had the check inline both times.
        self.assertTrue(callable(theta_eod._table_exists))
        self.assertTrue(callable(theta_eod.fetch_theta_eod))

    def test_the_fetch_takes_the_connection(self):
        # One argument: the legs come from the `positions` table the connection
        # already points at, so there is no second source of truth to drift.
        params = list(inspect.signature(theta_eod.fetch_theta_eod).parameters)
        self.assertEqual(params, ["con"])


@unittest.skipUnless((bootstrap.DATA_ROOT / "trades.duckdb").exists(), "no book")
class TestTableProbe(unittest.TestCase):
    def test_probe_answers_about_a_table_that_exists(self):
        import duckdb
        con = duckdb.connect(str(bootstrap.DATA_ROOT / "trades.duckdb"), read_only=True)
        try:
            self.assertTrue(theta_eod._table_exists(con, "positions"))
        finally:
            con.close()

    def test_probe_answers_no_about_one_that_does_not(self):
        # A probe that always says yes would make the fetch write into a table it
        # never created.
        import duckdb
        con = duckdb.connect(str(bootstrap.DATA_ROOT / "trades.duckdb"), read_only=True)
        try:
            self.assertFalse(theta_eod._table_exists(con, "no_such_table_xyz"))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
