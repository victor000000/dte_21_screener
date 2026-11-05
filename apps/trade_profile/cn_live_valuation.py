"""Validate native books and value exact held CN option legs."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .cn_live_inputs import native_ids, number
from .cn_live_model import model
SH = ZoneInfo("Asia/Shanghai")

def value_leg(p, fields, received, evidence):
    r = dict(p, **evidence)
    r.update(close_pnl_cny=None, premium_pnl_pct=None, quote=None, model=None, warnings=[])
    expiry = datetime.strptime(p['expiry'], '%Y%m%d').date()
    r['dte'] = (expiry - received.astimezone(SH).date()).days
    r['risk_direction'] = ('Premium decay / falling futures' if p['right']=='C' else 'Premium decay / rising futures') if p['qty'] > 0 else ('Rising futures' if p['right']=='C' else 'Falling futures')
    option_id, future_id = native_ids(p)
    r['quote_symbol'], r['future_quote_symbol'] = option_id, future_id
    try:
        f = fields[option_id]
        if float(f[7]) != p['strike']:
            raise ValueError('Quote strike mismatch')
        stamp = datetime.strptime(f[32], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SH)
        age = (received-stamp).total_seconds()
        bid, ask, bid_size, ask_size = [number(f[i]) for i in (1,3,0,4)]
        if any(v is None for v in (bid,ask,bid_size,ask_size)) or not 0 < bid <= ask or min(bid_size,ask_size) <= 0:
            raise ValueError('Missing, zero, crossed or empty two-sided book')
        if age < -5:
            raise ValueError('Future-dated quote')
        close, size = (ask, ask_size) if p['qty'] < 0 else (bid, bid_size)
        r['quote'] = dict(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, close=close,
                          close_side='ask' if p['qty'] < 0 else 'bid', close_size=size,
                          depth_covers_qty=size >= abs(p['qty']), quote_time=stamp.isoformat(),
                          received_at=received.isoformat(), age_seconds=age,
                          status='Dated / stale' if age > 30 else 'Recent vendor timestamp; feed delay unknown')
        if age > 30:
            r['warnings'].append('Quote is older than 30 seconds; not a live valuation')
        if size < abs(p['qty']):
            r['warnings'].append('Displayed closing size does not cover the position')
        if p['entry'] and p['entry'] > 0:
            r['premium_pnl_pct'] = 100*(close-p['entry'])/p['entry']*(1 if p['qty']>0 else -1)
            if r.get('multiplier'):
                r['close_pnl_cny'] = p['qty']*r['multiplier']*(close-p['entry'])
        if not r.get('multiplier'):
            r['warnings'].append('Multiplier unavailable: cash P&L and model omitted')
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        r['warnings'].append('Quote unavailable: '+str(exc))
    try:
        u = fields[future_id]
        stamp = datetime.strptime(u[17]+' '+u[1].zfill(6), '%Y-%m-%d %H%M%S').replace(tzinfo=SH)
        price = number(u[8])
        if not price or price <= 0 or (received-stamp).total_seconds() < -5:
            raise ValueError('Invalid future price/time')
        r['future_quote'] = dict(last=price,quote_time=stamp.isoformat())
        r['distance_to_strike_pct'] = 100*((p['strike']/price-1) if p['right']=='C' else (1-p['strike']/price))
        if r['quote'] and r.get('multiplier'):
            r['model'] = model(r, r['quote'], r['future_quote'], received)
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        r['warnings'].append('Model unavailable: '+str(exc))
    return r


