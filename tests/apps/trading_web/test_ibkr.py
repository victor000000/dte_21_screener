import unittest
from unittest.mock import Mock
from apps.trading_web.ibkr import IBKR
from apps.trading_web.tickets import TicketError


class IBKRTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_live_or_mixed_account_connection(self):
        for accounts in (['U123'], ['PRIVATE_ACCOUNT', 'U123']):
            client = object.__new__(IBKR)
            client.ib = Mock()
            client.ib.isConnected.return_value = True
            client.ib.managedAccounts.return_value = accounts
            with self.assertRaises(TicketError):
                await client._connect()
            client.ib.disconnect.assert_called_once()

    async def test_accepts_only_exact_paper_account(self):
        client = object.__new__(IBKR)
        client.ib = Mock()
        client.ib.isConnected.return_value = True
        client.ib.managedAccounts.return_value = ['PRIVATE_ACCOUNT']
        await client._connect()
        client.ib.disconnect.assert_not_called()

    async def test_account_currency_is_observed_not_assumed(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        client=object.__new__(IBKR)
        client._connect=AsyncMock()
        client.ib=Mock()
        client.ib.accountSummaryAsync=AsyncMock(return_value=[
            SimpleNamespace(account='PRIVATE_ACCOUNT',tag='NetLiquidation',value='12000',currency='EUR'),
            SimpleNamespace(account='PRIVATE_ACCOUNT',tag='BuyingPower',value='15000',currency='EUR')])
        result=await client._account()
        self.assertEqual(result['currency'],'EUR')
        self.assertEqual(result['equity'],'12000')
