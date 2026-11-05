"""Value overnight legs."""


def value_overnight_legs(baseline, now, rate, raw, source_inputs, spots):
    from apps.trade_profile.schwab_24h_reestimate import (UTC, ZoneInfo, bs, defaultdict, dt, math)
    rows, by_ticker = [], defaultdict(lambda: defaultdict(float))
    for r in raw:
        s0 = spots[r["ticker"]]
        src = source_inputs[r["ticker"]]
        spot = src["overnight_price"]
        expiry = dt.datetime.combine(dt.date.fromisoformat(r["expiry"]), dt.time(16), ZoneInfo("America/New_York")).astimezone(UTC)
        t0, t = ((expiry - point).total_seconds() / (365 * 86400) for point in (baseline, now))
        call, strike, units = r["call_put"] == "C", r["strike"], r["qty"] * 100
        iv = bs.implied_vol(r["observed_mark"], s0, strike, t0, rate, call)
        assert iv and math.isfinite(iv) and iv > 0
        original = bs.bs_price(s0, strike, t0, rate, iv, call)
        assert math.isclose(original, r["observed_mark"], abs_tol=1e-5)
        def price(s, vol=iv):
            return bs.bs_price(s, strike, t, rate, vol, call)
        mark = price(spot)
        delta, gamma, theta, vega = bs.bs_greeks(spot, strike, t, rate, iv, call)
        eps = spot * 1e-4
        assert math.isclose((price(spot+eps)-price(spot-eps))/(2*eps), delta, abs_tol=2e-6)
        assert math.isclose((price(spot+eps)-2*mark+price(spot-eps))/eps**2, gamma, rel_tol=1e-4)
        result=dict(**r, baseline_spot=s0, baseline_time=baseline.isoformat(),
                    broker="Schwab",spot=spot, snapshot_update_time=src["snapshot_update_utc"], valuation_time=now.isoformat(),
                    calibrated_iv_pct=iv*100, estimated_mark=mark,
                    estimated_profit_pct=(mark-r["entry"])/r["entry"]*100*(1 if units>0 else -1),
                    estimated_pnl_usd=units*(mark-r["entry"]),
                    change_since_baseline_usd=units*(mark-r["observed_mark"]),
                    delta_notional_usd=units*delta*spot,
                    gamma_pnl_1pct_usd=.5*units*gamma*(.01*spot)**2,
                    theta_usd_day=units*theta,vega_usd_pt=units*vega)
        for shock in (-.05,-.01,.01,.05):
            result[f"spot_shock_{shock:+.0%}_pnl_usd"]=units*(price(spot*(1+shock))-mark)
        for dv in (-.05,.05):
            result[f"iv_shock_{dv*100:+.0f}pt_pnl_usd"]=units*(price(spot,max(iv+dv,.001))-mark)
        for shock in (-.05,.05):
            result[f"spot_{shock:+.0%}_iv_plus5pt_pnl_usd"]=units*(price(spot*(1+shock),iv+.05)-mark)
        rows.append(result)
        for k,v in result.items():
            if k.endswith("_usd") or k in ("theta_usd_day","vega_usd_pt"):
                by_ticker[r["ticker"]][k]+=v
    return by_ticker, rows
