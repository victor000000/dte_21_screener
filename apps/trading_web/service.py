"""Review tokens and durable submission receipts; no canonical broker stores."""
import json
import secrets
import sqlite3
from contextlib import closing
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from .alpaca import Alpaca
from .ibkr import IBKR
from .market import MarketService
from data_providers.providers.interactive_ibkr import ReadOnlyIBKR
from .quote_review import review_quotes
from .tickets import normalize, check_holdings, TicketError
from .submissions import Submissions
ROOT = Path(__file__).resolve().parents[2]
class Service(Submissions):
    def __init__(self, db_path=None, brokers=None):
        self.brokers = brokers if brokers is not None else {'alpaca': Alpaca(), 'ibkr': IBKR()}
        self.market = MarketService(self.brokers, ReadOnlyIBKR()) if brokers is None else None
        self.lock = threading.RLock()
        self.previews = {}
        self.db_path = db_path or ROOT / '.local' / 'trading-web' / 'orders.sqlite'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS submissions (reference TEXT PRIMARY KEY, fingerprint TEXT, broker TEXT, state TEXT, receipt TEXT, created REAL)')
        self.db_path.chmod(0o600)
    def broker(self, name):
        if name not in self.brokers:
            raise TicketError('Unknown paper broker.')
        return self.brokers[name]
    def snapshot(self, name):
        b = self.broker(name)
        with self.lock:
            account = b.account()
            positions, orders, fills = b.positions(), b.orders(), b.fills()
            # Recover acknowledgements after a lost HTTP response or server restart.
            with closing(sqlite3.connect(self.db_path)) as db, db:
                for order in orders:
                    if order.get('reference'):
                        old = db.execute("SELECT receipt FROM submissions WHERE reference=? AND broker=? AND state IN ('unknown','submitting')",
                                         (order['reference'], name)).fetchone()
                        if old:
                            merged = {**json.loads(old[0]), **order}
                            db.execute("UPDATE submissions SET state='submitted',receipt=? WHERE reference=? AND broker=?",
                                       (json.dumps(merged), order['reference'], name))
        return dict(account=account, positions=positions, orders=orders, fills=fills,
                    received_at=datetime.now(timezone.utc).isoformat(), mode='paper',
                    coverage='Orders/fills are broker-session or latest-100 records, not a complete historical trade log.')
    def validate(self, ticket, b):
        b.account()
        positions, orders = b.positions(), b.orders()
        check_holdings(ticket, positions, orders)
        if any(o.get('active') and o.get('combo') and o.get('underlying') == ticket['legs'][0]['underlying'] for o in orders):
            raise TicketError('An IBKR combination order affects this underlying; resolve it before submitting.')

    def review(self, raw):
        ticket = normalize(raw)
        with self.lock:
            b = self.broker(ticket['broker'])
            self.validate(ticket, b)
            evidence = b.prepare(ticket)
            if self.market:
                evidence['quotes'] = review_quotes(self.market,ticket,raw.get('quote_source',ticket['broker']),raw.get('quote_feed','auto'),raw.get('quote_delayed') is True)
            if ticket['broker'] == 'ibkr':
                from .portfolio_risk import report
                evidence['risk'] = report(self, dict(broker='ibkr', ticket=raw))
            token = secrets.token_urlsafe(24)
            self.previews = {k: v for k, v in self.previews.items() if time.time() - v['created'] < 120}
            self.previews[token] = dict(ticket=ticket, created=time.time(), account=evidence['account']['id'], quotes=evidence.get('quotes'), risk=evidence.get('risk'))
        return dict(token=token, expires_seconds=120, ticket=ticket, **evidence)

    def cancel(self, name, order_id):
        with self.lock:
            return self.broker(name).cancel(str(order_id))
