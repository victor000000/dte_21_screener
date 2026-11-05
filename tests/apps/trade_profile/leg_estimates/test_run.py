"""Tests for the orchestration."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

import duckdb

from apps.trade_profile.leg_estimates import run

DB = bootstrap.DATA_ROOT / "trades.duckdb"


class TestEntryPoint(unittest.TestCase):
    def test_main_is_callable_with_argv(self):
        # Threading argv through (rather than reading sys.argv inside) is what
        # makes --account testable at all.
        import inspect
        self.assertIn("argv", inspect.signature(run.main).parameters)

    def test_it_refuses_to_estimate_without_the_native_solver(self):
        # The estimate is DEFINED as the QuantLib price; the pure-Python fallback
        # is a different model and would make these numbers a third thing. The
        # assert must stay ahead of any work.
        import inspect
        src = inspect.getsource(run.main)
        self.assertIn("USING_QUANTLIB", src)
        self.assertLess(src.index("USING_QUANTLIB"), src.index("db.connect"))


@unittest.skipUnless(DB.exists(), "trades.duckdb not present")
class TestRtMoves(unittest.TestCase):
    def test_returns_a_percentage_per_underlying(self):
        con = duckdb.connect(str(DB), read_only=True)
        con.execute(f"ATTACH IF NOT EXISTS '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' AS mh (READ_ONLY)")
        try:
            rows = [{"underlying": "EWZ"}, {"underlying": "TLT"}]
            moves = run.rt_moves_for(con, rows)
        finally:
            con.close()
        self.assertTrue(moves, "no move computed for a book that has those underlyings")
        for u, v in moves.items():
            self.assertLess(abs(v), 100, f"{u}: {v}% is not a daily move")

    def test_an_unknown_underlying_is_simply_absent(self):
        # Absent, not zero: the narrative prints a move only when it has one, and
        # a fabricated 0.0% would read as "the underlying did not move".
        con = duckdb.connect(str(DB), read_only=True)
        con.execute(f"ATTACH IF NOT EXISTS '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' AS mh (READ_ONLY)")
        try:
            moves = run.rt_moves_for(con, [{"underlying": "NOSUCHTICKER"}])
        finally:
            con.close()
        self.assertNotIn("NOSUCHTICKER", moves)


if __name__ == "__main__":
    unittest.main()
