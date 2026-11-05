from .support import *


class QuoteAcknowledgementTests(unittest.TestCase):
    def test_quality_ack_is_required_and_preserved_in_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            b=FakeBroker();s=Service(Path(temp)/'orders.sqlite',{'alpaca':b})
            r=s.review(ticket());s.previews[r['token']]['quotes']={'requires_ack':True,'rows':[]}
            with self.assertRaises(TicketError):s.submit(r['token'],'TEST_PAPER')
            self.assertEqual(b.count,0)
            result=s.submit(r['token'],'TEST_PAPER',True)
            self.assertTrue(result['receipt']['quote_review']['requires_ack'])

    def test_quote_deterioration_is_checked_again_before_transmission(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            b=FakeBroker();s=Service(Path(temp)/'orders.sqlite',{'alpaca':b})
            r=s.review(ticket());s.market=object()
            s.previews[r['token']]['quotes']={'requires_ack':False,'rows':[],'source':'alpaca','feed':'opra','delayed':False}
            with patch('apps.trading_web.submissions.review_quotes',return_value={'requires_ack':True}):
                with self.assertRaises(TicketError):s.submit(r['token'],'TEST_PAPER')
            self.assertEqual(b.count,0)

    def test_replay_requires_original_confirmed_account(self):
        with tempfile.TemporaryDirectory() as temp:
            b=FakeBroker();s=Service(Path(temp)/'orders.sqlite',{'alpaca':b})
            r=s.review(ticket());first=s.submit(r['token'],'TEST_PAPER')
            with self.assertRaises(TicketError):s.submit(r['token'],'OTHER')
            self.assertEqual(s.submit(r['token'],'TEST_PAPER'),first)
            self.assertEqual(b.count,1)
