import unittest
from apps.trade_profile import profit_targets as m

class PriceTargets(unittest.TestCase):
    def test_both_rights_solve_back_to_target(self):
        for call in (True,False):
            spot=m.solve_price(100,.1,.3,call,5)
            self.assertAlmostEqual(m.bs.bs_price(spot,100,.1,m.R,.3,call),5,places=8)
        self.assertIsNone(m.solve_price(100,0,.3,True,5))
        self.assertIsNone(m.solve_price(100,.1,None,True,5))
