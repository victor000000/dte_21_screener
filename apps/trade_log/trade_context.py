import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401
from data import db

"""trade_context.py — trade-context document for a trading day, straight from trades.duckdb.

For --date YYYY-MM-DD it writes var/derived/trade_context_<date>[_tag].md containing:
  * every fill that day (all accounts) with fill-time context
  * underlying +-span-min bars around each fill (underlying_minutes)
  * option EOD series for the traded strikes across all stored snapshots (before/after)
  * underlying EOD series (underlying_daily)
  * option order-ladder snapshots (快期 OrderReport -> chain_snapshots.source='qsqh_orders')
  * account_daily row

Usage: uv run python trade_context.py --date 2026-09-30 [--tag sc_close] [--span-min 30]
"""
import argparse
import datetime as dt
import pathlib

import duckdb

DB = bootstrap.DATA_ROOT / "trades.duckdb"
OUT = bootstrap.DATA_ROOT / "var" / "derived"
CST = dt.timedelta(hours=8)


def und_map(underlying):
    """fills.underlying -> underlying_minutes/daily symbol"""
    u = (underlying or "").lower()
    if u.startswith("sc"):
        return "SC2612"
    if u.startswith("ma"):
        return "MA2701"
    if u.startswith("mo"):
        return "IM2610"  # MO (中证1000 options) underlying proxy: IM2610 futures
    return (underlying or "").upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--span-min", type=int, default=30)
    args = ap.parse_args()
    day = dt.date.fromisoformat(args.date)

    # underlying_minutes / underlying_daily live in market_history, NOT trades: they moved
    # there when the bulk tables were split out. This opened trades.duckdb alone and then
    # queried them unqualified, so the window and EOD sections raised CatalogException.
    # db.connect attaches both (trades as the default catalog, market_history as `mh`).
    con = db.connect(log="ro", history="ro")
    L = []
    A = L.append
    A(f"# Trade context {args.date}{' - ' + args.tag if args.tag else ''}")
    A("")
    A("Auto-generated from trades.duckdb. Times CST for China fills, ET for US (ts_orig).")

    A("\n## Fills\n")
    A("| fill | time (orig) | account | symbol | action | qty | px | fee | realized | underlying_px | IV | delta |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in con.execute("""SELECT fill_id, ts_utc, ts_orig, account, symbol, action, open_close, qty,
            price, fee, realized_pnl, underlying_px, iv_at_fill, delta_at_fill, underlying
        FROM fills WHERE CAST(ts_utc AS DATE)=CAST(? AS DATE) ORDER BY fill_id""", [args.date]).fetchall():
        fid, tsu, tso, acct, sym, act, oc, qty, px, fee, pnl, upx, iv, d, und = r
        t = tsu + CST if acct == "CN_ACCOUNT" else tsu
        ivs = f"{iv:.1%}" if iv else "-"
        ds = f"{d:+.3f}" if d is not None else "-"
        A(f"| #{fid} | {t.strftime('%H:%M:%S')} | {acct} | {sym} | {act} {oc} | {qty} | {px} | {fee} | {pnl} | {upx} | {ivs} | {ds} |")

    A("\n## Orders — every order event (`orders`: filled / cancelled / modified-as-new-order)\n")
    orows = con.execute("""SELECT ts_submit_utc, symbol, action, open_close, limit_price, qty, filled_qty,
            avg_fill_price, status, order_id FROM orders
        WHERE CAST(ts_submit_utc AS DATE)=CAST(? AS DATE) ORDER BY ts_submit_utc""", [args.date]).fetchall()
    if orows:
        A("| time CST | symbol | action | limit | qty | filled | avg | status | order_id |")
        A("|---|---|---|---|---|---|---|---|---|")
        for r in orows:
            t = (r[0] + CST).strftime("%H:%M:%S") if r[0] else "-"
            qty = f"{r[5]:.0f}" if r[5] is not None else "-"
            fill = f"{r[6]:.0f}" if r[6] is not None else "-"
            lp = r[4] if r[4] is not None else "-"
            A(f"| {t} | {r[1]} | {r[2] or ''} {r[3] or ''} | {lp} | {qty} | {fill} | {r[7] if r[7] is not None else '-'} | {r[8]} | {r[9]} |")
    else:
        A("(none stored for this date)")

    A(f"\n## Underlying +-{args.span_min}min windows (`underlying_minutes`)\n")
    fills = con.execute("""SELECT DISTINCT underlying, ts_utc FROM fills
        WHERE CAST(ts_utc AS DATE)=CAST(? AS DATE)""", [args.date]).fetchall()
    symbols = sorted({und_map(f[0]) for f in fills})
    # min()/max() on an empty sequence raise ValueError, so any date with no fills --
    # a weekend, a holiday, a day whose fills came from another source -- crashed the
    # whole context report instead of writing "(none)". The docstring promises a
    # reproducible per-day document; an empty day is a document, not an exception.
    if fills:
        t0 = min(f[1] for f in fills) - dt.timedelta(minutes=args.span_min)
        t1 = max(f[1] for f in fills) + dt.timedelta(minutes=args.span_min)
    else:
        t0 = t1 = None
        A("(no fills for this date — no windows to scan)")
    for sym in symbols:
        rows = con.execute("""SELECT ts_utc, open, high, low, close, volume FROM mh.underlying_minutes
            WHERE symbol=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc""", [sym, t0, t1]).fetchall()
        A(f"### {sym} ({len(rows)} bars)\n")
        if rows:
            A("| time | O | H | L | C | vol |")
            A("|---|---|---|---|---|---|")
            for r in rows:
                A(f"| {r[0].strftime('%m-%d %H:%M')} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
            A("")

    A("\n## Option EOD series — traded strikes (all stored snapshots)\n")
    legs = con.execute("""SELECT DISTINCT underlying, strike, call_put FROM fills
        WHERE CAST(ts_utc AS DATE)=CAST(? AS DATE) AND strike IS NOT NULL""", [args.date]).fetchall()
    for und, K, cp in legs:
        ukey = und_map(und)
        rows = con.execute("""SELECT s.ts_utc, s.source, r.mid, r.iv, r.delta, r.oi, r.volume, r.spot
            FROM chain_rows r JOIN chain_snapshots s USING (snap_id)
            WHERE r.underlying IN (?, ?) AND r.strike=? AND r.call_put=?
            ORDER BY s.ts_utc""", [und, ukey, K, cp]).fetchall()
        A(f"### {ukey} {K:.0f}{cp} ({len(rows)} snapshots)\n")
        if rows:
            A("| date | source | settle/mid | IV | delta | OI | vol | spot |")
            A("|---|---|---|---|---|---|---|---|")
            for r in rows:
                iv = f"{r[3]:.1%}" if r[3] else "-"
                dl = f"{r[4]:+.3f}" if isinstance(r[4], float) else (r[4] or "-")
                A(f"| {r[0].strftime('%Y-%m-%d')} | {r[1]} | {r[2]} | {iv} | {dl} | {r[5]} | {r[6]} | {r[7]} |")
            A("")

    A("\n## Order ladder snapshots (`qsqh_orders`)\n")
    snaps = con.execute("""SELECT snap_id, ts_utc, underlying FROM chain_snapshots
        WHERE source='qsqh_orders' AND CAST(ts_utc AS DATE)=CAST(? AS DATE)""", [args.date]).fetchall()
    for sid, tsu, und in snaps:
        rows = con.execute("""SELECT mid, strike, call_put, spot FROM chain_rows
            WHERE snap_id=? ORDER BY strike, call_put, mid""", [sid]).fetchall()
        A(f"### snapshot #{sid} {und} ({len(rows)} price points)\n")
        A("| px | contract | spot |")
        A("|---|---|---|")
        for r in rows:
            A(f"| {r[0]} | {und} {r[1]:.0f}{r[2]} | {r[3]} |")
        A("")

    A("\n## Underlying EOD series (`underlying_daily`)\n")
    for sym in symbols:
        rows = con.execute("""SELECT day, open, high, low, close, settle, volume, oi, source
            FROM mh.underlying_daily WHERE symbol=? ORDER BY day""", [sym]).fetchall()
        A(f"### {sym} ({len(rows)} days)\n")
        if rows:
            A("| day | O | H | L | C | settle | vol | OI | source |")
            A("|---|---|---|---|---|---|---|---|---|")
            for r in rows:
                A(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |")
            A("")

    A("\n## Positions (current `positions` table — latest known state, all brokers)\n")
    A("| account | broker | underlying | type | strike/expiry | qty | avg | spot | delta_units | theta_day | vega_pt |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in con.execute("""SELECT account, broker, underlying, sec_type, expiry, strike, call_put, qty,
            avg_price, spot, delta_units, theta_day, vega_pt FROM positions ORDER BY account, underlying, strike""").fetchall():
        se = f"{r[5]:.0f}{r[6] or ''} {r[4]}" if r[4] else "stock"
        A(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {se} | {r[7]} | {r[8]} | {r[9]} | "
          f"{r[10]:.1f} | {r[11]:.1f} | {r[12]:.1f} |" if r[4] else
          f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | stock | {r[7]} | {r[8]} | {r[9]} | - | - | - |")

    A("\n## Account daily\n")
    A("| account | net_liq | margin | available | realized | fees | risk | source | notes |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in con.execute("""SELECT account, net_liq, margin_used, available, realized_pnl, fees, risk_ratio, source, notes
        FROM account_daily WHERE day=CAST(? AS DATE)""", [args.date]).fetchall():
        A("| " + " | ".join("" if x is None else str(x) for x in r) + " |")

    name = f"trade_context_{args.date}" + (f"_{args.tag}" if args.tag else "") + ".md"
    (OUT / name).write_text("\n".join(L) + "\n")
    print(f"written: var/derived/{name} ({len(L)} lines)")
    con.close()


if __name__ == "__main__":
    main()
