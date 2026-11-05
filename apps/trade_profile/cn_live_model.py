"""Dated Black76 risk estimates; cash scaling is applied exactly once."""
import math
from datetime import datetime, time
from zoneinfo import ZoneInfo
from compute import bs
SH = ZoneInfo("Asia/Shanghai")

def model(p, q, underlying, now):
    """Black76 at the dated quote time, holding futures and IV fixed in scenarios."""
    if not bs.USING_QUANTLIB:
        raise ValueError('Native QuantLib unavailable')
    stamp = datetime.fromisoformat(q['quote_time'])
    under_time = datetime.fromisoformat(underlying['quote_time'])
    if abs((stamp - under_time).total_seconds()) > 900:
        raise ValueError('Option/future timestamp skew exceeds 15 minutes')
    expiry = datetime.combine(datetime.strptime(p['expiry'], '%Y%m%d').date(), time(15), SH)
    t = (expiry - stamp).total_seconds() / (365 * 86400)
    if t <= 0:
        raise ValueError('Expired at quote timestamp')
    f, k, rate = underlying['last'], p['strike'], .02
    discount = math.exp(-rate*t)
    mid = (q['bid'] + q['ask']) / 2
    call = p['right'] == 'C'
    iv = bs.implied_vol(mid, f*discount, k, t, rate, call)
    if not iv or not math.isfinite(iv) or iv <= 0:
        raise ValueError('Midpoint does not admit valid Black76 IV')

    def price(future, term=t):
        return bs.bs_price(future*math.exp(-rate*term), k, term, rate, iv, call)

    delta, gamma, _, vega = bs.bs_greeks(f*discount, k, t, rate, iv, call)
    delta *= discount
    gamma *= discount**2
    eps = f * .0001
    if not math.isclose(price(f), mid, abs_tol=.001) or not math.isclose(
            (price(f+eps)-price(f-eps))/(2*eps), delta, abs_tol=2e-6):
        raise ValueError('Model price/delta validation failed')
    units = p['qty'] * p['multiplier']
    step = min(1/365, t/2)
    return dict(iv_pct=100*iv, per_contract_delta=delta, position_delta=p['qty']*delta,
                gamma_pnl_1pct_cny=.5*units*gamma*(f*.01)**2,
                vega_cny_per_point=units*vega, theta_cny_per_day=units*(price(f,t-step)-mid)/(step*365),
                up_1pct_cny=units*(price(f*1.01)-mid), down_1pct_cny=units*(price(f*.99)-mid),
                as_of=q['quote_time'], basis='European Black76 / native QuantLib; r=2%; expiry 15:00 Shanghai assumed; calendar ACT/365; fixed IV; no exercise premium',
                timestamp_skew_seconds=abs((stamp-under_time).total_seconds()),
                scenarios=[dict(move_pct=move, pnl_cny=units*(price(f*(1+move/100))-mid),
                    iv_up_10pp_pnl_cny=units*(bs.bs_price(f*(1+move/100)*discount,k,t,rate,iv+.10,call)-mid))
                    for move in (-10,-5,-3,-1,0,1,3,5,10)])


