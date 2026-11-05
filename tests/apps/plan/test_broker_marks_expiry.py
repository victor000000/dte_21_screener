"""Quotes and coverage for calendar positions with identical strikes."""
import contextlib
import datetime as dt
import io
import unittest
from unittest.mock import patch

from apps.plan import broker_marks
from datasources import tws


class TestExpiryIdentity(unittest.TestCase):
    def test_each_expiry_retains_its_own_mid_and_coverage(self):
        nov, dec = dt.date(2026, 11, 20), dt.date(2026, 12, 18)
        quotes = {("XYZ", nov, 100., "P"): {"bid": 1.9, "ask": 2.1},
                  ("XYZ", dec, 100., "P"): {"bid": 7.9, "ask": 8.1}}
        rows = [("a", "IBKR", "XYZ", "OPT", str(e), 100., "P", -1, 10.)
                for e in (nov, dec)]
        with patch.object(tws, "option_marks", return_value=quotes):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                marks = broker_marks.for_book(rows)
        self.assertEqual(marks[("XYZ", nov, 100., "P")], 2.)
        self.assertEqual(marks[("XYZ", dec, 100., "P")], 8.)
        self.assertIn("2 of 2 legs", output.getvalue())
        self.assertIn("2 of 2 contracts", output.getvalue())

    def test_a_quote_for_another_month_does_not_count_as_coverage(self):
        quotes = {("XYZ", dt.date(2026, 11, 20), 100., "P"): {"bid": 1., "ask": 2.}}
        rows = [("a", "IBKR", "XYZ", "OPT", "2026-12-18", 100., "P", -1, 10.)]
        with patch.object(tws, "option_marks", return_value=quotes):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                broker_marks.for_book(rows)
        self.assertIn("0 of 1 legs", output.getvalue())
