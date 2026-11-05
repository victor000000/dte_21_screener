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

"""live_profit_targets.py — estimate 50% profit targets using real-time extended hours pricing.

Uses real-time underlying prices from extended_hours_quotes table (pre/after/overnight markets)
to re-price options via Black-Scholes and estimate when each leg will reach 50% profit.

Shows TWO risk profiles:
1. Based on last market close (snapshot)
2. Based on real-time extended hours data

Run: uv run python apps/trade_profile/live_profit_targets.py
"""
import datetime as dt
import duckdb

from data import db
from apps.trade_profile.targets import analyze as targets_analyze  # noqa: E402
from compute.bs import bs_greeks, bs_price, implied_vol, T_years

from shared.rates import R_US, R_CN, FX_CNY as FXCNY

def get_latest_extended_hours_price(con, ticker):
    """Get most recent price from extended_hours_quotes, prefer bid/ask mid."""
    result = con.execute("""
        SELECT mid, last, timestamp_utc, session_type, source
        FROM extended_hours_quotes
        WHERE ticker = ?
        ORDER BY timestamp_utc DESC
        LIMIT 1
    """, [ticker]).fetchone()

    if not result:
        return None, None, None, None

    mid, last, ts, session, source = result
    price = mid if mid else last
    return price, ts, session, source


def analyze_leg(underlying, strike, call_put, qty, entry, mark, spot, expiry, delta_u, theta_d, vega_pt,
                is_live=False, multiplier=100):
    """Analyze a single leg's P&L and distance to 50% profit.

    `multiplier` is the contract size from the book (100 US options, 10 for CZCE methanol).
    It defaults to 100 because every caller filters sec_type='OPT', which excludes the
    'FUT_OPT' legs whose multiplier is 10 -- but the value belongs to the position, not to
    the filter, and a 10x error here is a 10x error in the 50% close rule.
    """
    if not entry or not mark or not spot:
        return None

    T = T_years(expiry)
    is_call = (call_put == 'C')

    # P&L and 50% target from the shared implementation (targets.py); dollars stay
    # here because direction is the only part they have of their own.
    _t = targets_analyze(entry, mark, qty)
    _m = multiplier or 100
    pnl_dollars = (entry - mark) * abs(qty) * _m if qty < 0 else (mark - entry) * qty * _m
    pnl_pct = _t['pnl_pct']
    target_50_price = _t['target_50']
    distance_to_target = _t['distance']

    # Estimate days to 50% using theta
    if theta_d and qty < 0:  # For shorts, theta helps
        theta_per_contract = theta_d / abs(qty)
        dollars_to_target = (mark - target_50_price) * _m
        days_to_target = dollars_to_target / abs(theta_per_contract) if theta_per_contract else None
    else:
        days_to_target = None

    return {
        'mark': mark,
        'spot': spot,
        'pnl_pct': pnl_pct,
        'pnl_dollars': pnl_dollars,
        'target_50_price': target_50_price,
        'distance': distance_to_target,
        'days_to_target': days_to_target
    }


def main():
    con = db.connect()

    # Get all option positions
    positions = con.execute("""
        SELECT underlying, strike, call_put, qty, avg_price, mark, spot, expiry,
               delta_units, theta_day, vega_pt, broker, account, multiplier
        FROM positions
        WHERE sec_type = 'OPT' AND qty <> 0
        ORDER BY underlying, strike
    """).fetchall()

    if not positions:
        print("No option positions found")
        con.close()
        return

    print("=" * 130)
    print("RISK PROFILE COMPARISON: Last Market Close vs Real-Time Extended Hours")
    print("=" * 130)
    print()

    # Get book vintage
    book_as_of = con.execute("SELECT max(as_of) FROM positions WHERE qty <> 0").fetchone()[0]
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    if book_as_of:
        age_min = (now_utc - book_as_of).total_seconds() / 60
        print(f"Snapshot time: {book_as_of:%Y-%m-%d %H:%M:%S} UTC ({age_min:.0f} min ago)")
    print(f"Current time:  {now_utc:%Y-%m-%d %H:%M:%S} UTC")
    print()

    # Analyze each leg twice: snapshot and live
    results = []

    for underlying, strike, call_put, qty, entry, snapshot_mark, snapshot_spot, expiry, delta_u, theta_d, vega_pt, broker, acct, mult in positions:

        # Get live extended hours price
        live_spot, price_ts, session, source = get_latest_extended_hours_price(con, underlying)

        if not live_spot:
            live_spot = snapshot_spot
            session = 'snapshot'
            source = 'snapshot'

        if not live_spot or not entry or not snapshot_spot:
            continue

        # Re-price option using BS with live spot
        T = T_years(expiry)
        is_call = (call_put == 'C')

        # Solve IV from snapshot mark
        if snapshot_mark and snapshot_spot:
            snapshot_iv = implied_vol(snapshot_mark, snapshot_spot, strike, T, R_US, is_call)
        else:
            snapshot_iv = None

        # Calculate live mark using BS with same IV but new spot
        if snapshot_iv and snapshot_iv > 0 and live_spot:
            live_mark = bs_price(live_spot, strike, T, R_US, snapshot_iv, is_call)
        else:
            # Fallback: scale by delta
            if snapshot_mark and delta_u and qty:
                spot_change_pct = (live_spot - snapshot_spot) / snapshot_spot
                # delta_units is the POSITION delta: qty * delta * 100 (see
                # build_positions.py). Dividing by |qty| alone therefore leaves the
                # contract multiplier in, giving 100x the per-share delta -- a 2%
                # spot move on a 0.3-delta option moved the mark 60% instead of
                # 0.6%. This branch runs whenever IV cannot be solved from the
                # stale mark, and it feeds every live P&L and the 50% target
                # categorisation, so the error was silent and large.
                delta_per_share = delta_u / (abs(qty) * (mult or 100))
                live_mark = snapshot_mark * (1 + spot_change_pct * delta_per_share)
            else:
                live_mark = snapshot_mark

        # Analyze both snapshot and live
        snapshot_analysis = analyze_leg(underlying, strike, call_put, qty, entry, snapshot_mark,
                                       snapshot_spot, expiry, delta_u, theta_d, vega_pt,
                                       multiplier=mult)

        live_analysis = analyze_leg(underlying, strike, call_put, qty, entry, live_mark,
                                   live_spot, expiry, delta_u, theta_d, vega_pt,
                                   multiplier=mult)

        if not snapshot_analysis or not live_analysis:
            continue

        dte = (expiry - now_utc.date()).days if expiry else None

        results.append({
            'underlying': underlying,
            'strike': strike,
            'call_put': call_put,
            'qty': qty,
            'entry': entry,
            'snapshot': snapshot_analysis,
            'live': live_analysis,
            'spot_snapshot': snapshot_spot,
            'spot_live': live_spot,
            'spot_change_pct': (live_spot - snapshot_spot) / snapshot_spot * 100,
            'session': session,
            'source': source,
            'expiry': expiry,
            'dte': dte
        })

    # Sort by live P&L percentage (for shorts)
    results = [r for r in results if r['qty'] < 0]  # Focus on shorts
    results.sort(key=lambda x: -x['live']['pnl_pct'])

    # Print comparison
    print("=" * 130)
    print("50% PROFIT TARGET ANALYSIS - SNAPSHOT vs LIVE")
    print("=" * 130)
    print(f"{'Leg':<18} {'Qty':>4} {'Entry':>7} | {'Snap Mark':>9} {'P&L%':>7} {'To 50%':>7} | {'Live Mark':>9} {'P&L%':>7} {'To 50%':>7} | {'ΔP&L':>7} {'Session':<10}")
    print("-" * 130)

    for r in results:
        leg = f"{r['underlying']} {r['strike']:.0f}{r['call_put']}"
        snap = r['snapshot']
        live = r['live']

        delta_pnl = live['pnl_pct'] - snap['pnl_pct']
        delta_sign = '+' if delta_pnl >= 0 else ''

        snap_sign = '+' if snap['pnl_pct'] >= 0 else ''
        live_sign = '+' if live['pnl_pct'] >= 0 else ''

        print(f"{leg:<18} {r['qty']:>4} ${r['entry']:>6.2f} | "
              f"${snap['mark']:>8.2f} {snap_sign}{snap['pnl_pct']:>6.1f}% {snap['distance']:>6.1f}% | "
              f"${live['mark']:>8.2f} {live_sign}{live['pnl_pct']:>6.1f}% {live['distance']:>6.1f}% | "
              f"{delta_sign}{delta_pnl:>6.1f}% {r['session']:<10}")

    print()
    print("=" * 130)
    print("CATEGORIZATION - LIVE PRICING")
    print("=" * 130)
    print()

    # Categorize based on live pricing
    reached_50 = [r for r in results if r['live']['pnl_pct'] >= 50]
    approaching = [r for r in results if 40 <= r['live']['pnl_pct'] < 50]
    profit = [r for r in results if 25 <= r['live']['pnl_pct'] < 40]
    small_profit = [r for r in results if 0 <= r['live']['pnl_pct'] < 25]
    losing = [r for r in results if r['live']['pnl_pct'] < 0]

    if reached_50:
        print("✅ REACHED 50% PROFIT - CLOSE NOW")
        for r in reached_50:
            live = r['live']
            print(f"  {r['underlying']} {r['strike']:.0f}{r['call_put']} x{r['qty']} | "
                  f"P&L +{live['pnl_pct']:.1f}% (${live['pnl_dollars']:,.0f}) | "
                  f"Live ${live['mark']:.2f} ({r['session']})")
        print()

    if approaching:
        print("⚡ APPROACHING 50% (40-50%) - WATCH CLOSELY")
        for r in approaching:
            live = r['live']
            days_str = f"{live['days_to_target']:.1f}d" if live['days_to_target'] and live['days_to_target'] > 0 else "N/A"
            print(f"  {r['underlying']} {r['strike']:.0f}{r['call_put']} x{r['qty']} | "
                  f"P&L +{live['pnl_pct']:.1f}% | Need {live['distance']:.1f}% more (~{days_str}) | "
                  f"DTE: {r['dte']}d | Spot ${r['spot_live']:.2f} ({r['session']})")
        print()

    if losing:
        print("❌ LOSING POSITIONS (live pricing)")
        for r in losing[:5]:
            live = r['live']
            spot_chg = r['spot_change_pct']
            print(f"  {r['underlying']} {r['strike']:.0f}{r['call_put']} x{r['qty']} | "
                  f"P&L {live['pnl_pct']:.1f}% (${live['pnl_dollars']:,.0f}) | "
                  f"Spot: ${r['spot_snapshot']:.2f}→${r['spot_live']:.2f} ({spot_chg:+.1f}%) {r['session']}")
        print()

    # Summary
    print("SUMMARY")
    print("-" * 130)
    print(f"Ready to close (≥50%):       {len(reached_50)} legs")
    print(f"Approaching target (40-50%): {len(approaching)} legs")
    print(f"Building profit (25-40%):    {len(profit)} legs")
    print(f"Small profit (0-25%):        {len(small_profit)} legs")
    print(f"Losing positions:            {len(losing)} legs")
    print()
    print(f"Pricing sources: {', '.join(set(r['source'] for r in results))}")
    print(f"Market sessions: {', '.join(set(r['session'] for r in results))}")

    con.close()


if __name__ == "__main__":
    main()
