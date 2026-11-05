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

"""live_underlying_risk.py — fetch real-time underlying prices from all sources, then analyze risk.

Combines:
1. TWS for US equities (IBKR account holdings)
2. Futu for cross-validation and additional coverage
3. yfinance as fallback
4. CN marks from latest broker snapshot

Then rebuilds positions and shows underlying risk breakdown.

Run: uv run python apps/trade_profile/live_underlying_risk.py
"""
import datetime as dt
import duckdb
from ib_async import IB, Stock

from data import db
from datasources import ibmarks
from datasources import tws

import yfinance as yf

try:
    from futu import OpenQuoteContext, TradeDateMarket
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False

def validated_spot(con, ticker):
    """The stored, cross-source-VALIDATED live spot for a ticker, or None.

    This script used to fetch from TWS/Alpaca/yfinance/Futu itself, with its own
    source order (Alpaca -> yfinance -> TWS) and no cross-check. That is how it
    reported TLT at 82.94 -- the bogus yfinance quote the standard fetcher rejects
    -- while everything else in the repo had already been taught to distrust it.
    A second implementation of "what is the live price" does not inherit the
    validation done for the first, so it reintroduces exactly the bug that
    validation was built to catch.

    extended_hours_quotes already holds only quotes that survived the
    cross-source consensus check (fetch_extended_hours_prices), flagged
    is_realtime. Prefer it; the local fetchers below are the fallback for a
    ticker it does not cover.
    """
    try:
        r = con.execute("""
            SELECT mid, last, session_type, source FROM extended_hours_quotes
            WHERE ticker = ? AND is_realtime
              AND timestamp_utc >= CAST(current_timestamp AT TIME ZONE 'UTC' AS TIMESTAMP)
                                   - INTERVAL '30 minutes'
            ORDER BY CASE source WHEN 'TWS' THEN 1 WHEN 'Alpaca' THEN 2
                                 WHEN 'Tiingo' THEN 3 WHEN 'yfinance' THEN 4
                                 ELSE 5 END,
                     timestamp_utc DESC
            LIMIT 1
        """, [ticker]).fetchone()
    except Exception:
        return None
    if not r:
        return None
    price = r[0] if r[0] else r[1]
    return (price, f"{r[3]} (validated)") if price else None


def get_tws_spots(tickers):
    """Fetch real-time spot prices from TWS."""
    spots = {}
    try:
        ib = IB()
        ib.RequestTimeout = 45
        tws.connect(ib, client_id=111, timeout=25)

        n = ibmarks.clean
        stock_pairs = list(zip(tickers, ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in tickers])))
        stock_ok = [(s, c) for s, c in stock_pairs if c]

        for s, c in stock_pairs:
            if not c:
                print(f"  TWS: {s} could not qualify")

        if stock_ok:
            for (s, _), t in zip(stock_ok, ib.reqTickers(*[c for _, c in stock_ok])):
                bid, ask = n(t.bid), n(t.ask)
                spots[s] = {
                    'mid': (bid + ask) / 2 if (bid and ask) else None,
                    'last': n(t.last),
                    'close': n(t.close),
                    'source': 'TWS'
                }

        ib.disconnect()
    except Exception as e:
        print(f"  TWS error: {repr(e)[:200]}")

    return spots

def get_alpaca_spots(tickers):
    """Fetch real-time spot prices from Alpaca."""
    spots = {}
    if not ALPACA_AVAILABLE:
        print("  Alpaca API not available")
        return spots

    try:
        import os
        api_key = os.environ.get('ALPACA_API_KEY')
        api_secret = os.environ.get('ALPACA_SECRET_KEY')

        if not api_key or not api_secret:
            print("  Alpaca credentials not found in environment")
            return spots

        client = StockHistoricalDataClient(api_key, api_secret)
        request = StockLatestQuoteRequest(symbol_or_symbols=tickers)
        quotes = client.get_stock_latest_quote(request)

        for ticker, quote in quotes.items():
            if quote.ask_price and quote.bid_price and quote.ask_price > 0 and quote.bid_price > 0:
                mid = (quote.ask_price + quote.bid_price) / 2
                spots[ticker] = {
                    'mid': float(mid),
                    'bid': float(quote.bid_price),
                    'ask': float(quote.ask_price),
                    'source': 'Alpaca'
                }
                print(f"  {ticker}: ${mid:.2f} (Alpaca)")
            elif quote.ask_price and quote.ask_price > 0:
                spots[ticker] = {
                    'last': float(quote.ask_price),
                    'source': 'Alpaca'
                }
                print(f"  {ticker}: ${quote.ask_price:.2f} (Alpaca, ask only)")
    except Exception as e:
        print(f"  Alpaca error: {repr(e)[:200]}")

    return spots

def get_futu_spots(tickers):
    """Fetch real-time spot prices from Futu OpenD."""
    spots = {}
    if not FUTU_AVAILABLE:
        print("  Futu API not available (install futu-api)")
        return spots

    try:
        ctx = OpenQuoteContext(host=os.environ.get("FUTU_HOST", "host.docker.internal"), port=11111)

        for ticker in tickers:
            try:
                # Futu requires market prefix
                code = f"US.{ticker}"
                ret, data = ctx.get_market_snapshot([code])
                if ret == 0 and not data.empty:
                    row = data.iloc[0]
                    last_price = row.get('last_price')
                    if last_price and last_price > 0:
                        spots[ticker] = {
                            'last': float(last_price),
                            'source': 'Futu'
                        }
                        print(f"  {ticker}: ${float(last_price):.2f} (Futu)")
            except Exception as e:
                print(f"  Futu: {ticker} error: {repr(e)[:100]}")

        ctx.close()
    except Exception as e:
        print(f"  Futu connection error: {repr(e)[:200]}")

    return spots

def get_yf_spots(tickers):
    """Fetch real-time spot prices from yfinance (intraday data when market open)."""
    spots = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            # Try to get real-time/intraday data first
            info = t.info
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            bid = info.get('bid')
            ask = info.get('ask')

            if bid and ask and bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spots[ticker] = {
                    'mid': float(mid),
                    'bid': float(bid),
                    'ask': float(ask),
                    'source': 'yfinance'
                }
                print(f"  {ticker}: ${mid:.2f} (yfinance bid/ask)")
            elif current_price and current_price > 0:
                spots[ticker] = {
                    'last': float(current_price),
                    'source': 'yfinance'
                }
                print(f"  {ticker}: ${current_price:.2f} (yfinance current)")
            else:
                # Fallback to historical close
                hist = t.history(period="1d")
                if not hist.empty:
                    spots[ticker] = {
                        'close': float(hist["Close"].iloc[-1]),
                        'source': 'yfinance'
                    }
                    print(f"  {ticker}: ${hist['Close'].iloc[-1]:.2f} (yfinance close)")
        except Exception as e:
            print(f"  yfinance: {ticker} error: {repr(e)[:100]}")
    return spots

def main():
    con = db.connect()

    # Get all underlyings from positions
    underlyings = con.execute("""
        SELECT DISTINCT underlying, sec_type
        FROM positions
        WHERE qty <> 0
        ORDER BY underlying
    """).fetchall()

    us_tickers = [u for u, st in underlyings if st in ('OPT', 'STOCK')]
    cn_tickers = [u for u, st in underlyings if st == 'FUT_OPT']

    print("=" * 100)
    print("Fetching real-time underlying prices from all sources...")
    print("=" * 100)

    # Fetch from all sources
    print("\n1. Alpaca (primary real-time source):")
    alpaca_spots = get_alpaca_spots(us_tickers)

    print("\n2. TWS (Interactive Brokers):")
    tws_spots = get_tws_spots(us_tickers)

    print("\n3. Futu OpenD:")
    futu_spots = get_futu_spots(us_tickers)

    print("\n4. yfinance (real-time via info API):")
    yf_spots = get_yf_spots(us_tickers)

    # Combine sources - prefer Alpaca mid > TWS mid > yfinance mid > others
    print("\n5. Combining sources (priority: Alpaca mid > TWS mid > yfinance mid > Futu/last > close):")
    final_spots = {}
    for ticker in us_tickers:
        # VALIDATED FIRST. The table below already holds only quotes that passed the
        # cross-source consensus check, so it cannot contain the bogus yfinance TLT
        # print that this script's own fetchers accepted. The local chain is the
        # fallback for a ticker the standard fetcher does not cover.
        pre = validated_spot(con, ticker)
        if pre:
            final_spots[ticker] = pre
            print(f"  {ticker}: ${pre[0]:.2f} ({pre[1]})")
            continue

        alpaca = alpaca_spots.get(ticker, {})
        tws = tws_spots.get(ticker, {})
        futu = futu_spots.get(ticker, {})
        yf_data = yf_spots.get(ticker, {})

        # Priority: Alpaca mid > TWS mid > yfinance mid > Futu > Alpaca/yf/TWS last > yfinance close
        if alpaca.get('mid'):
            spot = alpaca['mid']
            source = 'Alpaca'
        elif tws.get('mid'):
            spot = tws['mid']
            source = 'TWS'
        elif yf_data.get('mid'):
            spot = yf_data['mid']
            source = 'yfinance'
        elif futu.get('last'):
            spot = futu['last']
            source = 'Futu'
        elif alpaca.get('last'):
            spot = alpaca['last']
            source = 'Alpaca'
        elif yf_data.get('last'):
            spot = yf_data['last']
            source = 'yfinance'
        elif tws.get('last'):
            spot = tws['last']
            source = 'TWS'
        elif tws.get('close'):
            spot = tws['close']
            source = 'TWS-close'
        elif yf_data.get('close'):
            spot = yf_data['close']
            source = 'yfinance-close'
        else:
            spot = None
            source = 'STALE'

        if spot:
            final_spots[ticker] = (spot, source)
            print(f"  {ticker}: ${spot:.2f} ({source})")
        else:
            print(f"  {ticker}: NO PRICE")

    if cn_tickers:
        print(f"\n3. China futures: {len(cn_tickers)} tickers (using broker snapshot)")
        for ticker in cn_tickers:
            print(f"  {ticker}: using CZCE snapshot (market closed)")

    # Now analyze underlying risk with these real-time prices
    print("\n" + "=" * 100)
    print("Underlying Risk Breakdown (real-time)")
    print("=" * 100)

    result = con.execute('''
        SELECT
            underlying,
            spot,
            SUM(CASE WHEN sec_type='OPT' THEN delta_units ELSE qty END) as net_delta_units,
            SUM(vega_pt) as vega_usd,
            SUM(theta_day) as theta_usd,
            SUM(CASE WHEN sec_type='OPT' AND qty < 0 THEN ABS(qty) ELSE 0 END) as short_contracts,
            SUM(CASE WHEN sec_type='OPT' AND qty > 0 THEN qty ELSE 0 END) as long_contracts
        FROM positions
        WHERE qty <> 0
        GROUP BY underlying, spot
        ORDER BY ABS(SUM(CASE WHEN sec_type='OPT' THEN delta_notional_usd ELSE qty * spot END)) DESC
    ''').fetchall()

    print(f"\n{'Underlying':<10} {'Spot':>10} {'Source':>16} {'Δ $':>14} {'Vega':>10} {'Theta':>10} {'Structure':<20}")
    print("-" * 100)

    total_delta = 0
    total_vega = 0
    total_theta = 0

    for u, snap_spot, delta_units, vega, theta, shorts, longs in result:
        # ACTUALLY use the live spot. `final_spots` was populated from TWS/Alpaca/
        # yfinance/Futu and then only its source NAME was printed: the Spot column
        # and the delta notional were both snapshot values, under a "real-time"
        # heading and a Source column naming a live feed. Now the live spot is the
        # one displayed, and the notional is recomputed from it.
        live_spot, source = final_spots.get(u, (None, 'snapshot'))
        spot = live_spot or snap_spot
        delta_usd = delta_units * spot
        stale = " (snapshot)" if (live_spot is None and source != "snapshot") else ""
        structure = []
        if shorts > 0:
            structure.append(f"{shorts}sh")
        if longs > 0:
            structure.append(f"{longs}lg")
        structure_str = " ".join(structure) or "stock"

        total_delta += delta_usd
        total_vega += vega
        total_theta += theta

        print(f"{u:<10} {spot:>10.2f} {(str(source) + stale):>16} {delta_usd:>14,.0f} "
              f"{vega:>10,.0f} {theta:>10,.0f} {structure_str:<20}")

    print("-" * 100)
    print(f"{'TOTAL':<10} {'':>10} {'':>10} {total_delta:>14,.0f} {total_vega:>10,.0f} {total_theta:>10,.0f}")

    # Show detailed leg breakdown for positions with significant risk
    print("\n" + "=" * 100)
    print("Detailed Leg Breakdown (top exposures)")
    print("=" * 100)

    top_underlyings = [u for u, _, delta_usd, _, _, _, _ in result[:5]]

    for u in top_underlyings:
        legs = con.execute('''
            SELECT sec_type, strike, call_put, qty, spot, delta_notional_usd,
                   vega_pt, theta_day, avg_price, mark
            FROM positions
            WHERE underlying = ? AND qty <> 0
            ORDER BY sec_type, strike
        ''', [u]).fetchall()

        if not legs:
            continue

        spot = legs[0][4]
        source = final_spots.get(u, (None, 'snapshot'))[1]
        print(f"\n{u} @ ${spot:.2f} ({source})")

        for sec_type, K, cp, q, spot, dn, v, th, entry, mark in legs:
            if sec_type == 'STOCK':
                print(f"  STOCK {q:>4}x: Δ$={dn:>12,.0f}")
            else:
                side = 'SHORT' if q < 0 else 'LONG'
                if entry and mark:
                    pnl_pct = ((entry - mark) / entry * 100) if q < 0 else ((mark - entry) / entry * 100)
                    print(f"  {side:<5} {abs(q):>3}x {K:>6.0f}{cp}: Δ$={dn:>12,.0f}, V={v:>8,.0f}, Θ={th:>7,.0f}, P&L={pnl_pct:>6.1f}%")
                else:
                    print(f"  {side:<5} {abs(q):>3}x {K:>6.0f}{cp}: Δ$={dn:>12,.0f}, V={v:>8,.0f}, Θ={th:>7,.0f}")

    con.close()

if __name__ == "__main__":
    main()
