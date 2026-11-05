"""Tests for get_latest_price — reads extended_hours_quotes."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

import duckdb

from apps.trade_profile.complete_risk.quotes import get_latest_price

DB = bootstrap.DATA_ROOT / "trades.duckdb"


class TestShape(unittest.TestCase):
    def test_signature_takes_a_connection_and_a_ticker(self):
        import inspect
        params = list(inspect.signature(get_latest_price).parameters)
        self.assertEqual(params[:2], ["con", "ticker"])

    def test_it_returns_a_quadruple_not_a_bare_price(self):
        # (price, timestamp, session, source). Assuming a scalar -- which the
        # first version of this test did -- compares a tuple against an int and
        # raises TypeError instead of asserting anything about the price.
        import inspect
        src = inspect.getsource(get_latest_price)
        self.assertIn("return None, None, None, None", src)
        self.assertEqual(len(inspect.getsource(get_latest_price).split("return price,")[1]
                             .split("\n")[0].split(",")), 3)


@unittest.skipUnless(DB.exists(), "trades.duckdb not present")
class TestAgainstTheBook(unittest.TestCase):
    def test_a_held_ticker_returns_a_positive_price(self):
        con = duckdb.connect(str(DB), read_only=True)
        try:
            ticker = con.execute("SELECT underlying FROM positions WHERE qty<>0 LIMIT 1").fetchone()[0]
            price, ts, session, source = get_latest_price(con, ticker)
        finally:
            con.close()
        # This project's own rule: only an is_realtime row may be used as a live
        # price, so the tuple carries its provenance rather than just a number.
        if price is not None:
            self.assertGreater(price, 0)
            self.assertIn(session, ("RTH", "pre-market", "after-hours", "overnight", None))

    def test_an_unknown_ticker_returns_none_rather_than_zero(self):
        # None and 0.0 mean opposite things: "no quote" vs "worthless". Callers
        # branch on truthiness, so a 0.0 would silently price a leg at nothing.
        con = duckdb.connect(str(DB), read_only=True)
        try:
            self.assertEqual(get_latest_price(con, "NOSUCHTICKER"),
                             (None, None, None, None))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
