import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from apps.trading_web.ibkr_connection import IBKRConnection
from apps.trading_web.tickets import TicketError


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    def configured(self, settings, environ=None):
        with patch.dict('os.environ', environ or {}, clear=True), patch(
                'apps.trading_web.ibkr_connection.PAPER_CONFIG') as config:
            config.read_text.return_value = json.dumps(settings)
            return IBKRConnection()

    def test_defaults_never_include_live_gateway(self):
        connection = self.configured({'account': 'DU1'})
        self.assertEqual(connection.connection_status()['candidate_ports'], [4002, 7497])

    async def test_invalid_or_missing_account_cannot_open_socket(self):
        for settings in ({}, {'account': 'U1', 'port': 4001}, {'account': 'DU1', 'port': True}):
            with self.subTest(settings=settings), patch('apps.trading_web.ibkr_connection.IB') as connect:
                connection = self.configured(settings)
                with self.assertRaises(TicketError):
                    await connection._connect()
                connect.assert_not_called()
                self.assertFalse(connection.connection_status()['configured'])

    async def test_missing_config_cannot_open_socket_even_with_override(self):
        with patch.dict('os.environ', {'TRADING_IB_PORT': '4002'}, clear=True), patch(
                'apps.trading_web.ibkr_connection.PAPER_CONFIG') as config, patch(
                'apps.trading_web.ibkr_connection.IB') as connect:
            config.read_text.side_effect = FileNotFoundError
            connection = IBKRConnection()
            with self.assertRaisesRegex(TicketError, 'Configure'):
                await connection._connect()
            connect.assert_not_called()

    async def test_scans_paper_ports_and_validates_account(self):
        connection = self.configured({'account': 'DU1'})
        connection.ib = Mock()
        connection.ib.isConnected.side_effect = [False, True]
        connection.ib.connectAsync = AsyncMock(side_effect=[ConnectionError(), None])
        connection.ib.managedAccounts.return_value = ['DU1']
        self.assertEqual(await connection._connect(), 'DU1')
        settings = connection.connection_status()
        self.assertTrue(settings['connected'])
        self.assertEqual(settings['port'], 7497)
        self.assertNotIn('DU1', repr(settings))
        self.assertEqual(connection.ib.connectAsync.await_args.kwargs['clientId'], 71)

    async def test_live_account_never_becomes_execution_account(self):
        connection = self.configured({'account': 'DU1', 'port': 4001})
        connection.ib = Mock()
        connection.ib.isConnected.return_value = False
        connection.ib.connectAsync = AsyncMock()
        connection.ib.managedAccounts.return_value = ['U1']
        with self.assertRaisesRegex(TicketError, 'differ'):
            await connection._connect()
        self.assertFalse(connection.connection_status()['connected'])

    def test_port_override_keeps_account_check(self):
        account = self.configured({'account': 'DU1', 'port': 4002}, {'TRADING_IB_PORT': '7497'})
        self.assertEqual(account.connection_status()['candidate_ports'], [7497])
        invalid = self.configured({'account': 'U1', 'port': 4002}, {'TRADING_IB_PORT': '7497'})
        self.assertFalse(invalid.connection_status()['configured'])
