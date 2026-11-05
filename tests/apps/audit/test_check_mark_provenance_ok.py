"""The provenance check on sentences that are RIGHT -- and the rows it must ignore.

Split from test_check_mark_provenance, which covers the failures. Together the two
pin the comparison from both sides: a check that never passes is as useless as one
that never fails, and both were observed on the real report.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.audit import check_mark_provenance as cmp_check
from apps.trade_profile import mark_provenance
from tests.apps.audit.test_check_mark_provenance import Recorder, book, report, run


class TestItPassesOnTheTruth(unittest.TestCase):
    def test_a_book_of_broker_quotes(self):
        self.assertTrue(run("every option mark is a two-sided quote",
                            ["broker_book"] * 16).ok)

    def test_a_mixed_book(self):
        clause = mark_provenance.sentence(["broker_book"] * 9 + ["model"])
        self.assertTrue(run(clause, ["broker_book"] * 9 + ["model"]).ok)

    def test_a_book_of_snapshots(self):
        clause = mark_provenance.sentence(["snapshot"] * 3)
        self.assertTrue(run(clause, ["snapshot"] * 3).ok)


class TestEdgeCases(unittest.TestCase):
    def test_a_header_with_no_provenance_clause_fails(self):
        rec = Recorder()
        cmp_check.check("**Book as of 2026-10-06 13:51 UTC — no such clause here.**",
                        book(["broker_book"]), rec, mark_provenance)
        self.assertFalse(rec.ok)

    def test_a_missing_report_does_not_raise(self):
        rec = Recorder()
        cmp_check.check("", book(["broker_book"]), rec, mark_provenance)
        self.assertFalse(rec.ok)

    def test_stock_rows_are_not_counted(self):
        # A stock's mark IS its spot (`mark_source='spot'`). Counting it as an option
        # would move the expected clause and make the check disagree with the report.
        rows = book(["broker_book"] * 4) + book(["spot"], sec_type="STOCK")
        rec = Recorder()
        cmp_check.check(report("every option mark is a two-sided quote"), rows,
                        rec, mark_provenance)
        self.assertTrue(rec.ok, rec.calls[-1][3])

    def test_the_china_legs_DO_count(self):
        # `!= "STOCK"`, not `== "OPT"`: the CN legs are FUT_OPT with a broker snapshot
        # mark, and they are options a reader is looking at. risk_profile uses the same
        # rule, so the two cannot describe one book with two different numbers.
        rows = book(["broker_book"] * 16) + book(["cn_snapshot"] * 2, sec_type="FUT_OPT")
        rec = Recorder()
        clause = mark_provenance.sentence(["broker_book"] * 16 + ["cn_snapshot"] * 2)
        cmp_check.check(report(clause), rows, rec, mark_provenance)
        self.assertTrue(rec.ok, rec.calls[-1][3])
        self.assertIn("16 of 18", clause)


if __name__ == "__main__":
    unittest.main()
