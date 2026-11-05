"""Tests for persisting a run to trades.leg_estimates.

Tier 2: needs the databases. Skips itself on a runner, which is the same
contract the gate's --full checks use.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

import duckdb

from apps.trade_profile.leg_estimates import persist
from apps.trade_profile.leg_estimates.constants import HARVEST

DB = bootstrap.DATA_ROOT / "trades.duckdb"


class TestSchemaContract(unittest.TestCase):
    """The table is read by apps/audit/risk_profile_check.py, so its columns are an API."""

    def test_ddl_declares_the_columns_the_checker_reads(self):
        import inspect
        src = inspect.getsource(persist.save)
        for col in ("underlying", "strike", "call_put", "mark", "est_price",
                    "run_ts", "sec_type"):
            self.assertIn(col, src, f"risk_profile_check reads {col} from this table")

    def test_the_table_is_keyed(self):
        # selfcheck asserts every table has a key; this one must not be the
        # exception that gets the assertion relaxed.
        import inspect
        self.assertIn("PRIMARY KEY", inspect.getsource(persist.save))

    def test_the_empty_guard_is_inside_this_function(self):
        # scripts/check_regressions.py walks outward from an executemany and stops
        # at the nearest FunctionDef, so a caller-side guard would not be seen and
        # the gate would fail on code with identical behaviour.
        import inspect
        src = inspect.getsource(persist.save)
        # The CALL, not the word: the docstring above the guard legitimately
        # mentions check_regressions.py's executemany walk, and matching that
        # occurrence made this test compare the guard against a comment.
        call = src.index("con.executemany(")
        guard = src.index("if rows:")
        self.assertLess(guard, call, "the guard must precede the call, in this function")


@unittest.skipUnless(DB.exists(), "trades.duckdb not present")
class TestSaveRoundTrip(unittest.TestCase):
    def test_the_table_exists_with_the_shape_the_checker_reads(self):
        # Read-only, always: DuckDB caches database instances by path within one
        # process, and opening the same file read-write in one test while another
        # holds it read-only fails with "different configuration than existing
        # connections" -- which reads like a corrupt database and is not.
        con = duckdb.connect(str(DB), read_only=True)
        try:
            cols = [c[0] for c in con.execute("DESCRIBE leg_estimates").fetchall()]
        finally:
            con.close()
        for c in ("reached_50", "pnl_pct_est", "est_price", "run_ts"):
            self.assertIn(c, cols)

    def test_reached_50_is_derived_from_harvest(self):
        # The stored boolean and the narrative must agree about what "reached"
        # means, or the table and the report tell different stories.
        import inspect
        self.assertIn("HARVEST", inspect.getsource(persist.save))


if __name__ == "__main__":
    unittest.main()
