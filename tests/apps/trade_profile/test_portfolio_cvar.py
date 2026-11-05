import unittest
from datetime import date, timedelta
import numpy as np
import QuantLib as ql
from apps.trade_profile.portfolio_cvar import tail_risk, calculate, horizon_date, leg_pnl


class PortfolioCVaRTests(unittest.TestCase):
    def test_fractional_tail_and_thresholds(self):
        r=tail_risk(-np.arange(21),200)
        self.assertAlmostEqual(r['cvar'], (20+19*.05)/1.05)
        self.assertEqual(r['var'],19)
        self.assertEqual(r['band'],'warning')
        self.assertEqual(tail_risk([-100]*20,1000)['band'],'over limit')
        self.assertEqual(tail_risk([-50]*20,1000)['band'],'warning')

    def test_invalid_inputs_and_all_gains(self):
        for v in ([0]*19, [float('nan')]*20, [float('inf')]*20):
            with self.assertRaises(ValueError): tail_risk(v,1000)
        for e in (0,-1,float('nan')):
            with self.assertRaises(ValueError): tail_risk([0]*20,e)
        self.assertEqual(tail_risk([10]*20,1000)['cvar'],-10)

    def test_calendar_excludes_thanksgiving(self):
        self.assertEqual(horizon_date(date(2026,11,25),1),date(2026,11,27))

    def fixture(self):
        today=date(2026,11,5)
        cal=ql.UnitedStates(ql.UnitedStates.NYSE)
        ds=[today-timedelta(days=i) for i in range(800,0,-1)]
        ds=[d for d in ds if cal.isBusinessDay(ql.Date(d.day,d.month,d.year))]
        history={d:100*np.exp(.08*np.sin(i/20)) for i,d in enumerate(ds)}
        leg=dict(symbol='SPY',underlying='SPY',kind='stock',qty=10,multiplier=1,spot=100,mark=100)
        return today,history,leg

    def test_hedge_is_scenario_netting_and_cash_counted_once(self):
        today,h,p=self.fixture()
        # Sell the held stock at $100: all future securities P&L cancels.
        rows=calculate([p],[dict(p,qty=-10)],{'SPY':h},10000,today,cashflow=1000)
        for row in rows:
            self.assertAlmostEqual(row['after']['cvar'],0,places=8)
            self.assertGreater(row['current']['cvar'],0)
            self.assertAlmostEqual(row['incremental_cvar'],-row['current']['cvar'])

    def test_missing_sessions_do_not_become_shorter_horizon(self):
        today,h,p=self.fixture()
        for d in list(h)[::2]: del h[d]
        rows=calculate([p],[],{'SPY':h},10000,today)
        self.assertTrue(all(r['status']=='unavailable' for r in rows))

    def test_options_within_horizon_and_multiplier(self):
        _,_,p=self.fixture()
        p.update(kind='option',expiry=date(2026,11,6),strike=100,iv=.3,right='C')
        with self.assertRaises(ValueError): leg_pnl(p,np.array([1]),date(2026,11,6))
        p.update(expiry=date(2027,1,15),multiplier=100,qty=-2,mark=8)
        v=leg_pnl(p,np.array([.9,1.1]),date(2026,11,6))
        one=leg_pnl(dict(p,multiplier=1,qty=1),np.array([.9,1.1]),date(2026,11,6))
        np.testing.assert_allclose(v,one*-200)
