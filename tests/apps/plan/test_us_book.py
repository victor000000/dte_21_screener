"""test_us_book.py — the US book derived from what the brokers report.

The book CANNOT go stale: `broker_positions` holds the holdings, `fills` holds what they
cost. Both halves are asserted, because getting either wrong is silent.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import duckdb

from apps.plan.us_book import us_book

# The literal fallback, in the shape build_positions passes it.
FALLBACK = [
    ("40342049SCHW", "Schwab", "TLT", "OPT", "2026-11-20", 74.0, "P", -25, 0.52),
    ("40342049SCHW", "Schwab", "TLT", "OPT", "2026-11-20", 82.0, "C", -25, 0.46),
]


def book(con, rows):
    """Rows shaped as (as_of, account, broker, underlying, sec_type, symbol, expiry,
    strike, call_put, currency, qty)."""
    con.execute("""CREATE OR REPLACE TABLE broker_positions (as_of TIMESTAMP, account TEXT,
        broker TEXT, underlying TEXT, sec_type TEXT, symbol TEXT, expiry DATE, strike DOUBLE,
        call_put TEXT, currency TEXT, qty DOUBLE)""")
    if rows:   # DuckDB raises on an empty list, not a no-op (the 2026-10-05 shape)
        con.executemany("INSERT INTO broker_positions VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)


def fill(con, account, symbol, open_close, action, qty, price):
    con.execute("""INSERT INTO fills (account, symbol, open_close, action, qty, price)
                   VALUES (?,?,?,?,?,?)""", [account, symbol, open_close, action, qty, price])


class TestUsBook(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.con.execute("""CREATE TABLE fills (account TEXT, symbol TEXT, open_close TEXT,
                            action TEXT, qty DOUBLE, price DOUBLE)""")

    def tearDown(self):
        self.con.close()

    def test_holds_what_the_broker_reports_not_what_we_remember(self):
        # The failure this exists for: the list named the CLOSED 82C for a full session.
        import datetime as dt
        book(self.con, [
            (dt.datetime(2026, 10, 7, 13, 42), "40342049SCHW", "Schwab", "TLT", "OPT",
             "TLT261120P00074000", dt.date(2026, 11, 20), 74.0, "P", "USD", -7.0),
            (dt.datetime(2026, 10, 7, 13, 42, 35), "40342049SCHW", "Schwab", "TLT", "OPT",
             "TLT261120C00080000", dt.date(2026, 11, 20), 80.0, "C", "USD", -7.0),
        ])
        got = {(r[2], r[5], r[6]): r[7] for r in us_book(self.con, FALLBACK)}
        self.assertIn(("TLT", 80.0, "C"), got, "the live strike must be in the book")
        self.assertNotIn(("TLT", 82.0, "C"), got,
                         "the CLOSED strike must not be -- this is the staleness")

    def test_the_newest_snapshot_per_account_wins(self):
        # Append-only across loads, and a load may cover one broker — so filter per account.
        import datetime as dt
        book(self.con, [
            (dt.datetime(2026, 10, 6), "40342049SCHW", "Schwab", "TLT", "OPT",
             "TLT261120C00082000", dt.date(2026, 11, 20), 82.0, "C", "USD", -25.0),
            (dt.datetime(2026, 10, 7), "40342049SCHW", "Schwab", "TLT", "OPT",
             "TLT261120C00080000", dt.date(2026, 11, 20), 80.0, "C", "USD", -7.0),
            (dt.datetime(2026, 10, 6), "U0000000", "IBKR", "META", "OPT",
             "META261120P00630000", dt.date(2026, 11, 20), 630.0, "P", "USD", -2.0),
        ])
        got = {(r[2], r[5], r[6]) for r in us_book(self.con, FALLBACK)}
        self.assertIn(("META", 630.0, "P"), got, "IBKR's older load still stands")  # noqa
        self.assertEqual(len([g for g in got if g[0] == "TLT"]), 1,
                         "only the newest Schwab snapshot counts")

    def test_the_entry_price_comes_from_the_opening_fill(self):
        import datetime as dt
        book(self.con, [(dt.datetime(2026, 10, 7), "40342049SCHW", "Schwab", "TLT", "OPT",
                         "TLT261120C00080000", dt.date(2026, 11, 20), 80.0, "C", "USD", -7.0)])
        fill(self.con, "40342049SCHW", "TLT261120C00080000", "OPEN", "SELL", 7, 0.46)
        fill(self.con, "40342049SCHW", "TLT261120C00080000", "OPEN", "SELL", 3, 0.56)
        got = us_book(self.con, FALLBACK)
        # qty-weighted: (7*0.46 + 3*0.56) / 10
        self.assertAlmostEqual(got[0][8], (7 * 0.46 + 3 * 0.56) / 10, places=6)
        self.assertEqual(got[0][7], -7, "qty is what the broker reports")

    def test_a_closing_fill_never_sets_the_entry_price(self):
        import datetime as dt
        book(self.con, [(dt.datetime(2026, 10, 7), "40342049SCHW", "Schwab", "TLT", "OPT",
                         "TLT261120P00074000", dt.date(2026, 11, 20), 74.0, "P", "USD", -7.0)])
        fill(self.con, "40342049SCHW", "TLT261120P00074000", "CLOSE", "BUY", 18, 0.58)
        got = us_book(self.con, FALLBACK)
        self.assertAlmostEqual(got[0][8], 0.52, places=6,
                               msg="a close is not an entry; the literal must supply it")


if __name__ == "__main__":
    unittest.main()
