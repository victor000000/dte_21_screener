"""The line that says how much of the book came from a live broker book.

Two brokers can hold the SAME contract -- CRWD's Nov-20 230P sits at IBKR and at Schwab
-- and `tws_option_marks` keys on the full contract, so the duplicate collapses
into one entry. Counting `len(got)` against `len(legs)` then printed "11 of 13 legs have
a live two-sided book" for a book where all 13 rows were priced off the live book: it
read as two legs having fallen back to the chain ladder, which is the one thing this line
exists to tell you.
"""
import contextlib
import datetime as dt
import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan import broker_marks


class TestTheCoverageLineCountsLegs(unittest.TestCase):
    """The line a reader uses to judge whether the book is priced off a real market.

    Two brokers can hold the SAME contract -- CRWD's Nov-20 230P sits at IBKR and at
    Schwab -- and `tws_option_marks` keys on the full contract, so the
    duplicate collapses into one entry. Counting `len(got)` against `len(legs)` then
    printed "11 of 13 legs have a live two-sided book" for a book where all 13 rows
    were priced off the live book: it read as two legs having fallen back to the chain
    ladder, which is the one thing this line exists to tell you.
    """

    def test_a_duplicated_contract_does_not_look_like_a_miss(self):
        import contextlib
        import io
        import datasources.tws as real_tws
        original = real_tws.option_marks

        def fake(legs, client_id=0):
            return {("CRWD", dt.date(2026, 11, 20), 230.0, "P"):
                    {"bid": 3.0, "ask": 3.3}}

        real_tws.option_marks = fake
        try:
            rows = [("a", "IBKR", "CRWD", "OPT", "2026-11-20", 230.0, "P", 5, 1.0),
                    ("a", "Schwab", "CRWD", "OPT", "2026-11-20", 230.0, "P", 3, 1.0)]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                got = broker_marks.for_book(rows)
        finally:
            real_tws.option_marks = original
        line = buf.getvalue()
        self.assertEqual(len(got), 1, "the duplicate collapses in the mapping")
        self.assertIn("2 of 2 legs", line, line)
        self.assertIn("1 of 1 contracts", line, line)
