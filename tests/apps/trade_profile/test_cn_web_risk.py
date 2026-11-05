import unittest
from apps.trade_profile.cn_web_risk import summarize


class CNRiskTests(unittest.TestCase):
    def test_position_delta_not_multiplied_by_quantity_twice(self):
        row=dict(account='a',venue='CZCE',root='MA',future='MA2701',qty=-10,entry=100,mark=90,
                 position_delta=-2,multiplier=10,underlying_price=2000,multiplier_source='manual·unverified')
        r=summarize([row]);self.assertEqual(r['legs'][0]['delta_pnl_up_1pct_cny'],-400)
        self.assertEqual(r['legs'][0]['profit_pct'],10)
        self.assertFalse(r['futures'][0]['multiplier_verified'])

    def test_missing_inputs_do_not_become_zero(self):
        row=dict(account='a',venue='CZCE',root='MA',future='MA2701',qty=-1,entry=1,mark=2,position_delta=None)
        result=summarize([row]);self.assertIsNone(result['futures'][0]['up_1pct_cny'])
