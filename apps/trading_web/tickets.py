"""Broker-independent paper ticket validation and order translation."""
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import reduce
from math import gcd
import re


class TicketError(ValueError):
    pass


class BrokerRejected(TicketError):
    """Broker explicitly rejected an order; distinct from unknown transport outcome."""


def normalize(raw):
    if not isinstance(raw, dict):
        raise TicketError('Expected a ticket object.')
    broker = raw.get('broker')
    if broker not in ('alpaca', 'ibkr'):
        raise TicketError('Choose a paper broker.')
    try:
        limit = Decimal(str(raw.get('limit')))
    except InvalidOperation as exc:
        raise TicketError('Enter a positive limit price.') from exc
    if not limit.is_finite() or limit <= 0 or limit > 10000 or limit.as_tuple().exponent < -2:
        raise TicketError('Limit must be positive, at most 10000, with at most two decimals.')
    effect = raw.get('effect')
    if effect not in ('debit', 'credit'):
        raise TicketError('Choose debit or credit.')
    source = raw.get('legs', [])
    if not isinstance(source, list) or not 1 <= len(source) <= 4:
        raise TicketError('Use one to four option legs.')
    legs = []
    for leg in source:
        if not isinstance(leg, dict):
            raise TicketError('Each option leg must be an object.')
        symbol = str(leg.get('underlying', '')).strip().upper()
        if not re.fullmatch(r'[A-Z]{1,6}', symbol):
            raise TicketError('Use an unadjusted US equity/ETF option root.')
        try:
            expiry = date.fromisoformat(leg.get('expiry', ''))
            strike = Decimal(str(leg.get('strike')))
            qty = int(leg.get('qty'))
            if Decimal(str(leg.get('qty'))) != qty:
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise TicketError('Check expiry, strike and whole-contract quantity.') from exc
        if expiry < date.today() or not strike.is_finite() or strike <= 0 or strike > 99999 or strike * 1000 != int(strike * 1000):
            raise TicketError('Expiry must not be past; strike must be a positive valid option strike.')
        if qty < 1 or qty > 100:
            raise TicketError('POC limit: 1–100 contracts per leg.')
        right, intent = leg.get('right'), leg.get('intent')
        if right not in ('C', 'P') or intent not in ('buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close'):
            raise TicketError('Check call/put and opening/closing action.')
        occ = f'{symbol}{expiry:%y%m%d}{right}{int(strike * 1000):08d}'
        legs.append(dict(underlying=symbol, expiry=expiry.isoformat(), strike=str(strike), right=right,
                         qty=qty, intent=intent, side=intent.split('_')[0], symbol=occ))
    if len({x['symbol'] for x in legs}) != len(legs):
        raise TicketError('Duplicate contract legs are not allowed.')
    if len({x['underlying'] for x in legs}) != 1:
        raise TicketError('All legs must have the same underlying.')
    if len(legs) == 1 and effect != ('debit' if legs[0]['side'] == 'buy' else 'credit'):
        raise TicketError('A single buy is a debit; a single sell is a credit.')
    units = reduce(gcd, (x['qty'] for x in legs))
    for leg in legs:
        leg['ratio'] = leg['qty'] // units
    return dict(broker=broker, legs=legs, limit=str(limit), effect=effect, units=units,
                cash=str(limit * units * 100), time_in_force='day')


def check_holdings(ticket, positions, orders):
    """Closing intent must be backed by current broker holdings, not UI rows."""
    held = {p['symbol']: Decimal(str(p['qty'])) for p in positions}
    for leg in ticket['legs']:
        qty = held.get(leg['symbol'], Decimal(0))
        if leg['intent'] == 'buy_to_close' and (qty >= 0 or abs(qty) < leg['qty']):
            raise TicketError(f"Insufficient short holdings to close {leg['symbol']}.")
        if leg['intent'] == 'sell_to_close' and (qty <= 0 or qty < leg['qty']):
            raise TicketError(f"Insufficient long holdings to close {leg['symbol']}.")
        if leg['intent'] == 'buy_to_open' and qty < 0 or leg['intent'] == 'sell_to_open' and qty > 0:
            raise TicketError('Opening action would offset existing holdings; use closing intent.')
        for order in orders:
            if order.get('active') and leg['symbol'] in order.get('symbols', []):
                raise TicketError('A working order already affects this contract. Resolve it first.')


def alpaca_order(ticket, reference):
    body = dict(type='limit', time_in_force='day', qty=str(ticket['units']), client_order_id=reference)
    if len(ticket['legs']) == 1:
        leg = ticket['legs'][0]
        body.update(symbol=leg['symbol'], side=leg['side'], position_intent=leg['intent'], limit_price=ticket['limit'])
    else:
        body.update(order_class='mleg', limit_price=('-' if ticket['effect'] == 'credit' else '') + ticket['limit'],
                    legs=[dict(symbol=l['symbol'], ratio_qty=str(l['ratio']), side=l['side'], position_intent=l['intent']) for l in ticket['legs']])
    return body
