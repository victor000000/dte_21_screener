"""test_board.py — series selection and the rendered board."""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from apps.screener.cn_iv import board as B  # noqa: E402

DAY = dt.date(2026, 9, 30)


def series(n, start=0.10):
    return [(DAY - dt.timedelta(days=n - i), start + i * 0.001) for i in range(n)]


UNIVERSE = [("SR", "CZCE", "白糖期权"), ("SI", "GFEX", "工业硅"), ("M", "DCE", "豆粕期权")]


class TestPickSeries(unittest.TestCase):
    def test_the_longest_rankable_series_wins(self):
        # SC carries a 64-point series and a ~420-point one from the same exchange; ranking
        # on 64 points when 420 are stored wastes the deeper series.
        src, rows = B.pick_series({"akshare_sc_hist": series(64), "akshare_sc_vol": series(120)})
        self.assertEqual(src, "akshare_sc_vol")
        self.assertEqual(len(rows), 120)

    def test_a_too_short_series_is_still_returned_not_dropped(self):
        # It has to be, or the board cannot say "pending" about it.
        src, rows = B.pick_series({"only": series(10)})
        self.assertEqual((src, len(rows)), ("only", 10))

    def test_one_source_only_never_a_mixture(self):
        src, rows = B.pick_series({"a": series(70), "b": series(30)})
        self.assertEqual(src, "a")
        self.assertTrue(all(d >= DAY - dt.timedelta(days=70) for d, _ in rows))


class TestBuildBoard(unittest.TestCase):
    def _board(self, series_by_product, bars=None):
        return B.build_board(UNIVERSE, series_by_product, bars or {})

    def test_a_product_with_no_series_still_appears(self):
        # Iterating iv_history instead of the map would silently drop it -- the board would
        # look complete while a whole product was missing from it.
        b = self._board({"SR": {"s": series(120)}})
        self.assertEqual({e["product"] for e in b}, {"SR", "SI", "M"})
        self.assertIsNone(next(e for e in b if e["product"] == "SI")["res"])

    def test_ranked_products_come_first_and_in_ivr_order(self):
        b = self._board({"SR": {"s": series(120)}})
        self.assertEqual(b[0]["product"], "SR")
        self.assertGreaterEqual(b[0]["res"]["ivr"], 90)   # latest is the series maximum

    def test_bars_are_carried_so_rankable_is_not_read_as_tradable(self):
        b = self._board({"SI": {"s": series(120)}}, bars={"SI": (5000, DAY)})
        entry = next(e for e in b if e["product"] == "SI")
        self.assertEqual((entry["bars"], entry["last_bar"]), (5000, DAY))


class TestRender(unittest.TestCase):
    def test_unrankable_products_are_named_as_a_gap_in_our_data(self):
        text = B.render(B.build_board(UNIVERSE, {"SR": {"s": series(120)}}, {}), DAY, 35.0)
        self.assertIn("not rankable", text)
        self.assertIn("SI", text)
        self.assertIn("gap in our data", text)

    def test_the_header_states_the_data_day_not_just_today(self):
        # Golden Week freezes every series for eight days while the clock keeps moving; a
        # table headed only with today's date reads as a live board.
        text = B.render(B.build_board(UNIVERSE, {"SR": {"s": series(120)}}, {}), DAY, 35.0)
        self.assertIn("**Data through 2026-09-30**", text)

    def test_pass_count_is_over_rankable_products_only(self):
        text = B.render(B.build_board(UNIVERSE, {"SR": {"s": series(120)}}, {}), DAY, 35.0)
        self.assertIn("1 of 1 rankable (3 products", text)


if __name__ == "__main__":
    unittest.main()
