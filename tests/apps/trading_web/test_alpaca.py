import unittest
from unittest.mock import patch
from apps.trading_web.alpaca import Alpaca, EXPECTED_ACCOUNT, BASE
from apps.trading_web.tickets import TicketError


class AlpacaTests(unittest.TestCase):
    def test_paper_url_and_account_allowlist(self):
        self.assertEqual(BASE, 'https://paper-api.alpaca.markets/v2')
        with patch.object(Alpaca, 'request', return_value={'account_number': 'OTHER', 'status': 'ACTIVE'}):
            with self.assertRaises(TicketError):
                Alpaca().account()

    def test_blocked_account_cannot_trade(self):
        with patch.object(Alpaca, 'request', return_value={'account_number': EXPECTED_ACCOUNT, 'status': 'ACTIVE', 'trading_blocked': True}):
            with self.assertRaises(TicketError):
                Alpaca().account()

    def test_nested_order_exposes_all_contracts_for_conflict_checks(self):
        result = Alpaca.order_row({'id': '1', 'status': 'partially_filled', 'legs': [{'symbol': 'ONE'}, {'symbol': 'TWO'}]})
        self.assertEqual(result['symbols'], ['ONE', 'TWO'])
        self.assertTrue(result['active'])

    def test_old_open_order_is_not_hidden_by_recent_history(self):
        history=[{'id':str(i),'status':'filled','symbol':'OTHER'} for i in range(100)]
        active={'id':'older','status':'new','symbol':'SPY20991218P00550000'}
        with patch.object(Alpaca,'request',side_effect=[history,[active]]) as request:
            result=Alpaca().orders()
        self.assertEqual(request.call_args.kwargs['params']['status'],'open')
        self.assertEqual(len(result),101)
        self.assertTrue(next(r for r in result if r['id']=='older')['active'])

    def test_incomplete_open_order_coverage_fails_closed(self):
        with patch.object(Alpaca,'request',side_effect=[[],[{}]*500]):
            with self.assertRaisesRegex(TicketError,'truncated'):
                Alpaca().orders()
