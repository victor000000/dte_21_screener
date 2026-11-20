import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from apps.trading_web.alpaca import Alpaca, BASE
from apps.trading_web.tickets import TicketError


class AlpacaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.provider_home = Path(directory.name)
        (self.provider_home / 'secrets').mkdir()
        self.client = self.configure()

    def configure(self, **overrides):
        settings = dict(environment='paper', base_url=BASE, account_number='SYNTHETIC_PAPER',
                        key_id='synthetic-key', secret='synthetic-secret')
        settings.update(overrides)
        path = self.provider_home / 'secrets' / 'alpaca_paper.json'
        path.write_text(json.dumps(settings), encoding='utf-8')
        with patch('apps.trading_web.alpaca.data_home', return_value=self.provider_home):
            return Alpaca()

    def test_exact_account_is_checked_on_fixed_paper_url(self):
        response = Mock(status_code=200, content=b'{}')
        response.json.return_value = {'account_number': 'SYNTHETIC_PAPER', 'status': 'ACTIVE'}
        with patch('apps.trading_web.alpaca.requests.request', return_value=response) as request:
            self.assertEqual(self.client.account()['id'], 'SYNTHETIC_PAPER')
        self.assertEqual(request.call_args.args, ('GET', 'https://paper-api.alpaca.markets/v2/account'))
        self.assertFalse(request.call_args.kwargs['allow_redirects'])

    def test_missing_binding_or_misconfigured_endpoint_never_contacts_broker(self):
        with patch('apps.trading_web.alpaca.data_home', return_value=self.provider_home / 'absent'):
            missing_file = Alpaca()
        for client in (missing_file, self.configure(account_number=None), self.configure(account_number='  '),
                       self.configure(base_url='https://example.invalid/v2'), self.configure(environment='live')):
            with self.subTest(client=client), patch('apps.trading_web.alpaca.requests.request') as request:
                with self.assertRaises(TicketError):
                    client.account()
                request.assert_not_called()

    def test_mismatched_identity_blocks_orders_and_cancellations(self):
        for operation, args in (('submit', ({}, 'test-reference')), ('cancel', ('test-order',))):
            with self.subTest(operation=operation), patch.object(
                    self.client, 'request', return_value={'account_number': 'OTHER', 'status': 'ACTIVE'}) as request:
                with self.assertRaisesRegex(TicketError, 'does not match'):
                    getattr(self.client, operation)(*args)
                request.assert_called_once_with('GET', '/account')

    def test_rewriting_private_file_does_not_retarget_running_adapter(self):
        replacement = self.configure(account_number='OTHER')
        reply = {'account_number': 'OTHER', 'status': 'ACTIVE'}
        with patch.object(Alpaca, 'request', return_value=reply):
            with self.assertRaisesRegex(TicketError, 'does not match'):
                self.client.account()
            self.assertEqual(replacement.account()['id'], 'OTHER')

    def test_blocked_account_cannot_trade(self):
        reply = {'account_number': 'SYNTHETIC_PAPER', 'status': 'ACTIVE', 'trading_blocked': True}
        with patch.object(self.client, 'request', return_value=reply):
            with self.assertRaisesRegex(TicketError, 'not enabled'):
                self.client.account()

    def test_nested_order_exposes_all_contracts_for_conflict_checks(self):
        result = self.client.order_row({'id': '1', 'status': 'partially_filled', 'legs': [{'symbol': 'ONE'}, {'symbol': 'TWO'}]})
        self.assertEqual(result['symbols'], ['ONE', 'TWO'])
        self.assertTrue(result['active'])

    def test_old_open_order_is_not_hidden_by_recent_history(self):
        history = [{'id': str(i), 'status': 'filled', 'symbol': 'OTHER'} for i in range(100)]
        active = {'id': 'older', 'status': 'new', 'symbol': 'SPY20991218P00550000'}
        with patch.object(self.client, 'request', side_effect=[history, [active]]) as request:
            result = self.client.orders()
        self.assertEqual(request.call_args.kwargs['params']['status'], 'open')
        self.assertEqual(len(result), 101)
        self.assertTrue(next(r for r in result if r['id'] == 'older')['active'])

    def test_incomplete_open_order_coverage_fails_closed(self):
        with patch.object(self.client, 'request', side_effect=[[], [{}] * 500]):
            with self.assertRaisesRegex(TicketError, 'truncated'):
                self.client.orders()
