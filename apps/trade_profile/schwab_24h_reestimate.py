"""Reprice verified Schwab holdings from saved Futu overnight and dated IBKR bars."""
import csv
import datetime as dt
import io
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from compute import bs
from data_providers.runtime import trading_logs_dir

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
UTC = dt.timezone.utc


def main():
    assert bs.USING_QUANTLIB
    statement = (trading_logs_dir() / "2026-10-20-PositionStatement.csv")
    text = statement.read_text(encoding="utf-8-sig")
    futu = json.loads((REPORTS / "schwab_futu_24h_2026-10-21.json").read_text())
    inputs = {r["code"].split(".")[-1]: r for r in futu["results"]["snapshot"]["data"]}
    histories = json.loads((REPORTS / "schwab_underlying_24h_sources_2026-10-21.json").read_text())["histories"]
    option_histories = json.loads((REPORTS / "schwab_option_baselines_2026-10-21.json").read_text())["histories"]
    baseline = dt.datetime(2026, 10, 20, 20, tzinfo=UTC)
    # Saved-snapshot valuation clock; this is not a newly acquired 10:30 quote.
    now = max(dt.datetime.fromisoformat(r["update_time"]).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC) for r in inputs.values())
    source_inputs = {}
    for symbol, src in inputs.items():
        event = dt.datetime.fromisoformat(src["update_time"]).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        target = event - dt.timedelta(days=1)
        history = next(h for h in histories if h["symbol"] == symbol and h["exchange"] == "OVERNIGHT")
        bars = [b for b in history["bars"] if b["volume"] > 0 and dt.datetime.fromisoformat(b["time"]) + dt.timedelta(minutes=1) <= target]
        ref = max(bars, key=lambda b: b["time"])
        source_inputs[symbol] = dict(overnight_price=src["overnight_price"],regular_last_price=src["last_price"],snapshot_update_utc=event.isoformat(),field_event_time_verified=False,reference=ref,target_24h_prior_utc=target.isoformat(),approx_24h_return_pct=(src["overnight_price"]/ref["close"]-1)*100,reference_bar_end_gap_seconds=(target-dt.datetime.fromisoformat(ref["time"])-dt.timedelta(minutes=1)).total_seconds(),change_from_regular_close_pct=(src["overnight_price"]/src["last_price"]-1)*100)
    rate = .04
    ticker = None
    spots, raw = {}, []
    for r in csv.reader(io.StringIO(text)):
        if not r:
            continue
        if r[0] in ("CRWD", "EWZ"):
            ticker = r[0]
        elif r[0] in ("CROWDSTRIKE HLDGS IN Class A", "iShares MSCI Brazil ETF"):
            spots[ticker] = float(r[5])
        m = re.match(r"100 (?:\(Weeklys\) )?(\d+ [A-Z]+ \d+) (\d+) (PUT|CALL)$", r[0])
        if not m or not float(r[1]):
            continue
        expiry = dt.datetime.strptime(m[1], "%d %b %y").date()
        raw.append(dict(ticker=ticker, expiry=str(expiry), strike=float(m[2]), call_put=m[3][0],
                        qty=float(r[1]), entry=float(r[4]), observed_mark=float(r[5]),
                        statement_iv_pct=float(r[3].rstrip("%"))))
    assert len(raw) == 6
    for symbol in inputs:
        h = next(h for h in histories if h["symbol"] == symbol and h["exchange"] == "SMART")
        spots[symbol] = next(b["close"] for b in h["bars"] if dt.datetime.fromisoformat(b["time"]) == baseline-dt.timedelta(minutes=1))
    for r in raw:
        h = next(h for h in option_histories if (h["symbol"],h["expiry"],h["strike"],h["call_put"]) == (r["ticker"],r["expiry"].replace("-",""),r["strike"],r["call_put"]))
        r["statement_mark"] = r["observed_mark"]
        r["observed_mark"] = next(b["close"] for b in h["bars"] if dt.datetime.fromisoformat(b["time"]) == baseline-dt.timedelta(minutes=1))
    from apps.trade_profile.value_overnight_legs import value_overnight_legs
    by_ticker, rows = value_overnight_legs(baseline, now, rate, raw, source_inputs, spots)
    rows.sort(key=lambda r:(r["ticker"],-r["estimated_profit_pct"]))
    totals={k:sum(g[k] for g in by_ticker.values()) for k in next(iter(by_ticker.values()))}
    def leg(ticker,expiry,strike,cp):
        return next(r for r in rows if (r["ticker"],r["expiry"],r["strike"],r["call_put"])==(ticker,expiry,strike,cp))
    costs={"close_18_ewz_oct30_46c":18*100*leg("EWZ","2026-10-30",46,"C")["estimated_mark"],
           "close_25_ewz_nov20_43_50_call_spreads":25*100*(leg("EWZ","2026-11-20",43,"C")["estimated_mark"]-leg("EWZ","2026-11-20",50,"C")["estimated_mark"]),
           "close_25_ewz_nov20_37p":25*100*leg("EWZ","2026-11-20",37,"P")["estimated_mark"],
           "close_one_crwd_strangle":100*(leg("CRWD","2026-11-20",225,"P")["estimated_mark"]+leg("CRWD","2026-11-20",260,"C")["estimated_mark"])}
    after=[]
    for r in rows:
        newqty=r["qty"]
        if r["ticker"]=="EWZ":
            newqty={46:0,37:-25,43:-25,50:29}[r["strike"]]
        scale=newqty/r["qty"]
        after.append({k:v*scale for k,v in r.items() if k.endswith("_usd") and isinstance(v,(int,float))})
    after_totals={k:sum(r[k] for r in after) for k in after[0]}
    output=dict(status="corrected saved-snapshot morning estimate",generated_utc=dt.datetime.now(UTC).isoformat(),valuation_time=now.isoformat(),rate_assumption=rate,model="Native QuantLib European Black-Scholes, q=0; actual seconds/365; expiration16:00 New York",holdings_source=str(statement),baseline_time=baseline.isoformat(),underlying_inputs=source_inputs,legs=rows,by_ticker=dict(by_ticker),total=totals,estimated_close_debits=costs,after_candidates_1_to_3=after_totals,limitations=["Futu overnight_price from saved09:51CRWD/09:21EWZ snapshots, not fresh10:30quotes; field-specific event times not verified.","Approximate24h returns use completed positive-volume prior bars and snapshot update clocks; EWZ prior reference is sparse.","IV calibrated from October20 19:59UTC option MIDPOINT and underlying TRADES bars, minute-aligned rather than simultaneous ticks.","Fixed IV base case, r4%, q0; American exercise, discrete dividends, transaction fees and slippage are not modeled.","Actual Schwab buying power and margin call unavailable beyond October20 export; closing debit is not margin relief.","After-reduction P&L represents remaining holdings only; realized closing P&L is excluded and no account gain is implied."])
    (REPORTS/"schwab_24h_reestimate_2026-10-21.json").write_text(json.dumps(output,ensure_ascii=False,indent=2))
    with (REPORTS/"schwab_24h_reestimate_2026-10-21.csv").open("w") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    for r in rows:
        print(r["ticker"],r["expiry"],r["strike"],r["call_put"],r["qty"],"IV",round(r["calibrated_iv_pct"],2),"MARK",round(r["estimated_mark"],4),"PCT",round(r["estimated_profit_pct"],2),"PNL",round(r["estimated_pnl_usd"],2))
    print("BY TICKER",json.dumps(by_ticker));print("TOTAL",json.dumps(totals));print("COSTS",json.dumps(costs));print("AFTER",json.dumps(after_totals))


if __name__=="__main__":
    main()
