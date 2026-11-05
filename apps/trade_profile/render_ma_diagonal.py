"""Render the Oct 19 MA diagonal snapshot as an offline P&L/delta explorer.

Run in the native WSL environment. Prices and positions come from the saved
provider-backed risk CSV; no new market-data request is made by this report.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compute import bs

ASOF = dt.date(2026, 10, 19)
OUT = ROOT / "reports/ma_diagonal_pnl_delta_2026-10-19.html"


def main():
    assert bs.USING_QUANTLIB, "This report requires the native QuantLib engine"
    source = ROOT / "reports/position_delta_gamma_2026-10-19.csv"
    with source.open() as stream:
        legs = [row for row in csv.DictReader(stream)
                if row["symbol"] in {"MA612C3400", "MA701C3750"}]
    assert len(legs) == 2
    for leg in legs:
        for key in ("qty", "multiplier", "underlying_price", "option_mark", "iv", "rate", "strike", "fx_per_usd"):
            leg[key] = float(leg[key])
        leg["days"] = (dt.date.fromisoformat(leg["expiry"]) - ASOF).days
    front_days = min(leg["days"] for leg in legs)
    base = sum(leg["qty"] * leg["multiplier"] * leg["option_mark"] / leg["fx_per_usd"] for leg in legs)

    def value_delta(move, elapsed):
        value = delta = 0.0
        for leg in legs:
            future = leg["underlying_price"] * (1 + move)
            time = max(0, leg["days"] - elapsed) / 365
            strike = leg["strike"]
            if time == 0:
                price = max(future - strike, 0)
                # A call's expiry delta is discontinuous at its strike.
                df = 1.0 if future > strike else (0.0 if future < strike else 0.5)
            else:
                discount = math.exp(-leg["rate"] * time)
                spot = future * discount
                price = bs.bs_price(spot, strike, time, leg["rate"], leg["iv"], True)
                df = discount * bs.bs_greeks(spot, strike, time, leg["rate"], leg["iv"], True)[0]
            units = leg["qty"] * leg["multiplier"] / leg["fx_per_usd"]
            value += units * price
            delta += units * df * future
        return value - base, delta

    strikes = [{"symbol": leg["symbol"], "move": (leg["strike"] / leg["underlying_price"] - 1) * 100}
               for leg in sorted(legs, key=lambda row: row["days"])]
    grid = sorted(set([i / 4 for i in range(-80, 201)] +
                      [s["move"] + offset for s in strikes for offset in (-0.00001, 0.00001)]))
    curves = [[[x, *[round(v, 6) for v in value_delta(x / 100, day)]] for x in grid]
              for day in range(front_days + 1)]
    # Check the modeled P&L slope against the displayed dollar delta.
    for day in (0, 12, front_days):
        for move in (0, .1, .3):
            eps = 1e-5
            numeric = (value_delta(move + eps, day)[0] - value_delta(move - eps, day)[0]) / (2 * eps)
            analytic = value_delta(move, day)[1] / (1 + move)
            assert math.isclose(numeric, analytic, rel_tol=2e-5, abs_tol=.02), (day, move, numeric, analytic)
    assert abs(value_delta(0, 0)[0]) < .01
    assert math.isclose(value_delta(0, 0)[1], -435.3211462756, abs_tol=.01)
    assert math.isclose(value_delta(.1, front_days)[0], -608.5238081, abs_tol=.02)
    payload = dict(curves=curves, strikes=strikes, legs=legs, base=base,
                   asof=ASOF.isoformat(), days=front_days, engine="Native QuantLib / Black76")
    OUT.write_text(HTML.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"))), encoding="utf-8")
    print(json.dumps({"html": str(OUT), "bytes": OUT.stat().st_size,
                      "engine": payload["engine"], "days": front_days,
                      "delta_today_usd": value_delta(0, 0)[1],
                      "nov11_pnl_at_plus10pct_usd": value_delta(.1, front_days)[0],
                      "validation": "mark, prior scenario and finite-difference delta checks passed"}, indent=2))


HTML = (Path(__file__).parent / "templates/render_ma_diagonal.html").read_text()


if __name__ == "__main__":
    main()
