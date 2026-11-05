"""Synthetic secrets never reach the persisted submission or recovery receipt."""
import json
import sqlite3
from contextlib import closing
from .support import *
from apps.trading_web.receipt_privacy import clean_receipt
from apps.trading_web.tickets import BrokerRejected

class ReceiptPrivacyTests(unittest.TestCase):
    def stored(self, service):
        with closing(sqlite3.connect(service.db_path)) as db:
            return db.execute('SELECT receipt FROM submissions').fetchone()[0]

    def test_nested_fields_and_labelled_text(self):
        original={'id':'order-1','account':'TEST_PAPER','rows':[{'APCA-API-KEY-ID':'synthetic-key',
                  'client_secret':'synthetic-secret','username':'private-login','private_key':'private-signing-material','qty':2}], 'request_headers':{'Cookie':'cookie-value'},
                  'message':'password="secret with spaces" api_key=synthetic-key&ok=1 Bearer abc123'}
        cleaned=clean_receipt(original)
        self.assertEqual(cleaned['rows'],[{'qty':2}])
        self.assertEqual(cleaned['id'],'order-1')
        self.assertNotIn('request_headers',cleaned)
        for secret in ('synthetic-key','synthetic-secret','secret with spaces','cookie-value','abc123','private-login','private-signing-material'):
            self.assertNotIn(secret,json.dumps(cleaned))
        self.assertIn('client_secret',original['rows'][0])
        self.assertNotIn('json-secret',clean_receipt(json.dumps({'api_key':'json-secret'})))

    def test_submission_and_recovery_do_not_store_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            b=FakeBroker();s=Service(Path(folder)/'orders.sqlite',{'alpaca':b})
            review=s.review(ticket())
            s.previews[review['token']]['risk']={'access_token':'risk-secret','decision':'test evidence'}
            b.submit=lambda *args: {'id':'order-1','api_key':'broker-secret','status':'new'}
            result=s.submit(review['token'],'TEST_PAPER')
            self.assertNotIn('risk-secret',self.stored(s))
            self.assertNotIn('broker-secret',self.stored(s))
            self.assertEqual(result['receipt']['id'],'order-1')
            with closing(sqlite3.connect(s.db_path)) as db, db:
                db.execute("UPDATE submissions SET state='unknown'")
            b.working=[{'reference':result['reference'],'status':'new','headers':{'Authorization':'recovery-secret'}}]
            s.snapshot('alpaca')
            self.assertNotIn('recovery-secret',self.stored(s))
            self.assertEqual(s.receipts('alpaca')[0]['state'],'submitted')

    def test_rejection_text_is_filtered_before_database_write(self):
        with tempfile.TemporaryDirectory() as folder:
            b=FakeBroker();s=Service(Path(folder)/'orders.sqlite',{'alpaca':b})
            review=s.review(ticket())
            def reject(*args):
                raise BrokerRejected('Rejected request api_secret=synthetic-rejection-secret')
            b.submit=reject
            result=s.submit(review['token'],'TEST_PAPER')
            self.assertEqual(result['state'],'rejected')
            self.assertNotIn('synthetic-rejection-secret',self.stored(s))
