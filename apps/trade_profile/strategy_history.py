"""Aligned price and IV histories for the dated strategy study."""
import math
import statistics as st

def load(con):
    from .strategy_quantification_20261025 import NAMES, H
    def px(s):
        return {r[0]: float(r[1]) for r in con.execute(
            "select cast(ts_utc as date), arg_max(close, ts_utc) from underlying_minutes "
            "where symbol=? group by 1 order by 1", [s]).fetchall()}

    def iv(s):
        return {r[0]: float(r[1]) for r in con.execute(
            "select day, avg(atm_iv) from iv_history where underlying=? "
            "and source='ibkr_tws30d' and atm_iv is not null group by 1", [s]).fetchall()}

    out = {}
    for sym in NAMES:
        price, vol = px(sym), iv(sym)
        days = sorted(set(price) & set(vol))
        close = [price[d] for d in days]
        ivs = [vol[d] for d in days]
        rets = [math.log(close[i + 1] / close[i]) for i in range(len(close) - 1)]
        rows = []
        for i in range(252, len(rets) - H):
            ivwin = ivs[i - 251:i + 1]          # the IV lookback, not the return window
            fwd = st.stdev(rets[i + 1:i + 1 + H]) * math.sqrt(252)
            hi, lo = max(ivwin), min(ivwin)
            rows.append(dict(day=days[i], iv=ivs[i], fwd=fwd,
                             ivr=(ivs[i] - lo) / (hi - lo) if hi > lo else None,
                             pct=sum(1 for x in ivwin if x < ivs[i]) / len(ivwin),
                             rv5=st.stdev(rets[i - 4:i + 1]) * math.sqrt(252),
                             rv20=st.stdev(rets[i - 19:i + 1]) * math.sqrt(252),
                             rv60=st.stdev(rets[i - 59:i + 1]) * math.sqrt(252)))
        out[sym] = rows
    return out
