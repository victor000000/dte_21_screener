"""Paper-only Alpaca execution adapter; no canonical data ingestion."""
import json
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from data_providers.runtime import data_home
from .tickets import TicketError, BrokerRejected, alpaca_order

BASE = 'https://paper-api.alpaca.markets/v2'
EXPECTED_ACCOUNT = 'PA3I9RDMA9KU'
TERMINAL = {'filled', 'canceled', 'expired', 'rejected', 'replaced'}


class Alpaca:
    def request(self, method, path, **kwargs):
        config = json.loads((data_home() / 'secrets' / 'alpaca_paper.json').read_text())
        if config.get('environment') != 'paper' or config.get('base_url') != BASE:
            raise TicketError('Alpaca credential configuration must specify the paper endpoint.')
        response = requests.request(method, BASE + path, headers={
            'APCA-API-KEY-ID': config['key_id'], 'APCA-API-SECRET-KEY': config['secret']},
            timeout=(5, 20), allow_redirects=False, **kwargs)
        if response.status_code >= 300:
            try:
                message = response.json().get('message', 'Broker rejected request')
            except ValueError:
                message = 'Broker request failed'
            error = BrokerRejected if method == 'POST' and 400 <= response.status_code < 500 and response.status_code != 408 else TicketError
            raise error(f'Alpaca HTTP {response.status_code}: {message}')
        return response.json() if response.content else {}

    def account(self):
        a = self.request('GET', '/account')
        if a.get('account_number') != EXPECTED_ACCOUNT:
            raise TicketError('Alpaca account does not match the configured paper account.')
        if a.get('status') != 'ACTIVE' or a.get('trading_blocked') or a.get('account_blocked'):
            raise TicketError('Alpaca paper account is not enabled for trading.')
        return dict(id=EXPECTED_ACCOUNT, equity=a.get('equity'), buying_power=a.get('buying_power'),
                    options_level=a.get('options_trading_level'), currency=a.get('currency'), source='Alpaca Paper')

    def positions(self):
        rows = self.request('GET', '/positions')
        return [dict(symbol=p['symbol'], qty=p['qty'], average=p.get('avg_entry_price'), mark=p.get('current_price'),
                     pnl=p.get('unrealized_pl'), asset_class=p.get('asset_class'), source='Alpaca broker mark; quote timestamp unavailable') for p in rows]

    def orders(self):
        rows = self.request('GET', '/orders', params={'status': 'all', 'limit': 100, 'nested': 'true'})
        opened = self.request('GET', '/orders', params={'status': 'open', 'limit': 500, 'nested': 'true'})
        if len(opened) >= 500:
            raise TicketError('Open-order coverage may be truncated; reconcile in Alpaca before trading.')
        merged = {r['id']: r for r in [*rows, *opened]}
        return [self.order_row(r) for r in merged.values()]

    @staticmethod
    def order_row(o):
        legs = o.get('legs') or [o]
        return dict(id=o['id'], reference=o.get('client_order_id'), status=o['status'],
                    active=o['status'] not in TERMINAL, symbols=[l.get('symbol') for l in legs if l.get('symbol')],
                    qty=o.get('qty'), filled=o.get('filled_qty'), price=o.get('limit_price'),
                    updated=o.get('updated_at'), cancellable=o['status'] not in TERMINAL)

    def fills(self):
        rows = self.request('GET', '/account/activities/FILL', params={'page_size': 100, 'direction': 'desc'})
        return [dict(id=r['id'], symbol=r.get('symbol'), qty=r.get('qty'), side=r.get('side'), price=r.get('price'), time=r.get('transaction_time')) for r in rows]

    def prepare(self, ticket):
        account = self.account()
        required = 3 if len(ticket['legs']) > 1 else 2
        if int(account.get('options_level') or 0) < required:
            raise TicketError('Account options permission does not support this ticket.')
        contracts = []
        for leg in ticket['legs']:
            c = self.request('GET', '/options/contracts/' + quote(leg['symbol'], safe=''))
            if not c.get('tradable') or str(c.get('size')) != '100' or c.get('symbol') != leg['symbol']:
                raise TicketError('Only tradable standard 100-share options are supported.')
            contracts.append({k: c.get(k) for k in ('symbol', 'name', 'size', 'expiration_date', 'strike_price')})
        return dict(account=account, contracts=contracts, margin='Broker pre-trade margin preview unavailable.',
                    quote_note='No executable option quote loaded. Enter and verify your own limit in the broker platform.')

    def submit(self, ticket, reference):
        self.account()
        return self.order_row(self.request('POST', '/orders', json=alpaca_order(ticket, reference)))

    def cancel(self, order_id):
        self.account()
        self.request('DELETE', '/orders/' + quote(order_id, safe=''))
        return {'status': 'Cancel requested; refresh for broker confirmation.'}
