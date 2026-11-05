from .support import *

class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.broker = FakeBroker()
        self.service = Service(Path(self.directory.name) / 'receipts.sqlite', {'alpaca': self.broker})

    def test_reject_invalid_and_duplicate_legs(self):
        for change in ({'limit': 'NaN'}, {'limit': '-1'}, {'broker': 'live'}, {'effect': 'credit'}):
            raw = ticket(); raw.update(change)
            with self.assertRaises(TicketError):
                normalize(raw)
        raw = ticket(); raw['legs'].append(raw['legs'][0].copy())
        with self.assertRaises(TicketError):
            normalize(raw)

    def test_close_requires_current_correct_side_and_quantity(self):
        t = normalize(ticket('buy_to_close'))
        for held in ([], [{'symbol': t['legs'][0]['symbol'], 'qty': 2}], [{'symbol': t['legs'][0]['symbol'], 'qty': -1}]):
            with self.assertRaises(TicketError):
                check_holdings(t, held, [])
        check_holdings(t, [{'symbol': t['legs'][0]['symbol'], 'qty': -2}], [])

    def test_combo_credit_sign_and_ratios(self):
        raw = ticket(); raw['effect'] = 'credit'
        raw['legs'][0]['intent'] = 'sell_to_open'
        second = raw['legs'][0].copy(); second.update(strike='545', intent='buy_to_open', qty=4)
        raw['legs'].append(second)
        t = normalize(raw); payload = alpaca_order(t, 'test')
        self.assertEqual(t['units'], 2)
        self.assertEqual(t['cash'], '250.00')
        self.assertEqual(payload['limit_price'], '-1.25')
        self.assertEqual([l['ratio_qty'] for l in payload['legs']], ['1', '2'])
        self.assertNotIn('side', payload)

    def test_working_order_conflict(self):
        t = normalize(ticket())
        with self.assertRaises(TicketError):
            check_holdings(t, [], [{'active': True, 'symbols': [t['legs'][0]['symbol']]}])


    def test_malformed_legs_are_validation_errors(self):
        for value in (None,3,'option',[],True):
            raw=ticket();raw['legs']=[value]
            with self.assertRaises(TicketError):normalize(raw)
        with self.assertRaises(TicketError):normalize([])
