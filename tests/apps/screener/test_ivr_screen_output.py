"""A high IV percentile must not pass an IV-rank threshold or be persisted as IVR."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

import duckdb
from apps.screener import screener_21dte_v2 as screen
from tests.compute.test_iv_rank import rows


class TestScreenRankOutput(unittest.TestCase):
    def run_screen(self, values):
        today = dt.date(2026, 10, 16)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "screen.duckdb"
            con = duckdb.connect(str(path))
            con.execute("CREATE SCHEMA mh; CREATE SCHEMA ref")
            con.execute("CREATE TABLE mh.iv_history (underlying TEXT, source TEXT, day DATE, atm_iv DOUBLE)")
            con.execute("CREATE TABLE ref.calendar (venue TEXT, day DATE, is_open BOOLEAN)")
            con.execute("CREATE TABLE ref.events (day DATE, kind TEXT, name TEXT, importance TEXT)")
            con.execute("CREATE TABLE ref.earnings (underlying TEXT, day DATE, timing TEXT)")
            for source, day, value in rows(values):
                con.execute("INSERT INTO mh.iv_history VALUES ('META', ?, ?, ?)", [source, day, value])
            put = {"K": 90.0, "delta": -0.19, "mark": 1.0}
            call = {"K": 110.0, "delta": 0.19, "mark": 1.0}
            with mock.patch.object(screen.db, "connect", return_value=con), \
                 mock.patch.object(screen, "ROOT", pathlib.Path(tmp)), \
                 mock.patch.object(screen.clock, "today", return_value=today), \
                 mock.patch.object(screen, "spot_and_hv", return_value=(100.0, 0.2)), \
                 mock.patch.object(screen, "smile_legs", return_value=(put, call, 0.0, None)), \
                 mock.patch("sys.argv", ["screen", "--symbols", "META"]):
                screen.main()
            with duckdb.connect(str(path)) as saved:
                audit = saved.execute("SELECT ivr, flag FROM screener_runs").fetchone()
            report = (pathlib.Path(tmp) / "reports" / f"screener_{today}.md").read_text()
        return audit, report

    def test_report_gate_and_audit_use_range_rank(self):
        (ivr, flag), report = self.run_screen([0.1] * 58 + [1.1, 0.2])
        self.assertAlmostEqual(ivr, 10.0)
        self.assertEqual(flag, "WATCH")
        self.assertIn("| 10 |", report)
        self.assertIn("IVR = 100 * (latest IV - min IV) / (max IV - min IV)", report)
        self.assertNotIn("percentile of the latest IV", report)

    def test_invalid_latest_iv_is_reported_without_crashing(self):
        for value in (float("nan"), float("inf"), 0.0, -0.1):
            with self.subTest(value=value):
                (ivr, flag), report = self.run_screen([0.1] * 59 + [value])
                self.assertIsNone(ivr)
                self.assertEqual(flag, "NO-IV")
                cells = next(line for line in report.splitlines()
                             if line.startswith("| META |")).split("|")
                for index in (3, 4, 7):  # ATM IV, IVR and VRP must be unavailable.
                    self.assertEqual(cells[index].strip(), "-")

    def test_iv_and_hv_are_both_displayed_as_percentages(self):
        _, report = self.run_screen([0.1] * 59 + [0.3])
        self.assertIn("ATM IV %", report)
        self.assertIn("HV30 %", report)
        cells = next(line for line in report.splitlines()
                     if line.startswith("| META |")).split("|")
        self.assertEqual(cells[3].strip(), "30.0")
        self.assertEqual(cells[6].strip(), "20.0")
        self.assertEqual(cells[7].strip(), "10.0")


if __name__ == "__main__":
    unittest.main()
