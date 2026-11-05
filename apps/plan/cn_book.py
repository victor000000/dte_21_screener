"""cn_book.py — the China legs: a 快期 snapshot repriced at a LIVE underlying.
Split from build_positions.py (size ratchet), as us_book.py was. WHY THE SPOT IS FETCHED AND
THE MARK IS NOT: the spot used to be a literal nothing refreshed — MA701 sat at 2936 while
MA2701 traded 3268 (+11.3%), so a short 3350C read as 0.26 delta and 14% out of the money when
it was AT the money, on the account that must not lose money. No OPTION quotes reach this box,
so the mark stays the broker's 快期 observation — and THE LIST BELOW IS TRANSCRIBED FROM IT,
which is why it goes stale silently. On 2026-10-12 it held TWO legs against the broker's SIX,
and the methanol put was at 2650 against a real 2900: the same hand-copied-list drift this repo
keeps finding. Re-read `trading_logs/Position Tracker*.csv` before trusting any CN number.
"""
import datetime as dt
import re

from data import clock
from compute.bs import bs_greeks, bs_price, implied_vol, T_years
from apps.plan.cn_legs import CN
from apps.trade_log import cn_ticks
from shared.rates import R_CN

USDCNY = 7.13
_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def sina_code(u):
    """MA701 -> nf_MA2701. CZCE writes YMM, Sina wants YYMM: the decade digit comes from the
    clock, because a hard-coded "2" is right until 2030 and then names the wrong contract."""
    m = _RE.match(u)
    if not m:
        return None
    prod, num = m.group(1).upper(), m.group(2)
    if len(num) == 3:
        num = f"{(clock.today().year // 10) % 10}{num}"
    return f"nf_{prod}{num}"


def session_open(now_utc=None):
    """Day 09:00-11:30 / 13:30-15:00, night 21:00-02:30 CST. A LABEL, not a price, and blind
    to holidays — the returned PRICE is what guards a closed exchange reading "live"."""
    t = ((now_utc or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(hours=8)).time()
    return (dt.time(9, 0) <= t <= dt.time(11, 30) or dt.time(13, 30) <= t <= dt.time(15, 0) or t >= dt.time(21, 0) or t <= dt.time(2, 30))


def live_spot(u, obs_spot):
    """(spot, source, quote_class, is_realtime) — the live underlying, else the observation."""
    code = sina_code(u)
    if not code:
        return obs_spot, "快期", "broker_snapshot", False
    try:
        px = cn_ticks.fetch([code]).get(code)
    except Exception as e:
        print(f"note: {u}: Sina unreachable ({type(e).__name__})")
        px = None
    if not px or px <= 0:
        print(f"note: {u}: no live price for {code} — keeping the 快期 spot {obs_spot}, so this leg's est P&L is as old as that snapshot")
        return obs_spot, "快期", "broker_snapshot", False
    live = session_open()
    return float(px), "Sina", ("live" if live else "last_only"), live


def reprice(leg, live):
    """(spot, src, cls, rt, mark, du, gu, theta, vega) for one leg at its live spot.

    Solve the IV where the mark was OBSERVED, then reprice at today's spot: pairing a stale
    mark with a live spot to solve an IV mixes two moments. If no IV solves, keep the
    snapshot WHOLE rather than pair a price with a spot it was never struck at."""
    _a, _b, u, _t, exp, K, cp, qty, _avg, obs, mark_obs, mult, dlot, glot, th, v = leg
    spot, src, cls, rt = live
    # The snapshot WHOLE, in the units `positions` is in: the per-column factor differs and
    # cn_legs documents each one. It must be one definition — the two paths used to disagree.
    snap = (mark_obs, dlot * mult, glot / spot, th * 272 / 365, v)
    if spot == obs:
        return spot, src, cls, rt, *snap
    T = T_years(dt.date.fromisoformat(exp))
    iv = implied_vol(mark_obs, obs, K, T, R_CN, cp == "C")
    if not iv:
        print(f"WARN: {u} {K:g}{cp}: no IV solves from the 快期 mark {mark_obs:g} at {obs:g} — keeping the whole 快期 snapshot; this leg's est P&L is as old as it")
        return obs, "快期", "broker_snapshot", False, *snap
    d, g, th_u, v_u = bs_greeks(spot, K, T, R_CN, iv, cp == "C")
    return (spot, src, cls, rt, bs_price(spot, K, T, R_CN, iv, cp == "C"),
            qty * d * mult, qty * g * mult, qty * th_u * mult, qty * v_u * mult)


_COLS = "account,broker,underlying,sec_type,expiry,strike,call_put,qty,avg_price,spot,multiplier,mark,delta_units,gamma_units,theta_day,vega_pt,delta_notional_usd,asset_class,sector,industry,subindustry,spot_source,spot_class,spot_is_realtime,mark_obs,mark_source,bid,ask"
SQL = f"INSERT INTO positions ({_COLS}) VALUES ({','.join('?' * 28)})"


def store(con, sector):
    """Write every China leg, repriced at the live underlying. Returns the count written.

    ONE fetch per UNDERLYING, not per leg: a Sina timeout on one leg of a strangle would
    otherwise leave its two halves priced off two different markets."""
    obs = {leg[2]: leg[9] for leg in CN}
    live = {u: live_spot(u, s) for u, s in obs.items()}
    for leg in CN:
        acct, broker, u, typ, exp, K, cp, qty, avg, _obs, mark_obs, mult = leg[:12]
        spot, src, cls, rt, mark, du, gu, thu, vu = reprice(leg, live[u])
        con.execute(SQL, [acct, broker, u, typ, dt.date.fromisoformat(exp), K, cp, qty, avg, spot, mult, mark, du, gu, thu, vu, du * spot / USDCNY,
                          *sector.get(u, ("?", "?", "?", "?")), src, cls, rt, mark_obs, "cn_snapshot", None, None])
    return len(CN)
