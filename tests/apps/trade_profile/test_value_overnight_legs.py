import datetime as dt
import unittest
from apps.trade_profile.value_overnight_legs import value_overnight_legs
from compute import bs

class PositionScale(unittest.TestCase):
    def test_quantity_applied_once_and_iv_shock_direction(self):
        baseline=dt.datetime(2026,10,1,20,tzinfo=dt.timezone.utc)
        expiry=dt.datetime(2026,11,20,21,tzinfo=dt.timezone.utc)
        t=(expiry-baseline).total_seconds()/(365*86400)
        mark=bs.bs_price(100,100,t,.04,.3,True)
        raw=[dict(ticker='ABC',expiry='2026-11-20',strike=100,call_put='C',qty=q,
                  entry=mark,observed_mark=mark) for q in (1,-2)]
        totals,rows=value_overnight_legs(baseline,baseline,.04,raw,
            {'ABC':{'overnight_price':105,'snapshot_update_utc':baseline.isoformat()}},{'ABC':100})
        self.assertAlmostEqual(rows[0]['calibrated_iv_pct'],30,places=4)
        self.assertGreater(rows[0]['iv_shock_+5pt_pnl_usd'],0)
        for field in ('estimated_pnl_usd','delta_notional_usd','vega_usd_pt'):
            self.assertAlmostEqual(rows[1][field],-2*rows[0][field])
            self.assertAlmostEqual(totals['ABC'][field],-rows[0][field])
