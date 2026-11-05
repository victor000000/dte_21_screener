"""The shape of the row the stock branch writes.

A column/placeholder drift in this INSERT is invisible to every check the gate has --
compile cannot see SQL -- exactly like the `multiplier` CTE omission that raised
BinderException at run time and that nothing else caught.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from tests.apps.plan.test_stock_row import FakeCon, SECTOR, run


def row_of(con):
    cols = [c.strip() for c in
            con.sql.split("INSERT INTO positions (")[1].split(")")[0].split(",")]
    return dict(zip(cols, con.params))


class TestTheRowShape(unittest.TestCase):
    def test_columns_and_placeholders_agree(self):
        con, _ = run(10.0)
        cols = con.sql.split("INSERT INTO positions (")[1].split(")")[0].split(",")
        ph = con.sql.split("VALUES (")[1].split(")")[0].split(",")
        self.assertEqual(len(cols), len(ph), "column/placeholder drift in the INSERT")
        self.assertEqual(len(con.params), len(cols), "params do not match the columns")

    def test_it_declares_itself_a_stock_priced_off_the_spot(self):
        con, _ = run(10.0)
        cols = [c.strip() for c in con.sql.split("INSERT INTO positions (")[1].split(")")[0].split(",")]
        row = dict(zip(cols, con.params))
        self.assertEqual(row["sec_type"], "STOCK")
        self.assertEqual(row["mark_source"], "spot", "a stock's mark IS its spot")
        self.assertEqual(row["multiplier"], 1.0, "a stock has no 100x contract")
        self.assertIsNone(row["strike"])

    def test_the_greeks_are_zero_not_null(self):
        # Zero, not NULL: `qty * None` is what crashed the build on a leg whose IV
        # could not be solved, and it took every OTHER leg down with it.
        con, _ = run(10.0)
        cols = [c.strip() for c in con.sql.split("INSERT INTO positions (")[1].split(")")[0].split(",")]
        row = dict(zip(cols, con.params))
        for g in ("gamma_units", "theta_day", "vega_pt"):
            self.assertEqual(row[g], 0.0, f"{g} must be 0.0, not None")
        self.assertEqual(row["delta_units"], -10.0, "delta IS qty for a stock")

    def test_a_short_stock_is_negative_delta(self):
        con, _ = run(10.0, qty=-10)
        cols = [c.strip() for c in con.sql.split("INSERT INTO positions (")[1].split(")")[0].split(",")]
        self.assertEqual(dict(zip(cols, con.params))["delta_units"], -10.0)


if __name__ == "__main__":
    unittest.main()
