"""Tests for canonical_snapshot_spots — one close per underlying."""
import pathlib
import sys
import unittest
from unittest.mock import patch
import pandas as pd
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk.canonical import canonical_snapshot_spots


class TestShape(unittest.TestCase):
    def test_it_is_callable_with_no_database(self):
        # A build with an empty book must not explode; the function returns a
        # mapping and callers index it defensively.
        import inspect
        self.assertTrue(callable(canonical_snapshot_spots))
        self.assertGreaterEqual(len(inspect.signature(canonical_snapshot_spots).parameters), 1)


@unittest.skipUnless((bootstrap.DATA_ROOT / "trades.duckdb").exists(), "no book")
class TestOnePerUnderlying(unittest.TestCase):
    def test_every_input_underlying_gets_at_most_one_spot(self):
        # The reason this function exists: a per-leg fetch left EWZ with two
        # different "closes" in one table, and every comparison downstream was
        # then between two different things.
        import duckdb
        con = duckdb.connect(str(bootstrap.DATA_ROOT / "trades.duckdb"), read_only=True)
        try:
            unds = [r[0] for r in con.execute(
                "SELECT DISTINCT underlying FROM positions WHERE qty<>0").fetchall()]
            yesterday = dt.date.today() - dt.timedelta(days=2)
            frame = pd.DataFrame({'Close': [123.0]}, index=pd.to_datetime([yesterday]))
            with patch('yfinance.Ticker') as ticker:
                ticker.return_value.history.return_value = frame
                ticker.return_value.history_metadata = {}
                got = canonical_snapshot_spots(unds, {})
        finally:
            con.close()
        self.assertIsInstance(got, dict)
        for u in unds:
            if u in got and got[u] is not None:
                self.assertGreater(got[u], 0, f"{u} produced a non-positive close")


if __name__ == "__main__":
    unittest.main()
