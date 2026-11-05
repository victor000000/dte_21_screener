"""The close-cost check must be able to FAIL, in both directions.

A table nothing checks can silently stop being produced. Verified against the real report
before this file existed: removing the section failed 3 checks; doctoring one P&L failed
1, naming the leg and both figures.
"""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.audit import check_close_cost as K
from apps.trade_profile import close_cost as C

C0 = K.BOOK_COL


def book_row(bid, mid, ask, qty=-10, entry=9.142, mark=None, underlying="CRWD"):
    r = [None] * 24
    r[C0["broker"]] = "Schwab"
    r[C0["underlying"]] = underlying
    r[C0["sec_type"]] = "OPT"
    r[C0["expiry"]] = dt.date(2026, 12, 18)
    r[C0["strike"]] = 225.0
    r[C0["call_put"]] = "P"
    r[C0["qty"]] = qty
    r[C0["multiplier"]] = 100
    r[C0["mark"]] = mid if mark is None else mark
    r[C0["avg_price"]] = entry
    r[C0["bid"]] = bid
    r[C0["ask"]] = ask
    return tuple(r)


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, group, check, ok, detail, warn=False):
        self.calls.append((group, check, ok, detail))

    def by(self, fragment):
        return [c for c in self.calls if fragment in c[1]]


def run(text, rows):
    rec = Rec()
    K.check(text, rows, rec, lambda b: 1.0)
    return rec


OK_REPORT = "\n".join(C.build([("CRWD 12-18 225P", -10, 5.90, 6.65, 7.40, 9.142, 100, 1.0)]))


class TestItPassesOnAGoodSection(unittest.TestCase):
    def test_the_real_shape_passes(self):
        rec = run(OK_REPORT, [book_row(5.90, 6.65, 7.40)])
        self.assertTrue(all(c[2] for c in rec.calls), rec.calls)

    def test_a_book_with_no_wide_leg_is_a_pass_not_a_skip(self):
        # Nothing to show is a real state, and it must not read as a missing section.
        rec = run("no section here", [book_row(0.25, 0.255, 0.26)])
        self.assertTrue(rec.calls[0][2])
        self.assertIn("under 5%", rec.calls[0][3])


class TestItFailsWhenTheSectionIsGone(unittest.TestCase):
    def test_a_wide_leg_with_no_section_fails(self):
        rec = run("# report with no close-cost section", [book_row(5.90, 6.65, 7.40)])
        self.assertFalse(rec.by("shows what closing would cost")[0][2])

    def test_a_wide_leg_omitted_from_a_present_section_fails(self):
        # The section exists and is right about one leg, but another wide leg is missing.
        text = OK_REPORT
        rows = [book_row(5.90, 6.65, 7.40),
                book_row(2.12, 2.345, 2.57, underlying="EWZ")]
        rec = run(text, rows)
        self.assertFalse(rec.by("left out")[0][2])
        self.assertIn("EWZ", rec.by("left out")[0][3])


class TestItFailsOnAWrongNumber(unittest.TestCase):
    def test_a_doctored_pnl_at_mid_fails(self):
        self.assertIn("2,492", OK_REPORT)
        rec = run(OK_REPORT.replace("2,492", "9,999"), [book_row(5.90, 6.65, 7.40)])
        bad = rec.by("re-derives")
        self.assertFalse(bad[0][2])
        self.assertIn("9,999", bad[0][3])

    def test_a_row_for_a_leg_the_book_does_not_have_fails(self):
        ghost = OK_REPORT.replace("CRWD 12-18 225P", "ZZZ 1-1 1P")
        rec = run(ghost, [book_row(5.90, 6.65, 7.40)])
        self.assertFalse(rec.by("re-derives")[0][2])


if __name__ == "__main__":
    unittest.main()
