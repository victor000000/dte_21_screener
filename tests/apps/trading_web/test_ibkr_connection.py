import unittest
from unittest.mock import AsyncMock, Mock, patch
from apps.trading_web.ibkr_connection import IBKRConnection, ports
from apps.trading_web.tickets import TicketError


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    def test_defaults_never_include_live_gateway(self):
        with patch.dict('os.environ', {}, clear=True), patch('apps.trading_web.ibkr_connection.PAPER_CONFIG') as config:
            config.exists.return_value=False
            self.assertEqual(ports(), [4002,7497])

    async def test_scans_paper_ports_and_validates_account(self):
        c=IBKRConnection();c.ib=Mock();c.ib.isConnected.return_value=False
        c.ib.connectAsync=AsyncMock(side_effect=[ConnectionError(),None])
        c.ib.managedAccounts.return_value=['PRIVATE_ACCOUNT']
        with patch('apps.trading_web.ibkr_connection.ports',return_value=[4002,7497]):
            await c._connect()
        self.assertEqual(c.connection_info['port'],7497)
        self.assertEqual(c.ib.connectAsync.await_args.kwargs['clientId'],71)

    async def test_live_account_never_becomes_execution_account(self):
        c=IBKRConnection();c.ib=Mock();c.ib.isConnected.return_value=False
        c.ib.connectAsync=AsyncMock();c.ib.managedAccounts.return_value=['U123']
        with patch('apps.trading_web.ibkr_connection.ports',return_value=[4001]):
            with self.assertRaises(TicketError):await c._connect()
        self.assertFalse(c.connection_info['connected'])

    def test_saved_port_retains_exact_account_requirement(self):
        with patch.dict('os.environ', {}, clear=True), patch('apps.trading_web.ibkr_connection.PAPER_CONFIG') as config:
            config.exists.return_value=True
            config.read_text.return_value='{"port":4001,"account":"PRIVATE_ACCOUNT"}'
            self.assertEqual(ports(),[4001])
            config.read_text.return_value='{"port":4001,"account":"U123"}'
            with self.assertRaises(TicketError):ports()
