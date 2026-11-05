"""Integration tests for the profile query — the one that raised BinderException.

WHY THIS EXISTS. `calculate_risk_profile` reads the book through a CTE whose
outer SELECT aggregates columns the CTE must first select. When the hardcoded
`*100` was replaced with the stored contract size, `max(multiplier)` went into
the outer list and NOT into the CTE -- and the whole profile raised
`Binder Error: Referenced column "multiplier" not found` the next time it ran.

Every check the gate had passed on it. Compile cannot see SQL. The import sweep
never runs the function. The free-names and guard-last checks are about Python
names, not query columns. Nothing else executed the query -- and `make risk` had
not been run since the edit that broke it.

So this calls the real function against the real book. It is the cheapest thing
that would have caught it: no network (use_live=False), no writes, and it fails
with the database's own error message rather than a symptom.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import duckdb

from apps.trade_profile.complete_risk_analysis import calculate_risk_profile

DB = bootstrap.DATA_ROOT / "trades.duckdb"


@unittest.skipUnless(DB.exists(), "trades.duckdb not present")
class TestTheQueryRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(DB), read_only=True)
        cls.con.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' "
                        f"AS mh (READ_ONLY)")
        cls.rows = calculate_risk_profile(cls.con, use_live=False, market_open=False)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_it_returns_legs(self):
        self.assertTrue(self.rows, "the profile query returned nothing for a book "
                                   "that has positions")

    def test_every_row_carries_the_keys_the_caller_reads(self):
        # main() reads these by name. A query that stops producing one does not
        # raise here -- it raises later, in the report, as a KeyError with no
        # trace back to the SQL.
        need = {"underlying", "strike", "call_put", "broker", "account", "qty",
                "entry", "mark", "spot", "pnl_pct", "pnl_dollars", "target_50",
                "distance", "session", "theta", "vega", "delta", "gamma",
                "delta_notional"}
        for r in self.rows:
            missing = need - set(r)
            self.assertFalse(missing, f"{r.get('underlying')}: missing {missing}")

    def test_the_contract_multiplier_reaches_the_pnl(self):
        """The observable effect of the column that was missing from the CTE.

        `multiplier` is not a result key -- it is consumed to compute
        pnl_dollars. So the test is the ARITHMETIC, not the column: if the CTE
        stops carrying it the query raises, and if it carries the wrong value
        every dollar figure for that leg is out by 10x. On a US-only result the
        relation is exact.
        """
        self.assertTrue(self.rows)
        for r in self.rows:
            expected = ((r["entry"] - r["mark"]) * abs(r["qty"]) * 100
                        if r["qty"] < 0 else
                        (r["mark"] - r["entry"]) * r["qty"] * 100)
            self.assertAlmostEqual(
                r["pnl_dollars"], expected, places=2,
                msg=f"{r['underlying']} {r['strike']:g}{r['call_put']}: "
                    f"pnl_dollars {r['pnl_dollars']} != {expected} at multiplier 100 "
                    f"-- a CTE that lost the multiplier shows up exactly here")


if __name__ == "__main__":
    unittest.main()
