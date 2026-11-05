"""Read a pinned provider release; never acquire, copy, or alter canonical stores."""
from datetime import timedelta
import math
from data_providers import runtime
from data_providers.lake import current, configured_connection


def read_inputs(roots, today):
    release = current(runtime.data_home())
    if release is None:
        raise ValueError('No published provider release is available')
    result = {}
    con = configured_connection()
    try:
        release.attach(con, 'universe', 'universe')
        for root in roots:
            rows = con.execute('SELECT date, close, adj_close FROM universe.prices WHERE symbol=? AND date BETWEEN ? AND ? ORDER BY date',
                               [root, today-timedelta(days=3*366), today]).fetchall()
            if len({r[0] for r in rows}) != len(rows):
                raise ValueError(f'{root}: duplicate daily dates in provider release')
            usable = [(d,float(c),float(a)) for d,c,a in rows if c and a and c>0 and a>0]
            if not usable:
                raise ValueError(f'{root}: adjusted daily history is unavailable')
            result[root] = dict(history={d:a for d,c,a in usable}, spot=usable[-1][1],
                                asof=usable[-1][0], source='provider universe.prices adjusted close',
                                release=release.id)
    finally:
        con.close()
    return result


def finite(value, positive=False):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError('Missing numeric risk input') from None
    if not math.isfinite(value) or positive and value <= 0:
        raise ValueError('Invalid numeric risk input')
    return value


LIMITATIONS = [
    'Conditional historical estimate, not IBKR Risk Navigator output or a maximum-loss guarantee.',
    'Correlated historical adjusted-close returns; overlapping windows are not independent. At least 252 common observations and 200 windows per horizon.',
    'Option repricing uses constant implied volatility, zero rates/dividend yield and European Black-Scholes. Volatility spikes, skew changes, early exercise, fees, slippage and margin liquidation are not modeled.',
    'Adjusted returns include corporate-action/dividend effects; they are proxies for future spot-price returns.',
    'Options expiring inside a horizon are unavailable because physical settlement and subsequent stock exposure are not modeled.',
    'Foreign-currency cash balances are not modeled; this is securities risk divided by account NLV, not verified full-account risk.',
    'Bands are advisory and do not automatically prevent order submission.',
    'Working orders are excluded from hypothetical holdings. Partial fills are reflected only when the broker reports actual positions.',
    'Bands are 5% warning and 10% limit of current whole-account net liquidation value. Negative CVaR means all tail scenarios still have gains.',
]

