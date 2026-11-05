import unittest
from datetime import datetime, timezone
from apps.trade_profile.rolling_underlying import compare


class RollingTests(unittest.TestCase):
    def base(self):
        return dict(price=110, event_time='2026-10-23T12:00:00Z', adjustment='raw', bars=[
            dict(start='2026-10-22T11:59:00Z', close=100, volume=10),
            dict(start='2026-10-22T12:00:00Z', close=1, volume=10),
            dict(start='2026-10-22T11:59:30Z', close=1, volume=10)])

    def test_complete_only(self):
        r=compare(self.base(), datetime(2026,10,23,12,tzinfo=timezone.utc))
        self.assertAlmostEqual(r['return_24h_pct'],10)
        self.assertEqual(r['reference_gap_seconds'],0)

    def test_gaps_and_zero_volume(self):
        b=self.base();b['bars'][0]['volume']=0
        self.assertIsNone(compare(b)['return_24h_pct'])
        b['bars']=[dict(start='2026-10-21T11:59:00Z',close=100,volume=1)]
        self.assertIsNone(compare(b)['return_24h_pct'])

    def test_unknown_clock_and_future(self):
        b=self.base();b['event_time']=None
        self.assertIsNone(compare(b)['return_24h_pct'])
        self.assertIsNone(compare(self.base(),datetime(2026,10,22,tzinfo=timezone.utc))['return_24h_pct'])
