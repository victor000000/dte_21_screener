"""Two expiries and repeat captures must retain coherent snapshot rows."""
import datetime as dt
import unittest

import duckdb
from apps.trade_profile.complete_risk_analysis import save_risk_snapshot


def leg(expiry, qty=-1, mark=2.):
    return dict(underlying="XYZ", strike=100., call_put="P", account="a", broker="IBKR",
                expiry=expiry, qty=qty, entry=10., mark=mark, spot=100., pnl_pct=80.,
                pnl_dollars=800., target_50=5., distance=0., session="snapshot",
                source="snapshot", delta=-20., theta=3., vega=-10.,
                spot_source="snapshot", mark_source="snapshot", snap_iv=.3)


class TestSaveSnapshots(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.addCleanup(self.con.close)
        self.nov, self.dec = dt.date(2026, 11, 20), dt.date(2026, 12, 18)
        self.stamp = dt.datetime(2026, 10, 16)

    def save(self, snap, live):
        save_risk_snapshot(self.con, snap, live, self.stamp, self.stamp)

    def test_both_months_keep_their_own_prices_and_quantities(self):
        rows = [leg(self.nov), leg(self.dec, qty=-2, mark=8.)]
        self.save(rows, list(reversed(rows)))
        self.assertEqual(self.con.execute("SELECT expiry,qty,live_mark FROM risk_snapshots ORDER BY expiry").fetchall(),
                         [(self.nov, -1, 2.), (self.dec, -2, 8.)])

    def test_resaving_one_contract_refreshes_all_its_values(self):
        row = leg(self.nov)
        self.save([row], [row])
        updated = dict(row, qty=-3, mark=4., spot=110., pnl_pct=60., pnl_dollars=1800.,
                       snap_iv=.45, delta=-50., source="TWS")
        self.save([updated], [updated])
        self.assertEqual(self.con.execute("SELECT count(*) FROM risk_snapshots").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT qty,live_mark,live_spot,live_pnl_dollars,snap_iv,delta_units,price_source FROM risk_snapshots").fetchone(),
                         (-3, 4., 110., 1800., .45, -50., "TWS"))
