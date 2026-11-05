"""test_rank_ivr_cn.py — the query behind the board: which products and which series."""
import datetime as dt
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import duckdb  # noqa: E402

from apps.screener import rank_ivr_cn as entry  # noqa: E402

D = dt.date(2026, 9, 30)


def build_db():
    path = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE iv_history (day DATE, underlying VARCHAR, expiry DATE, "
                "atm_iv DOUBLE, spot DOUBLE, source VARCHAR)")
    con.execute("CREATE TABLE option_bars (product VARCHAR, day DATE, close DOUBLE)")
    con.execute("CREATE TABLE cn_product_map (canonical VARCHAR, venue VARCHAR, product VARCHAR, "
                "ak_symbol VARCHAR, endpoint VARCHAR, code_format VARCHAR, price_cols VARCHAR, "
                "note VARCHAR)")
    con.execute("INSERT INTO cn_product_map VALUES ('CN:CZCE:SR','CZCE','SR','SR','e','YMM','x','n')")
    con.execute("INSERT INTO cn_product_map VALUES ('CN:SHFE:CU','SHFE','CU','铜期权','e','YYMM','x','n')")
    con.execute("INSERT INTO iv_history VALUES (?, 'SR', NULL, 0.23, NULL, 'akshare_sr_hist')", [D])
    con.execute("INSERT INTO iv_history VALUES (?, 'SR', NULL, NULL, NULL, 'akshare_sr_hist')", [D])
    con.execute("INSERT INTO option_bars VALUES ('SR', ?, 1.0)", [D])
    con.close()
    return path


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.db = build_db()
        self.universe, self.series, self.bars = entry.load(self.db)
        self.addCleanup(lambda: pathlib.Path(self.db).unlink())

    def test_the_universe_is_the_map_not_the_series(self):
        # CU has no series at all and must still be listed -- otherwise a whole venue can be
        # missing from a board that looks complete.
        self.assertEqual({u[0] for u in self.universe}, {"SR", "CU"})
        self.assertIn("CU", self.universe[1][0] + self.universe[0][0])

    def test_null_iv_rows_are_not_a_series_point(self):
        self.assertEqual(len(self.series["SR"]["akshare_sr_hist"]), 1)

    def test_bars_are_read_per_product(self):
        self.assertEqual(self.bars["SR"][0], 1)


class TestReportWrite(unittest.TestCase):
    def test_write_names_the_file_for_the_clock_the_repo_uses(self):
        # reports/ names come from clock.today() (UTC), and the report's own header states
        # the DATA day -- the two are different clocks on purpose.
        db = build_db()
        out = pathlib.Path(tempfile.mkdtemp()) / "reports"
        try:
            with unittest.mock.patch.object(sys, "argv",
                                            ["x", "--db", db, "--write"]), \
                 unittest.mock.patch.object(entry, "REPORTS", out):
                entry.main()
            written = list(out.glob("ivr_cn_*.md"))
            self.assertEqual(len(written), 1)
            self.assertIn("Data through 2026-09-30", written[0].read_text())
        finally:
            pathlib.Path(db).unlink()


if __name__ == "__main__":
    unittest.main()
