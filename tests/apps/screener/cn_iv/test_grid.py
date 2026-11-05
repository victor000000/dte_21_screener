"""test_grid.py — the strike ladder built by hand for a product Sina's page omits."""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from unittest import mock  # noqa: E402

from apps.screener.cn_iv import chains  # noqa: E402

D1, D2 = dt.date(2026, 9, 1), dt.date(2026, 9, 30)


class TestSyntheticGrid(unittest.TestCase):
    def test_builds_codes_on_the_exchange_grid(self):
        # Sina serves 聚丙烯 contracts by code but omits the product from the page chain_table
        # scrapes. 100 CNY is the exchange's own step (8500/8600/8700 exist on pp2611;
        # 8550/8650 do not), verified 2026-10-07.
        g = chains.synthetic_grid(100, {D2: 8620.0}, D1, D2, "pp2611")
        ks = [k for k, _, _ in g]
        self.assertIn(8600.0, ks)
        self.assertNotIn(8650.0, ks)
        self.assertEqual(len(ks), len(set(ks)), "no duplicate strikes")
        self.assertEqual(g[0][1][:6], "pp2611")

    def test_no_forward_in_the_window_builds_nothing(self):
        self.assertEqual(chains.synthetic_grid(100, {}, D1, D2, "pp2611"), [])

    def test_the_grid_brackets_every_forward_in_the_window(self):
        # The ladder must cover the whole range the future visits, not just today's level --
        # wanted_strikes then picks the ATM one per day out of it.
        ks = [k for k, _, _ in chains.synthetic_grid(100, {D1: 8000.0, D2: 8620.0},
                                                     D1, D2, "pp2611")]
        self.assertLessEqual(min(ks), 8000.0)
        self.assertGreaterEqual(max(ks), 8620.0)

    def test_a_failed_table_call_is_not_rescued_by_synthesis(self):
        # The guard that matters: a month whose TABLE call failed is an unlisted month, and
        # synthesizing a ladder for it is how a third of one run got spent on contracts that
        # do not exist. month_grid must raise for a product with no step, and only build a
        # ladder when the product is known to be absent from Sina's page (step given).
        def boom(ak, venue, name, ymd):
            raise KeyError("up")
        with mock.patch.object(chains, "chain_table", side_effect=boom):
            with self.assertRaises(KeyError):
                chains.month_grid(None, "DCE", "豆粕期权", "m2609", None, {D1: 8000.0}, D1, D2)
            got = chains.month_grid(None, "DCE", "豆粕期权", "m2609", 100, {D1: 8000.0}, D1, D2)
        self.assertTrue(got, "with a step, the ladder is built instead of read")


if __name__ == "__main__":
    unittest.main()
