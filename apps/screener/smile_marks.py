"""Pair option closes with their session's underlying, then estimate at today's spot."""
from compute import bs
from shared.rates import R_US


def price_legs(con, sym, expiry, spot, bars, today):
    """Return (ladders, unmatched dates); `close` stays observed, `mark` is estimated.

    Solving old premiums at a new spot invents IV and can put the selected strikes
    outside the strategy's delta band. Both spot and time-to-expiry must match the
    observation before that IV is used to estimate today's price and delta.
    """
    days = sorted({day for _, _, day, _ in bars})
    prices = {}
    for query, params in (
        ("SELECT date, close FROM yh.prices WHERE symbol=? AND date=ANY(?)", [sym, days]),
        ("SELECT day, close FROM mh.underlying_daily WHERE symbol=? AND day=ANY(?)", [sym, days]),
    ):
        for day, close in con.execute(query, params).fetchall():
            if close and close > 0:
                prices[day] = close
    latest = {}
    for K, cp, day, close in bars:
        if day not in prices or cp not in ("C", "P"):
            continue
        if (K, cp) not in latest or day > latest[(K, cp)][0]:
            latest[(K, cp)] = (day, close)
    legs = {"C": [], "P": []}
    T = max((expiry - today).days, 1) / 365.0
    for (K, cp), (day, close) in latest.items():
        observed_T = (expiry - day).days / 365.0
        iv = bs.implied_vol(close, prices[day], K, observed_T, R_US, cp == "C")
        if not iv or not 0.03 < iv < 3.0:
            continue
        legs[cp].append({"K": K, "iv": iv,
                         "delta": bs.bs_delta(spot, K, T, R_US, iv, cp == "C"),
                         "close": close, "mark": bs.bs_price(spot, K, T, R_US, iv, cp == "C"),
                         "day": day, "expiry": expiry})
    return legs, sorted(set(days) - prices.keys())
