import unittest
from unittest.mock import Mock
from apps.trading_web.market_routes import route
from apps.trading_web.tickets import TicketError


class RouteTests(unittest.TestCase):
    def test_only_named_endpoints(self):
        m=Mock()
        route(m,'/api/cn/positions',{})
        m.cn.assert_called_once_with('positions',{})
        with self.assertRaises(TicketError):route(m,'/api/market/trade',{})
