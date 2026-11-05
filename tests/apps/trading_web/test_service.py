from .support import *

class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.broker = FakeBroker()
        self.service = Service(Path(self.directory.name) / 'receipts.sqlite', {'alpaca': self.broker})

    def test_repeated_submit_transmits_only_once_even_after_restart(self):
        review = self.service.review(ticket())
        first = self.service.submit(review['token'], 'TEST_PAPER')
        second = Service(self.service.db_path, {'alpaca': self.broker}).submit(review['token'], 'TEST_PAPER')
        self.assertEqual(first, second)
        self.assertEqual(self.broker.count, 1)

    def test_submit_revalidates_holdings(self):
        raw = ticket('buy_to_close'); t = normalize(raw)
        self.broker.held = [{'symbol': t['legs'][0]['symbol'], 'qty': -2}]
        review = self.service.review(raw)
        self.broker.held = []
        with self.assertRaises(TicketError):
            self.service.submit(review['token'], 'TEST_PAPER')
        self.assertEqual(self.broker.count, 0)

    def test_account_mismatch_and_expiry(self):
        review = self.service.review(ticket())
        with self.assertRaises(TicketError):
            self.service.submit(review['token'], 'OTHER')
        self.service.previews[review['token']]['created'] = 0
        with self.assertRaises(TicketError):
            self.service.submit(review['token'], 'TEST_PAPER')

    def test_unknown_blocks_new_order_until_broker_reconciliation(self):
        self.broker.fail = True
        review = self.service.review(ticket())
        result = self.service.submit(review['token'], 'TEST_PAPER')
        self.assertEqual(result['state'], 'unknown')
        second = self.service.review(ticket())
        with self.assertRaises(TicketError):
            self.service.submit(second['token'], 'TEST_PAPER')
        self.assertEqual(self.broker.count, 1)
        self.broker.working = [{'reference': result['reference'], 'status': 'rejected'}]
        self.service.snapshot('alpaca')
        self.assertEqual(self.service.receipts('alpaca')[0]['state'], 'submitted')


    def test_explicit_broker_rejection_is_not_an_unknown_transmission(self):
        from unittest.mock import patch
        from apps.trading_web.tickets import BrokerRejected
        review = self.service.review(ticket())
        with patch.object(self.broker, 'submit', side_effect=BrokerRejected('Order not permitted')):
            result = self.service.submit(review['token'], 'TEST_PAPER')
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['receipt']['message'], 'Order not permitted')
        new_review = self.service.review(ticket())
        self.assertEqual(self.service.submit(new_review['token'], 'TEST_PAPER')['state'], 'submitted')
