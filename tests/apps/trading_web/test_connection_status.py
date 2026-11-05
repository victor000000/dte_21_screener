import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from apps.trading_web.connection_status import status


class StatusTests(unittest.TestCase):
    def test_market_and_paper_roles_remain_separate(self):
        reader=Mock();reader.status.return_value=dict(connected=True,readonly=True,port=4001)
        executor=Mock();executor.connection_status.return_value=dict(connected=False,expected_account='PRIVATE_ACCOUNT')
        market=SimpleNamespace(brokers={'ibkr':reader},execution=executor,live=SimpleNamespace(last_options=None))
        r=status(market)
        self.assertTrue(r['market_data']['connected'])
        self.assertFalse(r['paper_execution']['connected'])
        self.assertIsNone(r['quote_readiness'])
