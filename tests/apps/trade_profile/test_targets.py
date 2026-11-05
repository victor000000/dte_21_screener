import unittest
from apps.trade_profile.targets import analyze, pnl_pct

class Targets(unittest.TestCase):
    def test_long_and_short_reach_different_targets(self):
        short=analyze(10,5,-3)
        long=analyze(10,15,3)
        self.assertEqual(short['target_50'],5)
        self.assertEqual(long['target_50'],15)
        self.assertTrue(short['reached'] and long['reached'])
        self.assertEqual(short['distance'],0)
        self.assertEqual(pnl_pct(10,12,-3),-20)
        self.assertEqual(pnl_pct(10,12,3),20)
