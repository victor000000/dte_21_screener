import unittest
from unittest.mock import patch
from apps.trading_web.market import MarketService

class CNRiskRefresh(unittest.TestCase):
    def test_route_does_not_add_completion_based_cache(self):
        market=MarketService({})
        with patch('apps.trade_profile.cn_leg_live.report',side_effect=[{'generation':1},{'generation':2}]) as report:
            first=market.cn('leg-risk',{'refresh':'true'})
            second=market.cn('leg-risk',{'refresh':'true'})
        self.assertNotEqual(first,second)
        self.assertEqual(report.call_count,2)
        report.assert_called_with(update=True)
