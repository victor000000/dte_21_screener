import unittest
from datetime import datetime, timezone
from apps.trade_profile.cn_risk_context import group_scenarios
from apps.trade_profile.cn_live_status import status


class CNRiskContextTests(unittest.TestCase):
    def test_incomplete_model_never_reports_partial_stress_as_complete(self):
        model={'scenarios':[dict(move_pct=x,pnl_cny=x,iv_up_10pp_pnl_cny=x-10)
                            for x in (-10,-5,-3,-1,0,1,3,5,10)]}
        result=group_scenarios([{'model':model},{'model':None}])
        self.assertFalse(result['scenarios_complete'])
        self.assertTrue(all(r['pnl_cny'] is None for r in result['scenarios']))
        complete=group_scenarios([{'model':model},{'model':model}])
        self.assertTrue(complete['scenarios_complete'])
        self.assertEqual(complete['scenarios'][0]['iv_up_10pp_pnl_cny'],-40)

    def test_saved_expiry_reages_at_shanghai_midnight(self):
        report={'legs':[{'expiry':'20261211','dte':99}]}
        actual=status(report,datetime(2026,11,4,16,0,tzinfo=timezone.utc))
        self.assertEqual(actual['legs'][0]['dte'],36)
        self.assertEqual(report['legs'][0]['dte'],99)
