"""test_symbol_map.py — the map must never be written incomplete, and must carry the
spellings we had to derive by hand."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from unittest import mock  # noqa: E402

from apps.data_ops import build_symbol_map  # noqa: E402

# One cn_product_map row, as the SELECT in rows_from_universes reads it.
MAP_ROW = ("CN:CZCE:MA", "CZCE", "MA", "MA", "ep", "YMM", ["close"])


class TestCnTruncationGuard(unittest.TestCase):
    def test_an_unreadable_cn_product_map_refuses_to_write_the_map(self):
        # DuckDB refuses even a READ-ONLY open while a writer holds cn_market.duckdb, and a
        # CN downloader holds it for hours — so this is the ordinary case, not an edge one.
        # Measured 2026-10-07: the pipeline running behind the CZCE repair blocked the read
        # and the builder's own except clause carried on regardless. Every CN row comes from
        # cn_product_map, so carrying on overwrites plans/symbol_map.csv with a map missing
        # all of them — and a truncated map is indistinguishable from a complete one to
        # whoever reads it next, which is the failure this table exists to prevent.
        with mock.patch("duckdb.connect", side_effect=RuntimeError("Conflicting lock is held")):
            with self.assertRaises(SystemExit) as caught:
                build_symbol_map.rows_from_universes()
        self.assertEqual(caught.exception.code, 3,
                         "must exit non-zero — a supervisor has to read this as a failure")

    def test_the_cn_rows_survive_a_readable_map(self):
        # The guard must not be a blanket refusal. With the map readable, both derivations
        # land: the rows straight from cn_product_map, and the CN product list from
        # plans/universe_futures_cn.txt, which needs no database at all.
        con = mock.MagicMock()
        con.execute.return_value.fetchall.return_value = [MAP_ROW]
        with mock.patch("duckdb.connect", return_value=con):
            rows = build_symbol_map.rows_from_universes()
        self.assertIn(("CN:CZCE:MA", "akshare", "MA", "cn_future",
                       "CZCE MA; code format YMM"), rows)
        self.assertIn("CN:INE:SC", {r[0] for r in rows if r[3] == "cn_future"})


class TestSinaSpellings(unittest.TestCase):
    def test_sina_gets_its_own_spelling_derived_from_the_map(self):
        # Sina spells CZCE codes at a different LENGTH than the exchange: the exchange
        # writes SR611 (YMM), Sina wants SR2611 (YYMM) and returns an EMPTY FRAME for the
        # exchange's form. An empty frame reads as "no data", so the spelling has to be in
        # the map rather than re-probed by the next consumer (verified 2026-10-07:
        # SR611 -> 0 rows, SR2611 -> 214).
        con = mock.MagicMock()
        con.execute.return_value.fetchall.return_value = [MAP_ROW]
        with mock.patch("duckdb.connect", return_value=con):
            rows = build_symbol_map.rows_from_universes()
        self.assertIn(("CN:CZCE:MA", "sina", "MA0", "cn_future",
                       "CZCE MA: Sina continuous front month (M0-style)"), rows)
        self.assertIn("MA<YYMM>", {r[2] for r in rows if r[1] == "sina"},
                      "the YYMM form must be recorded next to the exchange's YMM")


class TestClassShareSpellings(unittest.TestCase):
    def test_futu_and_theta_stock_use_dotted_class_suffixes(self):
        con=mock.MagicMock();con.execute.return_value.fetchall.return_value=[MAP_ROW]
        with mock.patch('duckdb.connect',return_value=con):
            rows=build_symbol_map.rows_from_universes()
        mappings={(canon,source):symbol for canon,source,symbol,*_ in rows}
        self.assertEqual(mappings[('BRK B','futu')],'US.BRK.B')
        self.assertEqual(mappings[('BRK B','thetadata_stock')],'BRK.B')
        self.assertEqual(mappings[('BRK B','alpaca')],'BRKB')


if __name__ == "__main__":
    unittest.main()
