from types import SimpleNamespace
import unittest
from apps.trade_profile.value_handoff_leg import value_handoff_leg

class HandoffGuard(unittest.TestCase):
    def test_unknown_side_never_reaches_valuation(self):
        legs=[]
        with self.assertRaises(AssertionError):
            value_handoff_leg(SimpleNamespace(),[],7,{},legs,{},
                              {'ABC':{'买卖':'unknown'}},'ABC',{})
        self.assertEqual(legs,[])
