from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from apps.trading_web.ibkr import IBKR
from apps.trading_web.ibkr_connection import IBKRConnection
from apps.trading_web.tickets import TicketError


def paper_client():
    client = object.__new__(IBKR)
    with patch('apps.trading_web.ibkr_connection._paper_settings', return_value=('DU1', (4002,))):
        IBKRConnection.__init__(client)
    client.ib = Mock()
    client.ib.isConnected.return_value = True
    return client


class IBKRTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_live_other_paper_or_mixed_account_connection(self):
        for accounts in ([], ['U1'], ['DU2'], ['DU1', 'U1']):
            with self.subTest(accounts=accounts):
                client = paper_client()
                client.ib.managedAccounts.return_value = accounts
                with self.assertRaises(TicketError):
                    await client._connect()
                client.ib.disconnect.assert_called_once()

    async def test_accepts_only_exact_paper_account(self):
        client = paper_client()
        client.ib.managedAccounts.return_value = ['DU1']
        self.assertEqual(await client._connect(), 'DU1')
        client.ib.disconnect.assert_not_called()

    async def test_account_currency_is_observed_not_assumed(self):
        client = paper_client()
        client.ib.managedAccounts.return_value = ['DU1']
        client.ib.accountSummaryAsync = AsyncMock(return_value=[
            SimpleNamespace(account='DU1', tag='NetLiquidation', value='12000', currency='EUR'),
            SimpleNamespace(account='DU1', tag='BuyingPower', value='15000', currency='EUR'),
            SimpleNamespace(account='DU2', tag='NetLiquidation', value='20000', currency='USD'),
        ])
        result = await client._account()
        client.ib.accountSummaryAsync.assert_awaited_once_with('DU1')
        self.assertEqual(result['id'], 'DU1')
        self.assertEqual(result['currency'], 'EUR')
        self.assertEqual(result['equity'], '12000')
