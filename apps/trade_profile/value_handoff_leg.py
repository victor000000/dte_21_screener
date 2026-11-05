"""Value handoff leg."""


def value_handoff_leg(args, differences, fx, holding, legs, quotes, raw, symbol, underlyings):
    from apps.trade_profile.cn_held_leg_report import (bs, dt, json, math)
    source = raw[symbol]
    side = source["买卖"].strip()
    assert side in {"买", "卖"}, (symbol, side)
    quantity = float(source["总仓"]) * (1 if side == "买" else -1)
    assert quantity != 0
    if quantity != holding["signed_contracts"]:
        differences.append(dict(symbol=symbol, delivered=holding["signed_contracts"],
                                raw_verified=quantity))
    # Independent multiplier check: broker value = signed qty * mark * multiplier.
    implied = float(source["持仓市值"]) / (quantity * float(source["最新价"]))
    multiplier = round(implied)
    assert multiplier > 0 and math.isclose(implied, multiplier, rel_tol=.002)
    quote = quotes[holding["canonical_id"]]
    under = underlyings[holding["underlying_contract"]]
    bid, ask = float(quote["bid"]), float(quote["ask"])
    future, strike = float(under["last"]), float(holding["strike"])
    assert 0 < bid <= ask and future > 0
    mark = (bid + ask) / 2
    expiry = dt.datetime.strptime(holding["expiry_source"], "%Y%m%d").date()
    time = (expiry - args.date).days / 365
    assert time > 0
    rate = .02
    discount = math.exp(-rate * time)
    call = holding["call_put"] == "C"
    iv = bs.implied_vol(mark, future * discount, strike, time, rate, call)
    assert iv is not None and math.isfinite(iv) and iv > 0

    def price(f):
        return bs.bs_price(f * discount, strike, time, rate, iv, call)

    greeks = bs.bs_greeks(future * discount, strike, time, rate, iv, call)
    delta, gamma = discount * greeks[0], discount**2 * greeks[1]
    eps = future * 1e-4
    assert math.isclose(price(future), mark, abs_tol=.001)
    assert math.isclose((price(future + eps) - price(future - eps)) / (2 * eps),
                        delta, abs_tol=2e-6)
    assert math.isclose((price(future + eps) - 2 * price(future) + price(future - eps)) / eps**2,
                        gamma, rel_tol=1e-4)
    units = quantity * multiplier
    entry = float(source["开仓均价"])
    assert math.isfinite(entry) and entry > 0
    close_quote = ask if quantity < 0 else bid
    close_pnl_cny = units * (close_quote - entry)
    premium_basis_cny = abs(units) * entry
    dd_cny = units * delta * future
    gp_cny = .5 * units * gamma * (.01 * future)**2
    native_under = json.loads(under["raw_json"])
    legs.append(dict(broker="浙商期货", account=source["用户代码"],
                     ticker=holding["product"], future=holding["underlying_contract"],
                     symbol=symbol, qty=quantity, expiry=expiry.isoformat(),
                     future_price=future, option_bid=bid, option_ask=ask, option_mid=mark,
                     entry_premium=entry, close_quote=close_quote,
                     close_quote_side="ask" if quantity < 0 else "bid",
                     entry_premium_basis_cny=premium_basis_cny,
                     estimated_close_pnl_cny=close_pnl_cny,
                     premium_pnl_pct=100 * close_pnl_cny / premium_basis_cny,
                     distance_to_strike_pct=100 * ((strike / future - 1) if call else (1 - strike / future)),
                     multiplier=multiplier, multiplier_basis="implied and rounded from raw broker position value / signed quantity / export mark",
                     expiry_basis=holding["expiry_basis"], iv=iv, rate=rate,
                     model_delta=delta, model_gamma=gamma,
                     dollar_delta_cny=dd_cny, dollar_delta_usd=dd_cny / fx,
                     gamma_pnl_1pct_cny=gp_cny, gamma_pnl_1pct_usd=gp_cny / fx,
                     repriced_up_1pct_usd=units * (price(future * 1.01) - price(future)) / fx,
                     repriced_down_1pct_usd=units * (price(future * .99) - price(future)) / fx,
                     holdings_file_modified_utc=holding["source_modified_utc"],
                     option_received_utc=quote["received_utc"],
                     option_event_utc=quote["source_quote_utc"],
                     underlying_vendor_date=native_under[17],
                     underlying_vendor_clock=native_under[1],
                     underlying_source_quote_utc=under.get("source_quote_utc"),
                     underlying_received_utc=under["received_utc"]))
