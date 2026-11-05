import unittest
from unittest.mock import Mock
from apps.trading_web.live_market import LiveMarket


class LiveTests(unittest.TestCase):
    def test_unavailable_sources_explicit(self):
        live=LiveMarket({})
        live.options.collect=Mock(return_value={'Futu':dict(status='unavailable',detail='denied')})
        data=live.quotes(['SPY261120P00600000'])
        self.assertIsNone(data['rows'][0]['quote']['bid'])
        self.assertEqual(data['sources'][0]['status'],'unavailable')

    def test_underlying_does_not_invent_account_pnl(self):
        live=LiveMarket({})
        live.spots.collect=Mock(return_value={})
        data=live.underlying('SPY')
        self.assertEqual(data['observations'],[])
        self.assertIsNone(data['account_pnl_24h'])
