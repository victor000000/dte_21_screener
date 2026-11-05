"""Render a proposed EWZ ratio diagonal using provider-verified quote inputs.

Input JSON contains spot, spot_asof, valuation_date, legs (symbol, expiry,
strike, qty, iv, iv_asof, bid, ask, quote_asof, source), and pricing_note.
Quotes are observations, not executions. This script never records trades.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compute import bs

def render(inputs: Path, output: Path):
    d = json.loads(inputs.read_text())
    assert bs.USING_QUANTLIB, "Native QuantLib required"
    today = dt.date.fromisoformat(d["valuation_date"])
    d["front_days"] = min((dt.date.fromisoformat(l["expiry"]) - today).days for l in d["legs"])
    d["rate"] = d.get("rate", .04)
    assert d["front_days"] > 0
    assert sorted(l["qty"] for l in d["legs"]) == [-7, 21]
    for leg in d["legs"]:
        assert leg["iv"] > 0 and leg["bid"] >= 0 and leg["ask"] >= leg["bid"]
        leg["days"] = (dt.date.fromisoformat(leg["expiry"]) - today).days
    # All dollar values refer to the full 7-short/21-long proposed position.
    d["mid_credit"] = -sum(l["qty"] * 100 * (l["bid"] + l["ask"]) / 2 for l in d["legs"])
    d["natural_credit"] = -sum(l["qty"] * 100 * (l["ask"] if l["qty"] > 0 else l["bid"]) for l in d["legs"])

    def scenario(spot, elapsed):
        value = delta = gamma = 0.
        undefined = False
        for leg in d["legs"]:
            t = max(leg["days"] - elapsed, 0) / 365
            if t:
                price = bs.bs_price(spot, leg["strike"], t, d["rate"], leg["iv"], True)
                de, ga, _, _ = bs.bs_greeks(spot, leg["strike"], t, d["rate"], leg["iv"], True)
            else:
                price = max(spot - leg["strike"], 0)
                de = float(spot > leg["strike"])
                ga = 0.
                undefined |= math.isclose(spot, leg["strike"], abs_tol=1e-8)
            value += 100 * leg["qty"] * price
            delta += 100 * leg["qty"] * de
            gamma += 100 * leg["qty"] * ga
        return [value, None if undefined else delta, None if undefined else gamma]

    grid = sorted(set([round(25 + i * .05, 2) for i in range(901)] + [d["spot"],46-1e-5,46+1e-5]))
    d["curves"] = [[[s, *[None if v is None else round(v, 7) for v in scenario(s, day)]] for s in grid]
                   for day in range(d["front_days"] + 1)]
    for day in (0, d["front_days"]):
        for s in (d["spot"], 44., 48., 55.):
            h=.001
            v,delta,gamma=scenario(s,day)
            up=scenario(s+h,day)[0]
            down=scenario(s-h,day)[0]
            assert math.isclose((up-down)/(2*h),delta,rel_tol=2e-5,abs_tol=.002)
            assert math.isclose((up-2*v+down)/h**2,gamma,rel_tol=1e-4,abs_tol=.003)
    d["engine"] = "Native QuantLib · European Black–Scholes, dividend yield 0"
    output.write_text(HTML.replace("__DATA__",json.dumps(d,separators=(",",":"))),encoding="utf-8")
    print(json.dumps({"html":str(output),"mid_credit":d["mid_credit"],"natural_credit":d["natural_credit"],
                      "current_model_value_delta_gamma":scenario(d["spot"],0),
                      "validation":"Native QuantLib delta and gamma matched finite differences"},indent=2))

HTML = (Path(__file__).parent / "templates/render_ewz_diagonal.html").read_text()

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--inputs",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"reports/ewz_diagonal_pnl_delta_gamma_2026-10-19.html")
    args=parser.parse_args()
    render(args.inputs,args.output)
