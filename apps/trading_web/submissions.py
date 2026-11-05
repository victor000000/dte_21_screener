"""Durable, idempotent transmission receipts and reviewed quote acknowledgement."""
import hashlib
import json
import sqlite3
from contextlib import closing
import time
from .tickets import TicketError, BrokerRejected
from .quote_review import review_quotes
from .receipt_privacy import clean_receipt


class Submissions:
    def submit(self, token, account, quote_ack=False):
        with self.lock:
            reference = 'poc-' + hashlib.sha256(str(token).encode()).hexdigest()[:28]
            with closing(sqlite3.connect(self.db_path)) as db, db:
                previous = db.execute('SELECT state,receipt FROM submissions WHERE reference=?', (reference,)).fetchone()
            if previous:
                receipt = json.loads(previous[1])
                if account != receipt.get('account'):
                    raise TicketError('Account confirmation does not match the original submission.')
                return dict(reference=reference, state=previous[0], receipt=receipt)
            preview = self.previews.get(token)
            if not preview or time.time() - preview['created'] > 120:
                raise TicketError('Review expired. Review the current ticket again.')
            if account != preview['account']:
                raise TicketError('Account confirmation does not match the reviewed paper account.')
            if (preview.get('quotes') or {}).get('requires_ack') and quote_ack is not True:
                raise TicketError('Acknowledge the displayed quote-quality warning or refresh quotes and review again.')
            ticket = preview['ticket']
            b = self.broker(ticket['broker'])
            self.validate(ticket, b)
            current_quotes = None
            reviewed = preview.get('quotes')
            if self.market and reviewed:
                current_quotes = review_quotes(self.market,ticket,reviewed['source'],reviewed['feed'],reviewed['delayed'])
                if current_quotes['requires_ack'] and not quote_ack:
                    raise TicketError('Quote quality changed or quotes aged. Refresh quotes and review again.')
            fingerprint = hashlib.sha256(json.dumps(ticket, sort_keys=True).encode()).hexdigest()
            with closing(sqlite3.connect(self.db_path)) as db, db:
                uncertain = db.execute("SELECT reference FROM submissions WHERE broker=? AND state IN ('submitting','unknown')", (ticket['broker'],)).fetchone()
                if uncertain:
                    raise TicketError('A previous submission is unresolved. Reconcile its reference with the broker before placing more orders.')
                evidence = clean_receipt(dict(risk_review=preview.get('risk'), ticket=ticket, quote_review=preview.get('quotes'), quote_ack=quote_ack, account=account, submission_quotes=current_quotes))
                db.execute('INSERT INTO submissions VALUES (?,?,?,?,?,?)', (reference, fingerprint, ticket['broker'], 'submitting', json.dumps(evidence), time.time()))
            try:
                receipt = b.submit(ticket, reference)
                receipt.update(evidence)
                state = 'submitted'
            except BrokerRejected as exc:
                state, receipt = 'rejected', {'message': str(exc)}
            except Exception:
                state = 'unknown'
                receipt = {'message': 'Submission outcome unknown. Do not recreate this order. Refresh broker orders and reconcile the client reference.', 'reference': reference}
            with closing(sqlite3.connect(self.db_path)) as db, db:
                receipt = clean_receipt({**evidence, **receipt})
                db.execute('UPDATE submissions SET state=?,receipt=? WHERE reference=?', (state, json.dumps(receipt), reference))
            return dict(reference=reference, state=state, receipt=receipt)

    def receipts(self, name):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            rows = db.execute('SELECT reference,state,receipt,created FROM submissions WHERE broker=? ORDER BY created DESC LIMIT 100', (name,)).fetchall()
        return [dict(reference=r[0], state=r[1], receipt=json.loads(r[2]), created=r[3]) for r in rows]

