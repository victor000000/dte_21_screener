import unittest
from datetime import datetime, timezone
from apps.trade_profile.cn_live_valuation import value_leg
from apps.trade_profile.cn_web_risk import summarize


class CNLiveLegTests(unittest.TestCase):
    def setUp(self):
        self.p = dict(symbol='lc2701-P-87000', expiry='20261207', strike=87000,
                      qty=-1, entry=2020, right='P', position_delta=.242)
        self.now = datetime(2026,10,26,0,tzinfo=timezone.utc)
        self.evidence = dict(multiplier=1,multiplier_basis='test evidence')
        f = ['0']*33
        for i,v in {0:'1',1:'2590',3:'3200',4:'1',7:'87000',32:'2026-10-23 15:03:50'}.items():
            f[i]=v
        self.fields = {'P_OP_lc2701P87000':f}

    def test_lc_price_replaces_zero_export_without_reusing_export_delta(self):
        r=value_leg(dict(self.p,mark=0),self.fields,self.now,self.evidence)
        self.assertEqual(r['close_pnl_cny'],-1180)
        self.assertAlmostEqual(r['premium_pnl_pct'],-1180/2020*100)
        self.assertEqual(r['position_delta'],.242)
        self.assertIsNone(r['model'])
        self.assertEqual(r['quote']['status'],'Dated / stale')

    def test_long_uses_bid_and_quantity_scaled_once(self):
        r=value_leg(dict(self.p,qty=3),self.fields,self.now,dict(multiplier=10))
        self.assertEqual(r['close_pnl_cny'],3*10*(2590-2020))
        self.assertFalse(r['quote']['depth_covers_qty'])

    def test_bad_books_never_become_profit(self):
        for index,value in [(1,'0'),(1,'3300'),(3,'nan'),(4,'0'),(7,'88000'),(32,'2026-10-27 15:00:00')]:
            fields={k:list(v) for k,v in self.fields.items()}
            fields['P_OP_lc2701P87000'][index]=value
            r=value_leg(self.p,fields,self.now,self.evidence)
            self.assertIsNone(r['close_pnl_cny'],(index,value))
            self.assertIsNone(r['quote'],(index,value))

    def test_missing_multiplier_keeps_percentage_but_omits_cash(self):
        r=value_leg(self.p,self.fields,self.now,dict(multiplier=None))
        self.assertIsNone(r['close_pnl_cny'])
        self.assertIsNotNone(r['premium_pnl_pct'])

    def test_old_positions_view_rejects_zero_placeholder(self):
        r=summarize([dict(self.p,mark=0,account='a',venue='GFEX',root='LC',future='LC2701')])
        self.assertIsNone(r['legs'][0]['profit_pct'])
