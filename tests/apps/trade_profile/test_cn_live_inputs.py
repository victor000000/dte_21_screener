import unittest
from apps.trade_profile.cn_live_inputs import native_ids, number

class CNInputTests(unittest.TestCase):
    def test_czce_year_uses_broker_expiry(self):
        self.assertEqual(native_ids(dict(symbol='MA701C3350',expiry='20261211')),
                         ('P_OP_ma2701C3350','nf_MA2701'))


    def test_nonfinite_numbers_are_missing(self):
        self.assertIsNone(number("nan"))
        self.assertIsNone(number("inf"))
