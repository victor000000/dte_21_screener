import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""profit_targets.py — how far each leg is from its 50% target, and what PRICE gets it there.

Two different targets, because the book is two different structures:

  short legs  -> BUY BACK at 50% of the entry credit      target = 0.5 * entry
  long wings  -> SELL at a 50% GAIN on the debit paid      target = 1.5 * entry

The `what-if` column is the answer to "what if the price moves X%": we solve, holding
time-to-expiry and IV FIXED, for the underlying price at which that leg prints its target.
That is a ceteris-paribus number — it isolates the price effect. Theta reaches the same
target on its own with no move at all, so the table also reports the no-move path.

IV is COMPUTED here (bs.implied_vol), never taken from a vendor field: yfinance's
`impliedVolatility` came back at 6.3% on META 850C today, which is nonsense and is a known
trap in this project.

    uv run python apps/trade_profile/profit_targets.py
"""
import argparse
import datetime as dt
import math
import pathlib
import sys

from ib_async import IB, Stock
import yfinance as yf

from data import clock  # noqa: E402
from compute import bs  # noqa: E402
from data import db
from apps.trade_profile.targets import target_price  # noqa: E402  # noqa: E402
from datasources import ibmarks  # noqa: E402
from datasources import tws  # noqa: E402

ROOT = bootstrap.ROOT
EXPIRY = dt.date(2026, 11, 20)
from shared.rates import R_US as R
TODAY = clock.today()


def spot_from_tws(ib, syms):
    """Live underlying marks — the broker is the tiebreaker when free sources disagree."""
    out = {}
    # qualifyContracts keeps a slot (None) for anything it cannot qualify; a None reaching
    # reqTickers crashes on `.secType`. Drop the Nones and keep the sym<->contract pairing.
    pairs = [(s, c) for s, c in zip(syms, ib.qualifyContracts(
        *[Stock(s, "SMART", "USD") for s in syms])) if c]
    for (s, _), t in zip(pairs, ib.reqTickers(*[c for _, c in pairs]) if pairs else []):
        for f in ("last", "close"):
            v = ibmarks.clean(getattr(t, f, None))   # rejects NaN and IB's -1 sentinel
            if v is not None:
                out[s] = float(v)
                break
    return out


def solve_price(K, T, sigma, call, target, lo=0.05, hi=5.0):
    """Underlying price at which the option is worth `target`, IV and T held fixed.

    bisection on price: BS is monotone in S for both calls and puts, so this is safe.
    Returns None when no price in [lo,hi]*K reaches the target (e.g. the target is below
    the option's intrinsic at every sensible price).
    """
    if sigma is None or T <= 0:
        return None
    a, b = K * lo, K * hi
    fa = bs.bs_price(a, K, T, R, sigma, call) - target
    fb = bs.bs_price(b, K, T, R, sigma, call) - target
    if fa * fb > 0:
        return None
    for _ in range(200):
        m = 0.5 * (a + b)
        if (bs.bs_price(m, K, T, R, sigma, call) - target) * fa > 0:
            a, fa = m, bs.bs_price(m, K, T, R, sigma, call) - target
        else:
            b = m
    return 0.5 * (a + b)


def days_to_target(S, K, T, sigma, call, target, step=0.25):
    """Days of pure time decay until the option prints `target`, price held fixed."""
    t = 0.0
    while t < T:
        if bs.bs_price(S, K, T - t, R, sigma, call) <= target:
            return t * 365.0
        t += step / 365.0
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None, help="limit to one account")
    args = ap.parse_args()

    con = db.connect(log="ro", trades_ro=True)

    ib = IB()
    ib.RequestTimeout = 45
    tws.connect(ib, client_id=94, timeout=25)

    rows = con.execute("""
        SELECT account, underlying, strike, call_put, qty, avg_price, mark, multiplier
        FROM positions
        WHERE strike IS NOT NULL AND expiry = ? AND qty <> 0
        ORDER BY account, underlying, strike
    """, [EXPIRY]).fetchall()

    syms = sorted({r[1] for r in rows})
    spot = spot_from_tws(ib, syms)

    # Yahoo as the independent second mark for the legs (the 4th source overall).
    yh = {}
    for s in syms:
        try:
            ch = yf.Ticker(s).option_chain(EXPIRY.isoformat())
            for cp, df in (("C", ch.calls), ("P", ch.puts)):
                for _, r in df.iterrows():
                    yh[(s, float(r["strike"]), cp)] = {
                        "last": float(r["lastPrice"]) if r["lastPrice"] == r["lastPrice"] else None,
                        "oi": float(r["openInterest"]) if r["openInterest"] == r["openInterest"] else None,
                        "vol": float(r["volume"]) if r["volume"] == r["volume"] else None,
                    }
        except Exception as e:
            print(f"  yahoo {s}: {e}")
    ib.disconnect()

    T = bs.T_years(EXPIRY, TODAY)
    print(f"expiry {EXPIRY} · {T*365:.0f} days · r {R:.1%} · spots "
          + " ".join(f"{k} {v:.2f}" for k, v in sorted(spot.items())) + "\n")

    legs = []
    for acct, sym, K, cp, qty, entry, mark_old, mult in rows:
        if args.account and acct != args.account:
            continue
        S = spot.get(sym)
        y = yh.get((sym, float(K), cp), {})
        marks = {"tws_close": mark_old, "yahoo_last": y.get("last")}
        mark = marks["yahoo_last"] or marks["tws_close"]
        call = cp == "C"
        sigma = bs.implied_vol(mark, S, K, T, R, call) if (mark and S) else None
        short = qty < 0
        target = target_price(entry, qty)
        if short:
            progress = (entry - mark) / entry if mark else None
        else:
            progress = (mark - entry) / entry if mark else None
        Sstar = solve_price(K, T, sigma, call, target) if sigma else None
        days = days_to_target(S, K, T, sigma, call, target) if sigma else None
        legs.append(dict(acct=acct, sym=sym, K=K, cp=cp, qty=qty, entry=entry, mark=mark,
                         marks=marks, sigma=sigma, short=short, target=target,
                         progress=progress, Sstar=Sstar, S=S, days=days,
                         mult=mult or 100, oi=y.get("oi"), vol=y.get("vol")))

    legs.sort(key=lambda d: -(d["progress"] if d["progress"] is not None else -9))

    print(f"{'#':>2s} {'acct':>12s} {'leg':>13s} {'q':>4s} {'entry':>7s} {'mark':>7s} "
          f"{'target':>7s} {'prog':>7s} {'IV':>6s} {'spot':>8s} {'needs':>8s} {'no-move':>8s}")
    for i, d in enumerate(legs, 1):
        leg = f"{d['sym']} {int(d['K'])}{d['cp']}"
        move = (f"{(d['Sstar']-d['S'])/d['S']*100:+.1f}%" if d["Sstar"] else "n/a")
        nm = f"{d['days']:.0f}d" if d["days"] else "n/a"
        prog = f"{d['progress']*100:+.0f}%" if d["progress"] is not None else "n/a"
        iv = f"{d['sigma']*100:.0f}%" if d["sigma"] else "n/a"
        print(f"{i:2d} {d['acct']:>12s} {leg:>13s} {d['qty']:4d} {d['entry']:7.2f} "
              f"{(d['mark'] or float('nan')):7.2f} {d['target']:7.2f} {prog:>7s} {iv:>6s} "
              f"{(d['S'] if d['S'] is not None else float('nan')):8.2f} {move:>8s} {nm:>8s}")

    print("\n=== WHAT-IF: the 5 nearest to 50% ===")
    for d in [x for x in legs if x["short"]][:5]:
        leg = f"{d['sym']} {int(d['K'])}{d['cp']} x{d['qty']}"
        if d["S"] is None:
            # No TWS spot -> no target price and no scenario ladder. Say that; do not
            # format None as a float (that crashed the whole report).
            print(f"\n{leg}  (acct {d['acct']})  !! no live spot from TWS -- what-if skipped")
            continue
        print(f"\n{leg}  (acct {d['acct']})  entry {d['entry']:.2f} -> target {d['target']:.2f} "
              f"| mark {(d['mark'] or float('nan')):.2f}, "
              f"{(d['progress']*100 if d['progress'] is not None else float('nan')):.0f}% captured")
        iv_txt = f"{d['sigma']*100:.0f}%" if d["sigma"] else "n/a (no solvable IV)"
        print(f"   spot {d['S']:.2f}, IV {iv_txt}"
              + (f"  =>  50% at {d['Sstar']:.2f}  ({(d['Sstar']-d['S'])/d['S']*100:+.2f}%)"
                 if d["Sstar"] else "  =>  no price gets there at this IV"))
        if d["Sstar"]:
            print(f"   {'move':>8s} {'price':>9s} {'mark':>8s} {'profit':>9s} {'% of credit':>12s}")
            for pct in (-10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10):
                Sp = d["S"] * (1 + pct / 100)
                mp = bs.bs_price(Sp, d["K"], T, R, d["sigma"], d["cp"] == "C")
                pnl = (d["entry"] - mp) * (-d["qty"]) * d["mult"]
                print(f"   {pct:+7d}% {Sp:9.2f} {mp:8.2f} {pnl:+9.0f} {((d['entry']-mp)/d['entry'])*100:+11.0f}%")

    # ---------------- CN legs ----------------
    # The CZCE daily file carries the EXCHANGE's own delta and 隐含波动率, so the CN leg solve
    # needs no vendor guesswork. Cross-checked in check_and_save_marks.py: our bs.implied_vol
    # agrees with the exchange to within ~7%, which is what licenses using these numbers.
    print("\n=== CN legs (CZCE exchange IV/delta, MA2701 spot from Sina) ===")
    try:
        import akshare as ak
        import urllib.request
        req = urllib.request.Request("https://hq.sinajs.cn/list=nf_MA2701",
                                     headers={"Referer": "https://finance.sina.com.cn"})
        ma_spot = float(urllib.request.urlopen(req, timeout=15).read().decode("gbk")
                        .split('"')[1].split(",")[8])
        cz = ak.option_hist_czce(symbol="甲醇期权", trade_date="20260930")
        cz["合约代码"] = cz["合约代码"].astype(str)
        Tcn = bs.T_years(dt.date(2026, 12, 11), TODAY)
        cn = []
        # qty carried explicitly: the target rule branches on its SIGN and this loop
        # had none, so the short-only `0.5 * entry` was the only thing making it work.
        # Both MA legs are short 31 contracts. This was the sixth copy of the rule --
        # the consolidation converted the analogous loop in hit_probability but missed
        # this one, so a long CN leg would have got a "50% target" below its debit.
        for code, K, cp, entry, qty in (("MA701P2650", 2650.0, "P", 81.98, -31),
                                        ("MA701C3350", 3350.0, "C", 70.31, -31)):
            r = cz[cz["合约代码"] == code]
            if not len(r):
                print(f"   {code}: not in CZCE file")
                continue
            r = r.iloc[0]
            settle = float(r["今结算"])
            # Use OUR OWN IV, not the exchange's. The exchange's 隐含波动率 does not
            # reproduce its own settlement price in our pricer (38.92% implied -> ~17% below
            # the actual 81.50 settle), so feeding it back would put the whole curve in the
            # wrong place and the "+0% move" row would show a profit we do not have.
            # bs.implied_vol is anchored to the real price by construction.
            sigma = bs.implied_vol(settle, ma_spot, K, Tcn, R, cp == "C")
            exch_sigma = float(r["隐含波动率"]) / 100.0
            target = target_price(entry, qty)
            Star = solve_price(K, Tcn, sigma, cp == "C", target)
            cn.append((code, K, cp, entry, settle, sigma, target, Star))
            print(f"   {code}  entry {entry:7.2f}  settle {settle:7.2f}  target {target:7.2f}  "
                  f"captured {(entry-settle)/entry*100:+5.1f}%  our IV {sigma*100:.1f}% "
                  f"(exch {exch_sigma*100:.1f}%)  spot {ma_spot:.0f}")
            if Star:
                print(f"      => 50% at {Star:8.1f}  ({(Star-ma_spot)/ma_spot*100:+.2f}%)   "
                      f"exch delta {float(r['DELTA']):+.4f}  OI {float(r['持仓量']):.0f}")
        if cn:
            print(f"\n   {'move':>8s} " + " ".join(f"{c[0][-4:]:>10s}" for c in cn))
            for pct in (-10, -7, -5, -3, -2, 0, 2, 3, 5, 7, 10):
                Sp = ma_spot * (1 + pct / 100)
                cells = []
                for code, K, cp, entry, settle, sigma, target, Star in cn:
                    mp = bs.bs_price(Sp, K, Tcn, R, sigma, cp == "C")
                    cells.append(f"{((entry-mp)/entry)*100:+9.0f}%")
                print(f"   {pct:+7d}% " + " ".join(cells))
    except Exception as e:
        print(f"   CN legs unavailable: {type(e).__name__} {e}")

    con.close()


if __name__ == "__main__":
    main()
