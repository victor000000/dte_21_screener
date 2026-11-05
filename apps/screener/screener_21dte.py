import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

# ── --help guard ─────────────────────────────────────────────────────────────
# This script WRITES to a database and takes no arguments, so `script.py --help`
# used to execute it in full. Not hypothetical: a 2026-10-05 sweep ran every app
# with --help and rewrote the fills table (via seed_fills.py) and risk_profile.
# A read-only-looking flag must not be a write. Exits before any connection.
from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below, and a
# docstring must be the first statement, so all 33 copies printed "(no docstring)".

"""screener_21dte.py — 45-DTE repick screener, run when positions hit 21 DTE.

For each candidate in plans/screener_universe.txt (or argv):
  - HV20/60/252 (close-to-close) + Parkinson 20d (yfinance daily)
  - current ATM IV + term slope (front vs ~90d expiry, yfinance chains)
  - IVR: 100 * (latest IV - min IV) / (max IV - min IV), from >=60 daily yf_chain points;
    insufficient or flat IV history is unrankable (no HV-percentile substitution)
  - liquidity: 20d dollar volume; spread% of the candidate strikes
  - strangle candidates on the ~45-DTE monthly: put/call at delta ±0.16–0.22
    (per-strike IV), credit at mid, Reg-T margin estimate
Stores iv_history + screener_runs rows; writes reports/screener_v1_<date>.md (v2 owns reports/screener_<date>.md).
Usage: uv run python apps/screener/screener_21dte.py [SYM ...]
"""
import datetime as dt
import math
import pathlib
import sys

import duckdb
import numpy as np
import pandas as pd
import yfinance as yf

from data import clock  # noqa: E402
from data import db  # noqa: E402
from compute.bs import bs_greeks, T_years
from compute.iv_rank import fetch_series, rank_series

ROOT = bootstrap.ROOT
DB = bootstrap.DATA_ROOT / "trades.duckdb"
from shared.rates import R_US as R

universe_file = bootstrap.DATA_ROOT / "plans" / "screener_universe.txt"
if len(sys.argv) > 1:
    SYMS = [s.upper() for s in sys.argv[1:]]
elif universe_file.exists():
    SYMS = [ln.strip().upper() for ln in universe_file.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
else:
    SYMS = ["SPY", "QQQ", "IWM"]


def hv_series(lr, w):
    s = pd.Series(lr).rolling(w).std(ddof=1) * math.sqrt(252)
    return s.dropna()


def pick_delta(df, spot, T, target_lo, target_hi, call, atm_iv):
    best, best_score = None, 1e9
    for _, r in df.iterrows():
        K = float(r["strike"])
        iv = r.get("impliedVolatility", np.nan)
        if not np.isfinite(iv) or iv < 0.005:
            iv = atm_iv
        d = bs_greeks(spot, K, T, R, iv, call)[0]
        if d is None or not np.isfinite(d):
            continue
        score = abs(abs(d) - 0.19)
        oi = float(r.get("openInterest", 0) or 0)
        if target_lo <= abs(d) <= target_hi:
            score -= 0.05          # prefer in-band
        if oi < 10:
            score += 0.03
        if score < best_score:
            best_score, best = score, (K, abs(d), float(r.get("bid", 0) or 0),
                                       float(r.get("ask", 0) or 0), oi, float(r.get("volume", 0) or 0))
    return best


def iv_rank_for(con, sym, today, current_iv):
    """Rank today's chain IV against its own vendor history, with one point per day."""
    per, excluded = fetch_series(con, symbols=[sym])
    own = [(src, day, iv) for src, day, iv in per.get(sym, [])
           if src == "yf_chain" and day < today]
    if (sym, "yf_chain") in excluded:
        return {"ivr": None, "kind": "yf_chain (per-expiry history excluded)"}
    return rank_series(own + [("yf_chain", today, current_iv)])


def main():
    from datasources.yahoo_session import create_session
    session = create_session()
    # Through db.connect(), so `mh` is market_history and the DDL lands where readers
    # look. This used to be a bare duckdb.connect(trades.duckdb), which made an
    # unqualified `iv_history` the TRADES table -- while every reader of it
    # (screener_21dte_v2, fill_leg_strikes, build_screen_universe) reads
    # `mh.iv_history` in market_history. The IV rows this screen wrote could not
    # influence any screen, including its own successor. db.connect() also pins the
    # session to UTC, which a bare connection does not.
    con = db.connect(history="rw")
    con.execute("CREATE TABLE IF NOT EXISTS mh.iv_history (day DATE, underlying TEXT, expiry DATE, atm_iv DOUBLE, spot DOUBLE, source TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS screener_runs (run_ts TIMESTAMP, underlying TEXT, spot DOUBLE,
    expiry DATE, dte INT, atm_iv DOUBLE, ivr DOUBLE, ivr_kind TEXT, hv20 DOUBLE, hv_rank DOUBLE,
    put_k DOUBLE, put_delta DOUBLE, call_k DOUBLE, call_delta DOUBLE, credit DOUBLE, margin_est DOUBLE,
    dollar_vol_20d DOUBLE, flag TEXT)""")

    rows, out_lines = [], []
    today = clock.today()
    out_lines.append(f"# 21DTE repick screener — {today}\n")
    out_lines.append("| Sym | Spot | Exp | DTE | ATM IV | IVR* | HV20 | HVrank | IV/HV | Kput(Δ) | Kcall(Δ) | Credit | Margin | $Vol20d | Flag |")
    out_lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    for sym in SYMS:
        if sym.startswith("CN:"):
            print(f"{sym}: CN futures require the China data plane; skipping US vendor calls")
            continue
        try:
            t = yf.Ticker(sym, session=session)
            h = t.history(period="2y", interval="1d", auto_adjust=False).dropna(subset=["Close", "High", "Low"])
            if h is None or len(h) < 40:
                print(f"{sym}: no history")
                continue
            closes = h["Close"].values.astype(float)
            spot = float(closes[-1])
            lr = np.diff(np.log(closes))
            hv20s = hv_series(lr, 20)
            hv20 = float(hv20s.iloc[-1]) if len(hv20s) else None
            hv60 = float(hv_series(lr, 60).iloc[-1]) if len(lr) >= 60 else None
            hv_rank = float((hv20s < hv20).mean() * 100) if hv20 else None
            sub = h.tail(20)
            park = float(math.sqrt((np.log(sub["High"] / sub["Low"]) ** 2).mean() / (4 * math.log(2)) * 252))
            dvol = float((h["Close"].tail(20) * h["Volume"].tail(20)).mean())

            exps = list(t.options)
            if not exps:
                print(f"{sym}: no options")
                continue
            exp_dates = sorted(dt.date.fromisoformat(e) for e in exps)
            target = min(exp_dates, key=lambda d: abs((d - today).days - 45))
            dte = (target - today).days
            ch = t.option_chain(target.isoformat())
            T = T_years(target)
            # ATM IV from nearest strike
            calls, puts = ch.calls, ch.puts
            atm_row = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
            atm_iv = float(atm_row["impliedVolatility"].iloc[0])
            if not np.isfinite(atm_iv) or atm_iv < 0.005:
                atm_row = puts.iloc[(puts["strike"] - spot).abs().argsort()[:1]]
                atm_iv = float(atm_row["impliedVolatility"].iloc[0])
            if not np.isfinite(atm_iv) or atm_iv < 0.005:
                near = calls[(calls["strike"] - spot).abs() < 0.1 * spot]
                ivs = [v for v in near["impliedVolatility"] if np.isfinite(v) and v > 0.005]
                atm_iv = float(np.median(ivs)) if ivs else np.nan
            # term slope vs ~90d
            far = [d for d in exp_dates if 70 <= (d - today).days <= 120]
            slope = None
            if far:
                ch2 = t.option_chain(min(far, key=lambda d: abs((d - today).days - 90)).isoformat())
                r2 = ch2.calls.iloc[(ch2.calls["strike"] - spot).abs().argsort()[:1]]
                iv2 = float(r2["impliedVolatility"].iloc[0])
                if np.isfinite(iv2) and iv2 > 0.005:
                    slope = iv2 - atm_iv

            ranked = iv_rank_for(con, sym, today, atm_iv)
            ivr, ivr_kind = ranked["ivr"], ranked["kind"]

            pp = pick_delta(puts, spot, T, 0.16, 0.22, False, atm_iv)
            cc = pick_delta(calls, spot, T, 0.16, 0.22, True, atm_iv)
            credit = margin = None
            if pp and cc:
                pK, pdlt, pbid, pask, poi, _ = pp
                cK, cdlt, cbid, cask, coi, _ = cc
                pm, cm = (pbid + pask) / 2, (cbid + cask) / 2
                credit = pm + cm
                call_req = max(0.2 * spot - max(cK - spot, 0), 0.1 * spot) + cm
                put_req = max(0.2 * spot - max(spot - pK, 0), 0.1 * pK) + pm
                margin = (max(call_req, put_req) + (pm if call_req >= put_req else cm)) * 100
            iv_hv = (atm_iv / hv20) if (hv20 and atm_iv) else None
            flag = "PASS" if (ivr is not None and ivr >= 50 and dvol > 1e8) else ("WATCH" if ivr is not None and ivr >= 30 else "FAIL")

            con.execute("INSERT OR REPLACE INTO mh.iv_history VALUES (?,?,?,?,?, 'yf_chain')", [today, sym, target, atm_iv, spot])
            con.execute("INSERT INTO screener_runs VALUES (CAST(current_timestamp AT TIME ZONE 'UTC' AS TIMESTAMP),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [sym, spot, target, dte, atm_iv, ivr, ivr_kind, hv20, hv_rank,
                         pp[0] if pp else None, pp[1] if pp else None,
                         cc[0] if cc else None, cc[1] if cc else None,
                         credit, margin, dvol, flag])
            def f2(v, d=2):
                return "-" if v is None else f"{v:.{d}f}"
            out_lines.append(
                f"| {sym} | {spot:.2f} | {target} | {dte} | {atm_iv:.1%} | "
                f"{'-' if ivr is None else f'{ivr:.0f}'} | {f2(hv20)} | {f2(hv_rank,0)} | {f2(iv_hv)} | "
                f"{'-' if not pp else f'{pp[0]:.0f}({pp[1]:.2f})'} | "
                f"{'-' if not cc else f'{cc[0]:.0f}({cc[1]:.2f})'} | "
                f"{f2(credit)} | {'-' if margin is None else f'{margin:,.0f}'} | {dvol/1e6:,.0f}M | {flag} |")
            print(f"{sym}: IV {atm_iv:.1%} IVR* {f2(ivr,0)} ({ivr_kind}) HV20 {hv20:.1%} "
                  f"credit {f2(credit)} margin {f2(margin,0)} [{flag}]")
        except Exception as e:
            print(f"{sym}: FAILED — {repr(e)[:150]}")

    # ---- exit calendar for current positions ----
    out_lines.append("\n## Exit calendar (21 DTE) — current book\n")
    out_lines.append("| Underlying | Expiry | 21-DTE exit | Repick window |")
    out_lines.append("|---|---|---|---|")
    for u, exp in con.execute("SELECT DISTINCT underlying, expiry FROM positions WHERE expiry IS NOT NULL ORDER BY expiry").fetchall():
        exit_d = exp - dt.timedelta(days=21)
        out_lines.append(f"| {u} | {exp} | {exit_d} | {exit_d - dt.timedelta(days=7)} … {exit_d} |")

    report = "\n".join(out_lines)
    rep = ROOT / "reports" / f"screener_v1_{today}.md"   # v2 owns reports/screener_<date>.md
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(report, encoding="utf-8")
    con.close()
    print(f"\nwritten: {rep}")
    print("\nIVR* = 100 * (latest IV - min IV) / (max IV - min IV), using 60+ daily yf_chain points; flat or insufficient history is unrankable.")


# Guard added by the data/application split: unguarded, importing this module ran it.
if __name__ == "__main__":
    main()
