"""test_cn_book_market.py — how cn_book reads the market: the Sina symbol spelling and whether
the session is open. Split from test_cn_book.py (size ratchet); both are pure helpers with no
book behind them, which is why they are cheap to pin exactly.
"""
import datetime as dt
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan import cn_book


class TestSinaCode(unittest.TestCase):
    def test_czce_three_digit_expands_and_four_digit_passes_through(self):
        self.assertEqual(cn_book.sina_code("MA701"), "nf_MA2701")
        self.assertEqual(cn_book.sina_code("SC2612"), "nf_SC2612")

    def test_decade_comes_from_the_clock_and_unparseable_is_none(self):
        with mock.patch.object(cn_book.clock, "today", return_value=dt.date(2031, 5, 1)):
            self.assertEqual(cn_book.sina_code("MA701"), "nf_MA3701")
        self.assertIsNone(cn_book.sina_code("MA"))


class TestSessionOpen(unittest.TestCase):
    def at(self, hh, mm):
        return cn_book.session_open(dt.datetime(2026, 10, 8, hh, mm) - dt.timedelta(hours=8))

    def test_day_and_night_are_open_lunch_and_evening_are_not(self):
        for hh, mm in ((9, 0), (11, 30), (13, 30), (15, 0), (21, 0), (23, 59), (0, 30)):
            self.assertTrue(self.at(hh, mm), f"{hh}:{mm:02d} CST should be open")
        for hh, mm in ((11, 31), (12, 0), (15, 1), (20, 59), (2, 31)):
            self.assertFalse(self.at(hh, mm), f"{hh}:{mm:02d} CST should be closed")


if __name__ == "__main__":
    unittest.main()
