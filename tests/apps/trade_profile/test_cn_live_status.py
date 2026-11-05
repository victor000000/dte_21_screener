import unittest
from datetime import datetime, timezone
from apps.trade_profile.cn_live_status import status

class CNStatusTests(unittest.TestCase):
    def test_saved_quote_reages_without_mutating_evidence(self):
        report = {'legs':[{'quote':{'quote_time':'2026-10-26T09:00:00+08:00',
            'depth_covers_qty':False}, 'model':{}, 'as_of':'2026-10-23 09:00:00'}]}
        fresh = status(report, datetime(2026,10,26,1,0,15,tzinfo=timezone.utc))
        old = status(report, datetime(2026,10,26,1,1,tzinfo=timezone.utc))
        self.assertEqual(fresh['freshness']['recent'],1)
        self.assertEqual(old['freshness']['stale'],1)
        self.assertEqual(old['freshness']['verified_live'],0)
        self.assertNotIn('age_seconds',report['legs'][0]['quote'])
        self.assertEqual(old['freshness']['insufficient_depth'],1)

    def test_missing_and_future_times_never_count_as_recent(self):
        r = status({'legs':[{}, {'quote':{'quote_time':'2099-01-01T00:00:00Z'}}]})
        self.assertEqual(r['freshness']['missing'],1)
        self.assertEqual(r['freshness']['stale'],1)
        self.assertEqual(r['freshness']['recent'],0)
