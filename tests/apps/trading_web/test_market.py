import unittest
from unittest.mock import patch
from apps.trading_web.market import MarketService
from apps.trading_web.tickets import TicketError


class MarketTests(unittest.TestCase):
    def test_multisource_poll_reuses_catalog_but_refreshes_books(self):
        from unittest.mock import Mock
        broker=Mock();symbol='SPY991218P00550000'
        broker.market.return_value={'rows':[{'symbol':symbol,'quote':{'bid':1}}]}
        m=MarketService({'ibkr':broker})
        m.live.quotes=Mock(side_effect=[
            {'rows':[{'symbol':symbol,'quote':{'bid':2}}],'sources':[], 'readiness':{}, 'warning':''},
            {'rows':[{'symbol':symbol,'quote':{'bid':3}}],'sources':[], 'readiness':{}, 'warning':''}])
        q=dict(source='ibkr',symbol='SPY',expiry='2099-12-18',multi='true')
        with patch('apps.trading_web.market.time.monotonic',return_value=0):
            self.assertEqual(m.chain(q)['rows'][0]['quote']['bid'],2)
        with patch('apps.trading_web.market.time.monotonic',return_value=20):
            self.assertEqual(m.chain(q)['rows'][0]['quote']['bid'],3)
        self.assertEqual(broker.market.call_count,1)
        self.assertEqual(m.live.quotes.call_count,2)

    def test_invalid_requests_do_not_reach_provider(self):
        m=MarketService({})
        for q in ({'source':'live','symbol':'SPY'}, {'symbol':'CN:CZCE:MA'}, {'symbol':'../../secret'}):
            with self.assertRaises(TicketError):m.expiries(q)
        with self.assertRaises(TicketError):m.quotes(['bad'])
        with self.assertRaises(TicketError):m.quotes(['SPY991218P00550000']*21)

    def test_identical_poll_reuses_short_cache(self):
        m=MarketService({});symbol='SPY991218P00550000'
        with patch('apps.trading_web.market.us_option_data.snapshots',return_value={'rows':[]}) as p:
            m.quotes([symbol]);m.quotes([symbol]);self.assertEqual(p.call_count,1)


class CatalogFallbackTests(unittest.TestCase):
    def test_ibkr_catalog_failure_uses_alpaca_without_transferring_cursor(self):
        from unittest.mock import Mock, patch
        from apps.trading_web.market import MarketService
        broker=Mock();broker.market.side_effect=ValueError('unavailable')
        service=MarketService({'ibkr':broker})
        query=dict(source='ibkr',symbol='SPY',expiry='2099-12-18',right='P',multi='true')
        with patch('apps.trading_web.market.us_option_data.chain',return_value={'rows':[], 'source':'Alpaca','next_page_token':'private-cursor'}) as fn:
            result=service.chain(query)
            self.assertEqual(result['source'],'Alpaca')
            self.assertIsNone(result['next_page_token'])
            fn.assert_called_once()
        with self.assertRaises(ValueError):
            service.chain(dict(query,cursor='ibkr-cursor'))

    def test_readonly_quote_gateway_does_not_replace_order_broker(self):
        from unittest.mock import Mock
        from apps.trading_web.market import MarketService
        paper=Mock();reader=Mock();brokers={'ibkr':paper}
        service=MarketService(brokers,reader)
        reader.market.return_value={'rows':[]}
        service.quotes(['SPY991218P00550000'],'ibkr')
        self.assertIs(brokers['ibkr'],paper)
        self.assertIs(service.execution,paper)
        reader.market.assert_called_once()
        paper.market.assert_not_called()
