"""Build an observed-price leg report from saved provider receipts, without repricing."""
import csv
import datetime as dt
import hashlib
import io
import json
import math
from collections import defaultdict
from pathlib import Path
from data_providers.runtime import data_home, trading_logs_dir

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"


def main():
    us_path = REPORTS / "provider_observed_us_2026-10-21.json"
    cn_path = REPORTS / "provider_observed_cn_2026-10-21.json"
    us, cn = (json.loads(p.read_text()) for p in (us_path, cn_path))
    assert not us.get("error") and not cn.get("error")
    source = (trading_logs_dir() / "2026-10-20-AccountStatement.csv")
    archived = (data_home() / "var/raw/trading_exports/20261020T140426Z-41fe7a10/accountstatement.csv/2026-10-20-AccountStatement.csv")
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(archived.read_bytes()).digest()
    assert hashlib.sha256((trading_logs_dir() / "asdfds").read_bytes()).hexdigest() == cn["holdings"][0]["receipt_sha256"]
    quotes = {(q["underlying"], q["expiry"], q["strike"], q["call_put"]): q for q in us["quotes"]}
    rows = []

    def add(broker, ticker, expiry, strike, cp, qty, mult, entry, mark,
            currency, basis, observed, holdings, depth=None):
        assert qty and mult > 0 and entry > 0
        assert all(math.isfinite(v) for v in (qty, mult, entry, mark)) and mark >= 0
        rows.append(dict(broker=broker, ticker=ticker, expiry=str(expiry), strike=strike,
                         call_put=cp, qty=qty, multiplier=mult, entry=entry, mark=mark,
                         profit_pct=100 * (mark - entry) / entry * (1 if qty > 0 else -1),
                         pnl=qty * mult * (mark - entry), currency=currency,
                         risk="premium at risk" if qty > 0 else ("upside" if cp == "C" else "downside"),
                         price_basis=basis, quote_observation=observed,
                         holdings_asof=holdings, closing_depth_covers_qty=depth))

    def add_us(broker, ticker, expiry, strike, cp, qty, entry, holdings):
        key=(ticker, expiry.strftime("%Y%m%d"), strike, cp)
        q=quotes[key]
        # At this capture all option bid/ask fields were unavailable. The explicit
        # close field is an observation, not an executable quote or a model value.
        assert q["close"] is not None
        add(broker, ticker, expiry, strike, cp, qty, 100, entry, q["close"], "USD",
            "IBKR broker-reported previous close; no bid/ask; source close date not supplied",
            q["ticker_time"] + " (receipt time, not close event time)", holdings)

    for p in us["positions"]:
        assert float(p["multiplier"]) == 100
        add_us("IBKR", p["underlying"], dt.datetime.strptime(p["expiry"], "%Y%m%d").date(),
               p["strike"], p["call_put"], p["qty"], p["avg_cost"] / 100, us["captured_utc"])

    lines=list(csv.reader(io.StringIO(source.read_text(encoding="utf-8-sig"))))
    start=next(i for i,r in enumerate(lines) if r and r[0]=="Symbol" and "Option Code" in r)+1
    schwab_count=0
    for r in lines[start:]:
        if not r or not r[0]:
            break
        symbol, code, expiry, strike, cp, qty, entry = r[:7]
        add_us("Schwab", symbol, dt.datetime.strptime(expiry,"%d %b %y").date(),
               float(strike),cp[0],float(qty),float(entry),"2026-10-20 statement; freshly hash-checked")
        schwab_count+=1
    assert schwab_count==6
    assert any(r["broker"]=="Schwab" and r["expiry"]=="2026-10-30" and r["strike"]==46 and r["qty"]==-18 for r in rows)

    for h in cn["holdings"]:
        n=json.loads(h["raw_json"])
        qty=float(n["总仓"]) * (1 if n["买卖"].strip()=="买" else -1)
        assert qty==h["signed_contracts"]
        implied=float(n["持仓市值"])/(qty*float(n["最新价"]))
        mult=round(implied)
        assert math.isclose(implied,mult,rel_tol=.002)
        fields=cn["payloads"]["P_OP_"+cn["native_ids"][h["canonical_id"]]]
        assert float(fields[7])==h["strike"]
        bid,ask=float(fields[1]),float(fields[3])
        assert 0 < bid <= ask
        mark=ask if qty<0 else bid
        depth=float(fields[4] if qty<0 else fields[0])>=abs(qty)
        add("浙商期货",h["underlying_contract"],dt.datetime.strptime(h["expiry_source"],"%Y%m%d").date(),
            h["strike"],h["call_put"],qty,mult,float(n["开仓均价"]),mark,"CNY",
            "Sina native ask to close short / bid to close long; feed delay mode unverified",
            fields[32]+" Asia/Shanghai",h["source_modified_utc"]+" UTC",depth)

    assert len(rows)==26
    rows.sort(key=lambda r:(r["broker"],r["ticker"],-r["profit_pct"]))
    out=REPORTS/"leg_profit_observed_2026-10-21.csv"
    with out.open("w") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    totals=defaultdict(float)
    for r in rows:
        totals[(r["broker"],r["currency"])]+=r["pnl"]
        print(f"{r['broker']} | {r['ticker']} | {r['expiry']} {r['strike']:g}{r['call_put']} | {r['qty']:+g} | {r['entry']:.4g} → {r['mark']:.4g} | {r['profit_pct']:+.2f}% | {r['pnl']:+,.2f} {r['currency']}" + (" THIN" if r['closing_depth_covers_qty'] is False else ""))
    print("TOTALS",dict(totals))
    print("CN quote times",min(r["quote_observation"] for r in rows if r["currency"]=="CNY"),max(r["quote_observation"] for r in rows if r["currency"]=="CNY"))
    print("WRITTEN",out)

if __name__ == "__main__":
    main()
