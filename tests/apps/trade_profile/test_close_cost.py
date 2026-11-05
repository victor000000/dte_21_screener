"""What a short leg costs to buy back, against the mid every P&L is measured at.

Measured 2026-10-06: CRWD's Dec-18 225P -- the leg the report called the position worth
holding -- sat in a 5.90/7.40 market around a 6.65 mid, 22.6% wide. Up $2,492 on paper,
$1,742 realisable, because you buy a short back at the ASK.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.trade_profile import close_cost as C

# (name, qty, bid, mid, ask, entry, mult, fx) -- the shape from_rows builds.
CRWD = ("CRWD 12-18 225P", -10, 5.90, 6.65, 7.40, 9.142, 100, 1.0)
TIGHT = ("TLT 11-20 82C", -7, 0.25, 0.255, 0.26, 0.46, 100, 1.0)


def body(lines):
    return "\n".join(lines)


class TestTheArithmetic(unittest.TestCase):
    def test_the_give_up_is_the_difference_between_the_two_marks(self):
        r = C._row(*CRWD)
        self.assertAlmostEqual(r["at_mid"], 2492.0, places=0)
        self.assertAlmostEqual(r["at_ask"], 1742.0, places=0)
        self.assertAlmostEqual(r["at_mid"] - r["at_ask"], 750.0, places=0)

    def test_the_two_percentages_are_different_and_both_reported(self):
        # Conflating these is easy: bid-ask is the conventional spread, mid->ask is what
        # crossing costs, and only the second belongs beside a P&L measured at the mid.
        r = C._row(*CRWD)
        self.assertAlmostEqual(r["bid_ask_pct"], 22.6, places=1)
        self.assertAlmostEqual(r["cross_pct"], 11.3, places=1)
        self.assertAlmostEqual(r["bid_ask_pct"] / r["cross_pct"], 2.0, places=1)

    def test_a_short_leg_shows_the_cost_and_a_long_leg_is_skipped(self):
        # You SELL a long to close it, at the bid -- the sign of this is the opposite, so
        # a long leg in this table would read backwards.
        self.assertEqual(C.build([("LONG 1-1 100C", 5, 1.0, 1.1, 1.2, 0.5, 100, 1.0)]), [])


class TestWhatItLeavesOut(unittest.TestCase):
    def test_a_tight_market_is_not_listed(self):
        # 3.9% wide. Listing 0.1% spreads beside 22% ones teaches the reader to skip the
        # table, which is the opposite of what a warning column is for.
        self.assertEqual(C.build([TIGHT]), [])

    def test_a_leg_with_no_quote_at_all_is_not_listed(self):
        self.assertEqual(C.build([("X 1-1 100C", -1, 0, 1.0, 0, 0.5, 100, 1.0)]), [])

    def test_an_empty_book_produces_nothing(self):
        self.assertEqual(C.build([]), [])


class TestTheSectionItPrints(unittest.TestCase):
    def test_it_names_both_marks_and_the_give_up(self):
        lines = body(C.build([CRWD]))
        self.assertIn("**mid**", lines)
        self.assertIn("**ask**", lines)
        self.assertIn("Give-up", lines)

    def test_a_width_is_stated_so_the_omission_is_not_silent(self):
        # Legs under the threshold are dropped; the prose has to say so, or a missing leg
        # reads as a leg with no problem.
        self.assertIn(f"{C.MATERIAL_PCT:.0f}%", body(C.build([CRWD])))


class TestFromRows(unittest.TestCase):
    """The row-tuple mapping, which is per-caller and got one caller wrong."""

    COLS = {"broker": 0, "underlying": 1, "sec_type": 2, "qty": 3, "multiplier": 4,
            "mark": 5, "avg_price": 6, "expiry": 7, "strike": 8, "call_put": 9,
            "bid": 10, "ask": 11}

    def row(self, exp):
        return ("Schwab", "CRWD", "OPT", -10, 100, 6.65, 9.142, exp, 225.0, "P", 5.9, 7.4)

    def test_it_takes_the_column_map_it_is_given(self):
        import datetime as dt
        lines = C.from_rows([self.row(dt.date(2026, 12, 18))], lambda b: 1.0, self.COLS)
        self.assertIn("CRWD 12-18 225P", body(lines))

    def test_a_string_expiry_is_a_caller_error_not_a_wrong_number(self):
        # The real bug this parameter prevents: one caller's map read another's `expiry`,
        # a str where a date belonged, and Python said "Invalid format specifier" rather
        # than quietly printing a wrong figure. Loud is what we want here.
        with self.assertRaises((ValueError, TypeError)):
            C.from_rows([self.row("2026-12-18")], lambda b: 1.0, self.COLS)

    def test_a_non_option_row_is_skipped(self):
        stock = ("Schwab", "CRWD", "STOCK", -10, 1, 100.0, 100.0, None, None, None, 0, 0)
        self.assertEqual(C.from_rows([stock], lambda b: 1.0, self.COLS), [])


if __name__ == "__main__":
    unittest.main()
