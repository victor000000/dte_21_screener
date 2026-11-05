import unittest
from datetime import datetime, timezone, timedelta
from data_providers.providers.option_quote import quote
from apps.trading_web.quote_selection import select, clock_session

SYMBOL='SPY261120P00600000'


class SelectionTests(unittest.TestCase):
    def result(self, source, bid, ask, stamp, feed='live'):
        return dict(status='responded',data=dict(rows=[dict(symbol=SYMBOL,quote=quote(SYMBOL,bid,ask,source=source,feed=feed,quote_time=stamp))]))

    def test_fresh_whole_book_wins_over_stale_and_indicative(self):
        now=datetime.now(timezone.utc)
        r=select([SYMBOL],dict(a=self.result('old',.5,1,(now-timedelta(days=1)).isoformat()),
                              b=self.result('fresh',2,3,now.isoformat()),c=self.result('indicative',4,5,now.isoformat(),'indicative')))
        self.assertEqual((r['rows'][0]['quote']['bid'],r['rows'][0]['quote']['ask']),(2,3))
        self.assertEqual(len(r['rows'][0]['alternatives']),3)

    def test_disagreement_disables_reference(self):
        now=datetime.now(timezone.utc).isoformat()
        row=select([SYMBOL],dict(a=self.result('a',1,1.01,now),b=self.result('b',2,2.01,now)))['rows'][0]
        self.assertTrue(row['disputed']);self.assertFalse(row['quote']['executable_reference'])

    def test_pre_post_not_dropped_and_missing_stays_missing(self):
        self.assertEqual(clock_session('2026-10-23T12:00:00Z'),'pre-market')
        self.assertEqual(clock_session('2026-10-23T21:00:00Z'),'post-market')
        self.assertIsNone(select([SYMBOL],{})['rows'][0]['quote']['midpoint'])
