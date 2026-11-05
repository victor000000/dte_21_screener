import unittest
from datetime import datetime, timezone
from apps.trade_profile.cn_live_valuation import value_leg

class CNModelTests(unittest.TestCase):
    def setUp(self):
        self.p = dict(symbol='lc2701-P-87000', expiry='20261207', strike=87000,
                      qty=-1, entry=2020, right='P', position_delta=.242)
        self.now = datetime(2026,10,26,0,tzinfo=timezone.utc)
        self.evidence = dict(multiplier=1,multiplier_basis='test evidence')
        f = ['0']*33
        for i,v in {0:'1',1:'2590',3:'3200',4:'1',7:'87000',32:'2026-10-23 15:03:50'}.items():
            f[i]=v
        self.fields = {'P_OP_lc2701P87000':f}

    def test_model_scaling_and_signs(self):
        u=['0']*18
        u[1]='150107';u[8]='97280';u[17]='2026-10-23'
        fields=dict(self.fields,nf_LC2701=u)
        a=value_leg(self.p,fields,self.now,self.evidence)['model']
        b=value_leg(dict(self.p,qty=-3),fields,self.now,self.evidence)['model']
        self.assertIsNotNone(a)
        for key in ('position_delta','up_1pct_cny','down_1pct_cny','vega_cny_per_point','theta_cny_per_day'):
            self.assertAlmostEqual(b[key],3*a[key])
        self.assertGreater(a['up_1pct_cny'],0)
        self.assertLess(a['down_1pct_cny'],0)
        self.assertLess(a['vega_cny_per_point'],0)
        self.assertLess(a['gamma_pnl_1pct_cny'],0)


        self.assertEqual(len(a['scenarios']),9)
        self.assertAlmostEqual(a['scenarios'][4]['pnl_cny'],0,places=6)
        for x,y in zip(a['scenarios'],b['scenarios']):
            self.assertAlmostEqual(y['pnl_cny'],3*x['pnl_cny'])
            self.assertLess(x['iv_up_10pp_pnl_cny'],x['pnl_cny'])
