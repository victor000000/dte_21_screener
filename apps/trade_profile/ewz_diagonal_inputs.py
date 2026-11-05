"""Validate a provider native capture and fit IV to synchronized quote midpoints."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compute import bs


def build(path):
    raw = path.read_bytes()
    capture = json.loads(raw)
    assert bs.USING_QUANTLIB
    specs = {923031156: ("EWZ261030C00046000", "2026-10-30", 46., -7),
             836892026: ("EWZ261120C00050000", "2026-11-20", 50., 21)}
    wanted = set(specs) | {10753244}
    snapshots = {s["contract"]["conId"]: s for s in capture["snapshots"]}
    quotes = {}
    for group in capture["historical_bid_ask"]:
        cid = group["contract"]["conId"]
        if cid not in wanted:
            continue
        valid = [q for q in group["ticks"] if 0 <= q["priceBid"] <= q["priceAsk"]
                 and q["priceAsk"] > 0 and q["sizeBid"] > 0 and q["sizeAsk"] > 0]
        assert valid, f"No valid book for {cid}"
        quotes[cid] = max(enumerate(valid), key=lambda pair: (pair[1]["time"], pair[0]))[1]
    assert set(quotes) == wanted
    times = [dt.datetime.fromisoformat(q["time"]) for q in quotes.values()]
    reference = dt.datetime.fromisoformat(capture["requested_utc"])
    ages = [(reference - t).total_seconds() for t in times]
    assert max(ages) <= 30 and min(ages) >= 0, ages
    skew = (max(times) - min(times)).total_seconds()
    assert skew <= 5
    assert all(snapshots[c]["marketDataType"] == 1 for c in wanted)
    under = quotes[10753244]
    spot = round((under["priceBid"] + under["priceAsk"]) / 2, 3)
    today = reference.date()
    legs = []
    for cid, (symbol, expiry, strike, qty) in specs.items():
        contract = snapshots[cid]["contract"]
        assert contract["strike"] == strike and contract["right"] == "C"
        assert contract["lastTradeDateOrContractMonth"] == expiry.replace("-", "")
        assert float(contract["multiplier"]) == 100
        quote = quotes[cid]
        midpoint = (quote["priceBid"] + quote["priceAsk"]) / 2
        time = (dt.date.fromisoformat(expiry) - today).days / 365
        iv = bs.implied_vol(midpoint, spot, strike, time, .04, True)
        assert iv and abs(bs.bs_price(spot, strike, time, .04, iv, True) - midpoint) < 1e-6
        legs.append(dict(symbol=symbol, expiry=expiry, strike=strike, qty=qty, iv=iv,
                         bid=quote["priceBid"], ask=quote["priceAsk"],
                         bid_size=quote["sizeBid"], ask_size=quote["sizeAsk"],
                         reference_close=snapshots[cid]["close"],
                         quote_asof=quote["time"], source="IBKR type1 + native BID_ASK ticks",
                         iv_asof=f"QuantLib midpoint-fit at {quote['time']}; matched EWZ midpoint; rate4%, q0, date-based expiry"))
    size_ok = all((l["bid_size"] if l["qty"] < 0 else l["ask_size"]) >= abs(l["qty"]) for l in legs)
    assert size_ok
    result = dict(valuation_date=today.isoformat(), spot=spot, rate=.04, legs=legs,
                  spot_asof=under["time"] + "; synchronized native quote midpoint, not last trade",
                  status="Regular-session quote snapshot validated — not a streaming quote",
                  pricing_note="Both option books and EWZ share source timestamp " + under["time"] +
                  ". Valid type1 books cross-checked with native BID_ASK ticks. IVs are independently fitted to these option midpoints and matched EWZ midpoint using QuantLib; vendor Greeks with a different underlying input are retained as source evidence, not mixed into this calculation. Entry controls compare captured natural bid/ask and midpoint cash. Displayed sizes cover the proposed quantities at this snapshot; a complex-order fill is not guaranteed. Earlier Alpaca/Theta entitlement and historical quote gaps remain separately open.",
                  provider_handoff=str(path),
                  validation=dict(raw_sha256=hashlib.sha256(raw).hexdigest(), quote_age_at_reference_seconds=ages,
                                  cross_leg_skew_seconds=skew, reference_time=reference.isoformat(),
                                  displayed_size_sufficient=size_ok, originating_timestamp_precision="seconds"))
    return result


if __name__ == "__main__":
    result = build(Path(sys.argv[1]))
    output = ROOT / "reports/ewz_diagonal_inputs_2026-10-19.json"
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps({"spot":result["spot"], "validation":result["validation"],
                      "legs":[{k:l[k] for k in ("symbol","bid","ask","bid_size","ask_size","iv")} for l in result["legs"]]},indent=2))
