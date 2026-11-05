"""Attribution presentation must preserve units, gaps, and missing-data semantics."""
import csv
import tempfile
import unittest
from pathlib import Path
from apps.trade_profile.web_attribution import grouped, report, rows, DEFAULT


class AttributionTests(unittest.TestCase):
    def test_already_scaled_dollars_are_not_multiplied_again(self):
        leg=dict(broker='test',underlying='SPY',qty_carried=-3,multiplier=100,
                 delta_linear_usd=-20,spot_usd=-50,vega_usd=-10,theta_usd=15,
                 flow_pnl_native_usd=2,residual_usd=0,carried_pnl_native_usd=-45)
        item=grouped([leg,leg])[0]
        self.assertEqual(item['delta_usd'],-40)
        self.assertEqual(item['gamma_usd'],-60)
        self.assertEqual(item['pnl_usd'],-86)

    def test_missing_component_stays_unknown(self):
        row=dict(broker='test',underlying='SPY')
        self.assertIsNone(grouped([row])[0]['pnl_usd'])
        self.assertIsNone(grouped([row])[0]['gamma_usd'])

    def test_empty_and_nonfinite_are_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.csv'
            path.write_text('day,vega_usd,theta_usd,delta_usd\n2026-10-01,,nan,0\n')
            value=rows(path)[0]
            self.assertIsNone(value['vega_usd']);self.assertIsNone(value['theta_usd'])
            self.assertEqual(value['delta_usd'],0)

    def test_missing_report_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            result=report(folder=folder)
            self.assertFalse(result['available']);self.assertEqual(result['days'],[])

    @unittest.skipUnless((DEFAULT/"daily_attribution.csv").exists(), "Private dated report is not distributed")
    def test_saved_days_reconcile_including_account_gap(self):
        result=report()
        self.assertTrue(result['available'])
        self.assertTrue(any(r['combined_usd']>0 for r in result['daily']))
        self.assertTrue(any(r['combined_usd']<0 for r in result['daily']))
        for day in result['days']:
            daily=report(day)
            self.assertLess(abs(daily['summary']['reconciliation_gap']),0.01)
            for row in daily['volatility']:
                if row['iv_minus_rv_points'] is not None:
                    self.assertAlmostEqual(row['iv_minus_rv_points'],100*(row['iv_prev']-row['rv10']))
        self.assertFalse(report('2099-01-01')['available'])
        self.assertFalse(report('../../private')['available'])
