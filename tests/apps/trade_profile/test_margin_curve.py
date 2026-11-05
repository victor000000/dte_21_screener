import unittest
from apps.trade_profile.margin_curve import naked_core, position_margin

class MarginArithmetic(unittest.TestCase):
    def test_call_and_put_floor_use_different_bases(self):
        self.assertEqual(naked_core(200,100,'P',2,100),2000)
        self.assertEqual(naked_core(100,200,'C',2,100),2000)
        self.assertEqual(position_margin(100,[],.1),(0,0))
    def test_two_short_one_long_leaves_one_naked(self):
        short=dict(cp='P',qty=-2,mult=100,K=90,iv=.3)
        wing=dict(cp='P',qty=1,mult=100,K=80,iv=.3)
        total,core=position_margin(100,[short,wing],.1)
        self.assertEqual(core,naked_core(100,90,'P',1,100))
        self.assertGreater(total,core)
