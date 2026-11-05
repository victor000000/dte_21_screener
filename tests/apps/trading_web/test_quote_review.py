import unittest
from datetime import datetime, timezone
from apps.trading_web.quote_review import review_quotes
from apps.trading_web.tickets import normalize
from data_providers.providers.option_quote import quote
from .support import ticket


class QuotesTests(unittest.TestCase):
    def test_order_sized_natural_and_midpoint_sign(self):
        raw=ticket();raw['effect']='credit';raw['legs'][0]['intent']='sell_to_open'
        second=raw['legs'][0].copy();second.update(strike='545',intent='buy_to_open');raw['legs'].append(second)
        t=normalize(raw);now=datetime.now(timezone.utc).isoformat()
        rows=[{'symbol':l['symbol'],'quote':quote(l['symbol'],*prices,10,10,source='test',feed='opra',quote_time=now)}
              for l,prices in zip(t['legs'],[(2,2.2),(.8,1)])]
        class Market:
            def quotes(self,*args):return {'rows':rows}
        result=review_quotes(Market(),t,'alpaca')
        self.assertEqual(result['natural_debit'],-1)
        self.assertEqual(result['midpoint_debit'],-1.2)
        self.assertFalse(result['requires_ack'])

    def test_missing_and_indicative_need_ack_not_synthetic_prices(self):
        t=normalize(ticket())
        class Market:
            def quotes(self,*args):return {'rows':[]}
        r=review_quotes(Market(),t,'alpaca')
        self.assertTrue(r['requires_ack']);self.assertIsNone(r['natural_debit'])

    def test_future_timestamp_requires_ack_even_if_source_claims_executable(self):
        from datetime import timedelta
        from unittest.mock import Mock
        t=normalize(ticket());symbol=t['legs'][0]['symbol']
        q=dict(midpoint=1.1,bid=1,ask=1.2,bid_size=100,ask_size=100,
               executable_reference=True,state='live',
               quote_time=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        market=Mock();market.quotes.return_value={'rows':[dict(symbol=symbol,quote=q)]}
        self.assertTrue(review_quotes(market,t,'alpaca')['requires_ack'])

    def test_invalid_time_cannot_reuse_cached_age(self):
        from unittest.mock import Mock
        t=normalize(ticket());symbol=t['legs'][0]['symbol']
        for stamp in ('invalid',None,'2026-11-05T12:00:00'):
            q=dict(midpoint=1.1,bid=1,ask=1.2,bid_size=100,ask_size=100,
                   executable_reference=True,state='live',age_seconds=0,quote_time=stamp)
            market=Mock();market.quotes.return_value={'rows':[dict(symbol=symbol,quote=q)]}
            self.assertTrue(review_quotes(market,t,'alpaca')['requires_ack'])
