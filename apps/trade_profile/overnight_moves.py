import pathlib
import os
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

"""overnight_moves.py — show overnight/24h price changes for all positions.

Compares the snapshot prices (from last build_positions.py run) against current live prices
from all available sources. Essential for understanding risk profile changes outside RTH.

Run: uv run python apps/trade_profile/overnight_moves.py
"""
import datetime as dt
import duckdb
from ib_async import IB, Stock

from data import db
from datasources import ibmarks
from datasources import tws

import yfinance as yf

try:
    from futu import OpenQuoteContext
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False


def get_live_prices(tickers):
    """Fetch live prices from all sources and return best available."""
    all_prices = {}

    # Try all sources
    for ticker in tickers:
        prices = {'sources': []}

        # yfinance
        try:
            t = yf.Ticker(ticker)
            info = t.info
            bid = info.get('bid')
            ask = info.get('ask')
            current = info.get('currentPrice') or info.get('regularMarketPrice')

            if bid and ask and bid > 0 and ask > 0:
                prices['yfinance'] = (bid + ask) / 2
                prices['sources'].append('yfinance(mid)')
            elif current and current > 0:
                prices['yfinance'] = current
                prices['sources'].append('yfinance(curr)')
        except:
            pass

        all_prices[ticker] = prices

    # TWS
    try:
        ib = IB()
        ib.RequestTimeout = 45
        tws.connect(ib, client_id=112, timeout=25)
        n = ibmarks.clean

        stock_pairs = list(zip(tickers, ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in tickers])))
        stock_ok = [(s, c) for s, c in stock_pairs if c]

        if stock_ok:
            for (s, _), t in zip(stock_ok, ib.reqTickers(*[c for _, c in stock_ok])):
                bid, ask = n(t.bid), n(t.ask)
                if bid and ask:
                    all_prices[s]['tws'] = (bid + ask) / 2
                    all_prices[s]['sources'].append('TWS(mid)')
                elif n(t.last):
                    all_prices[s]['tws'] = n(t.last)
                    all_prices[s]['sources'].append('TWS(last)')

        ib.disconnect()
    except:
        pass

    # Futu
    if FUTU_AVAILABLE:
        try:
            ctx = OpenQuoteContext(host=os.environ.get("FUTU_HOST", "host.docker.internal"), port=11111)
            for ticker in tickers:
                code = f"US.{ticker}"
                ret, data = ctx.get_market_snapshot([code])
                if ret == 0 and not data.empty:
                    last_price = data.iloc[0].get('last_price')
                    if last_price and last_price > 0:
                        all_prices[ticker]['futu'] = float(last_price)
                        all_prices[ticker]['sources'].append('Futu')
            ctx.close()
        except:
            pass

    # Pick best price per ticker
    final = {}
    for ticker, prices in all_prices.items():
        # Priority: TWS mid > yfinance mid > TWS last > others
        if prices.get('tws'):
            final[ticker] = (prices['tws'], 'TWS')
        elif prices.get('yfinance'):
            final[ticker] = (prices['yfinance'], 'yfinance')
        elif prices.get('futu'):
            final[ticker] = (prices['futu'], 'Futu')
        else:
            final[ticker] = (None, 'NONE')

    return final


def main():
    con = db.connect()

    # Get snapshot prices and time
    snapshot = con.execute("""
        SELECT underlying, spot, as_of
        FROM positions
        WHERE qty <> 0
        GROUP BY underlying, spot, as_of
        ORDER BY underlying
    """).fetchall()

    if not snapshot:
        print("No positions found")
        return

    snapshot_time = snapshot[0][2]
    age_minutes = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - snapshot_time).total_seconds() / 60

    print("=" * 110)
    print(f"Overnight / 24h Price Movement Analysis")
    print("=" * 110)
    print(f"Snapshot time: {snapshot_time:%Y-%m-%d %H:%M:%S} UTC ({age_minutes:.0f} minutes ago)")
    print(f"Current time:  {dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):%Y-%m-%d %H:%M:%S} UTC")
    print()

    # Get live prices
    us_tickers = [u for u, _, _ in snapshot if u != 'MA701']  # Exclude CN futures
    print(f"Fetching live prices for {len(us_tickers)} underlyings...")
    live_prices = get_live_prices(us_tickers)

    # Calculate moves
    print()
    print(f"{'Underlying':<10} {'Snapshot':>10} {'Live':>10} {'Change $':>11} {'Change %':>10} {'Source':<15} {'Status':<15}")
    print("-" * 110)

    moves = []
    for u, snap_spot, _ in snapshot:
        if u == 'MA701':
            # CN futures - use snapshot
            print(f"{u:<10} {snap_spot:>10.2f} {snap_spot:>10.2f} {'--':>11} {'--':>10} {'snapshot':<<15} {'Market closed':<15}")
            continue

        live, source = live_prices.get(u, (None, 'NONE'))

        if live and snap_spot:
            chg_d = live - snap_spot
            chg_p = (chg_d / snap_spot) * 100

            if abs(chg_p) >= 5:
                status = '⚠️ MAJOR JUMP'
            elif abs(chg_p) >= 2:
                status = '⚡ SIGNIFICANT'
            elif abs(chg_p) >= 1:
                status = '📊 NOTABLE'
            else:
                status = 'Normal'

            moves.append((abs(chg_p), u, snap_spot, live, chg_d, chg_p, source, status))

    # Sort by magnitude and print
    moves.sort(reverse=True)
    for _, u, snap, live, chg_d, chg_p, source, status in moves:
        sign = '+' if chg_d >= 0 else ''
        print(f"{u:<10} {snap:>10.2f} {live:>10.2f} {sign}{chg_d:>10.2f} {sign}{chg_p:>9.2f}% {source:<15} {status:<15}")

    # Show position impact for major moves
    major_moves = [(u, chg_p) for _, u, _, _, _, chg_p, _, status in moves if 'MAJOR' in status or 'SIGNIFICANT' in status]

    if major_moves:
        print()
        print("=" * 110)
        print("Position Impact Analysis")
        print("=" * 110)

        for u, chg_p in major_moves:
            legs = con.execute("""
                SELECT strike, call_put, qty, delta_notional_usd
                FROM positions
                WHERE underlying = ? AND sec_type = 'OPT'
                ORDER BY strike
            """, [u]).fetchall()

            if legs:
                sign = '+' if chg_p >= 0 else ''
                print(f"\n{u}: {sign}{chg_p:.1f}% move")
                for K, cp, q, dn in legs:
                    side = 'SHORT' if q < 0 else 'LONG'
                    print(f"  {side} {abs(q):>3}x {K:>6.0f}{cp}: Δ${dn:>12,.0f}")

    con.close()


if __name__ == "__main__":
    main()
