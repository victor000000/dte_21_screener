import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

# ── --help guard ─────────────────────────────────────────────────────────────
# No argparse here, so `script.py --help` used to execute this script in full.
# That is not hypothetical: a 2026-10-05 sweep ran every app with --help and
# rewrote `fills`, `risk_profile` and `positions`. The write does not have to be
# in THIS file either -- live_risk_profile.py orchestrates build_positions and
# risk_profile through subprocess, so "does it INSERT?" is the wrong test. The
# rule is simply that a script with no argument parser must not run on --help.
from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below, and a
# docstring must be the first statement, so all 33 copies printed "(no docstring)".
from data import db

"""trade_window_analysis.py — per-trade [-30min,+30min] movement scan.

For every fill with window data in underlying_minutes it computes:
  range% (max-min over window), pre-move (start->fill), post-move (fill->end) and flags
  LARGE moves. Also compares fill-time IV to the prior EOD chain IV for the same contract
  where both exist (US: CBOE frozen 9/28; CN: akshare EOD snapshots).
Writes reports/trade_window_moves_<date>.md and prints the summary.

Usage: uv run python trade_window_analysis.py
"""
import datetime as dt
from data import clock
import pathlib

import duckdb

ROOT = bootstrap.ROOT
def main():
    # see trade_context.py: underlying_minutes lives in market_history, not trades
    con = db.connect(log="ro", history="ro")

    SPAN = 30
    rows = con.execute("""SELECT fill_id, account, broker, underlying, symbol, ts_utc, price, underlying_px,
        strike, call_put, expiry, iv_at_fill, action, qty FROM fills
    WHERE ts_utc IS NOT NULL ORDER BY ts_utc""").fetchall()

    MAP = {"MA701P2650": "MA2701", "MA701C3350": "MA2701", "sc2612P570": "SC2612", "sc2612C880": "SC2612",
           "MO2610-P-7400": "IM2610", "MO2610-C-7900": "IM2610"}

    out = ["# Trade-window movement scan — [fill-30min, fill+30min]", ""]
    flags = []
    iv_rows = []
    for fid, acct, broker, und, sym, ts, px, upx, K, cp, exp, iv, act, qty in rows:
        usym = MAP.get(sym, und)
        bars = con.execute("""SELECT ts_utc, open, high, low, close FROM mh.underlying_minutes
        WHERE symbol=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc""",
            [usym, ts - dt.timedelta(minutes=SPAN), ts + dt.timedelta(minutes=SPAN)]).fetchall()
        if not bars:
            continue
        hi = max(b[2] for b in bars)
        lo = min(b[3] for b in bars)
        start = bars[0][1]
        end = bars[-1][4]
        mid = upx or bars[0][4]
        rng = (hi - lo) / mid * 100 if mid else 0
        pre = (mid - start) / start * 100 if start else 0
        post = (end - mid) / mid * 100 if mid else 0
        line = (f"| #{fid} | {ts:%m-%d %H:%M} | {broker} | {sym} | {act} {qty}@{px} | S {mid:.2f} | "
                f"range {rng:.2f}% | pre {pre:+.2f}% | post {post:+.2f}% | {len(bars)} bars |")
        out.append(line)
        if rng >= 1.0 or abs(pre) >= 0.8 or abs(post) >= 0.8:
            flags.append((max(rng, abs(pre), abs(post)), line))

    # IV vs prior-EOD for filled options
    for fid, acct, broker, und, sym, ts, px, upx, K, cp, exp, iv, act, qty in rows:
        if not iv or not K or not exp:
            continue
        eod = con.execute("""SELECT r.iv, s.ts_utc, s.source FROM chain_rows r JOIN chain_snapshots s USING (snap_id)
        WHERE r.underlying=? AND r.strike=? AND r.call_put=? AND s.ts_utc <= ? AND r.iv IS NOT NULL
        ORDER BY s.ts_utc DESC LIMIT 1""",
            ["MA701" if "MA" in sym else "SC2612" if "sc" in sym else "MO2610" if "MO" in sym else und, K, cp,
             ts]).fetchone()
        if eod and eod[0] and abs(eod[0] - iv) > 0.0001:
            iv_rows.append((f"| #{fid} | {ts:%m-%d} | {sym} | fill IV {iv:.1%} | prev-EOD IV {eod[0]:.1%} ({eod[2]}, {eod[1]:%m-%d}) | Δ {100*(iv-eod[0]):+.1f} pt |"))

    out += ["", f"## Large-move flags ({len(flags)})", ""] + [ln for _, ln in sorted(flags, reverse=True)]
    out += ["", f"## Fill IV vs prior-EOD chain IV ({len(iv_rows)})", ""] + [r for r in iv_rows]
    out += ["", "Note: intraday OPTION quotes are not available from any feed; option-side intraday moves "
            "(price/IV/smile) are recorded only via 快期 order ladders / capture-time snapshots."]

    (ROOT / "reports" / f"trade_window_moves_{clock.today().isoformat()}.md").write_text("\n".join(out) + "\n")
    print(f"fills with windows: {sum(1 for l in out if l.startswith('| #'))} | flags: {len(flags)} | iv comparisons: {len(iv_rows)}")
    print("written:", f"reports/trade_window_moves_{clock.today().isoformat()}.md")
    con.close()


# Guard added by the data/application split: unguarded, importing this module ran it.
if __name__ == "__main__":
    main()
