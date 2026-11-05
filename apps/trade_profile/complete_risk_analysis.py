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

"""complete_risk_analysis.py — Complete risk workflow with database persistence.

STANDARD PROCEDURE:
1. Fetch real-time extended hours prices from all sources
2. Calculate risk profile based on snapshot (last close)
3. Calculate risk profile based on real-time data
4. Save both to risk_snapshots table
5. Display comparison

All timestamps in UTC. Run anytime (RTH, pre-market, after-hours, overnight).

Run: uv run python apps/trade_profile/complete_risk_analysis.py
"""
import datetime as dt
import subprocess

from data import db
from data.schema.risk_snapshots import ensure as ensure_risk_snapshots
from apps.trade_profile.targets import analyze as targets_analyze  # noqa: E402
from apps.trade_profile.margin_curve import naked_core  # noqa: E402
from compute.bs import bs_price, implied_vol, T_years, bs_greeks

from shared.rates import R_US

from apps.trade_profile.complete_risk._state import _DISPUTED_REPORTED
from apps.trade_profile.complete_risk.session import is_market_hours
from apps.trade_profile.complete_risk.refresh import fetch_extended_hours_prices
from apps.trade_profile.complete_risk.quotes import get_latest_price
from apps.trade_profile.complete_risk.broker_quotes import get_real_option_quotes
from apps.trade_profile.complete_risk.canonical import canonical_snapshot_spots
from apps.trade_profile.complete_risk.theta_eod import fetch_theta_eod, _table_exists


# Set once so a table-level inconsistency is reported a single time per run
# rather than once per profile calculation.










def fetch_massive_eod(con, rows, closes, marks):
    """Massive (ex-Polygon) end-of-day closes and option bars.

    Mutates and returns (closes, marks) so it merges with the ThetaData result
    and the two can be compared line for line.

    The grouped endpoint fetches every US ticker in ONE request, so the 5/min
    free-tier limit does not bite on underlyings. The per-contract option path
    costs one request each, so results are cached per (contract, last session)
    -- a second run the same day spends zero requests.
    """
    try:
        from datasources.massive import get_client, occ_symbol
    except Exception as e:
        print(f"  Massive client unavailable: {repr(e)[:80]}")
        return closes, marks

    client = get_client()
    if not client.api_key:
        print("  Massive: no API key -- skipping")
        return closes, marks

    symbols = sorted({r[0] for r in rows})
    # The most recent completed session, from a source already fetched.
    end = dt.datetime.now(dt.timezone.utc).date()
    session = None
    for delta in range(1, 8):
        cand = end - dt.timedelta(days=delta)
        if cand.weekday() < 5:
            session = cand
            break
    if session is None:
        return closes, marks
    s = session.isoformat()

    # Cache: reuse this session's Massive marks if already stored.
    #
    # Keyed by (symbol, expiration, strike, call_put) -- ALL FOUR. Keying by the first
    # two collapses every contract sharing an expiry into one entry: CRWD 220P, 230P
    # and 330C all become "CRWD/2026-11-20", so only 5 of this book's 12 legs were
    # cached and the other 7 were re-fetched on every run at 5 requests/minute --
    # exactly the budget the cache exists to protect.
    #
    # theta_eod_marks is created without a key, so every run has appended a fresh copy
    # of each mark; arg_max takes the newest rather than an arbitrary one.
    cached_marks = {}
    if _table_exists(con, 'theta_eod_marks'):
        for sym, exp, k, cp, close in con.execute("""
                SELECT symbol, expiration, strike, call_put, arg_max(close, as_of_utc)
                FROM theta_eod_marks
                WHERE source='massive_eod' AND kind='option' AND as_of_utc::DATE >= ?
                GROUP BY symbol, expiration, strike, call_put
        """, [s]).fetchall():
            cached_marks[(sym, exp, float(k) if k is not None else None, cp)] = close

    try:
        grouped = client.grouped_stocks(s)
    except Exception as e:
        print(f"  Massive grouped failed: {repr(e)[:100]}")
        grouped = {}

    n_new = 0
    vendor_closes, vendor_marks = {}, {}
    for sym in symbols:
        g = grouped.get(sym)
        if g and g.get('close'):
            vendor_closes[sym] = g['close']
            closes.setdefault(sym, g['close'])

    for u, exp, k, cp in rows:
        key = (u, exp.isoformat(), float(k), cp)
        cached = cached_marks.get((u, exp.isoformat(), float(k), cp))
        if cached is not None:
            vendor_marks[key] = cached
            marks.setdefault(key, cached)
            continue
        try:
            bars = client.option_daily(occ_symbol(u, exp, float(k), cp), s, s)
            if bars and bars[-1].get('close') is not None:
                vendor_marks[key] = bars[-1]['close']
                marks.setdefault(key, bars[-1]['close'])
                n_new += 1
        except Exception as ex:
            print(f"  Massive option {u} {k}{cp} failed: {repr(ex)[:80]}")

    print(f"  Massive: {len(grouped)} tickers grouped, {n_new} new option bars "
          f"({len(cached_marks)} cached)")

    if _table_exists(con, 'theta_eod_marks'):
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        # Persist only Massive observations; merged inputs may belong to ThetaData.
        for sym, c in vendor_closes.items():
            if c is not None:
                con.execute("INSERT INTO theta_eod_marks VALUES (?, 'underlying', ?, NULL, NULL, NULL, ?, 'massive_eod')",
                            [now, sym, c])
        for u, exp, k, cp in rows:
            key = (u, exp.isoformat(), float(k), cp)
            if key in vendor_marks:
                con.execute("INSERT INTO theta_eod_marks VALUES (?, 'option', ?, ?, ?, ?, ?, 'massive_eod')",
                            [now, u, exp.isoformat(), float(k), cp, vendor_marks[key]])
    return closes, marks








def calculate_risk_profile(con, use_live=False, market_open=False, snapshot_time=None,
                           regular_hours=False,
                           theta_closes=None, theta_marks=None):
    """Calculate risk profile using either snapshot or live prices.

    Args:
        use_live: Use live underlying prices
        market_open: If True and use_live, fetch real option quotes from broker
        snapshot_time: Not used - kept for compatibility
    """
    # Get latest positions for each leg (latest as_of timestamp per unique leg)
    # Two things were wrong here and both silently halved the book.
    #
    # 1. The partition was (underlying, strike, call_put) with no account, so the
    #    rn=1 filter kept ONE row per contract and discarded the other account's
    #    leg. The book legitimately holds the same contract in two accounts --
    #    META 630P is -2 at IBKR and -2 at Schwab, CRWD 220P and 330C likewise --
    #    so every delta, vega and theta for those legs was exactly half the real
    #    position, and risk_snapshots recorded the wrong book permanently.
    #
    # 2. Even partitioned correctly, the rows then have to be COMBINED, not
    #    picked from: pick the newest row per (account, contract), then aggregate.
    #    Entry price becomes a size-weighted average, because two accounts can have
    #    opened the same contract at different prices and the combined P&L must be
    #    measured against what was actually paid.
    #
    #    The aggregation is PER ACCOUNT, not across accounts. It used to sum the
    #    accounts together, which was the right instinct for (1) -- a leg held at
    #    two brokers must not be halved -- but it threw away the one column an
    #    order needs. Every report here is now grouped by broker, because an order
    #    goes to one broker and a margin call is one broker's problem, and a row
    #    summed across accounts cannot be acted on at either. The totals are
    #    unchanged: they sum the same quantities, just in rows that still say
    #    whose they are.
    #
    # 3. `expiry` was missing from BOTH the partition and the group, which is the same
    #    defect as (1) one column over and was fixed later. PARTITION BY account,
    #    underlying, strike, call_put means the same account holding the same strike and
    #    right at two expiries is ONE partition, so ORDER BY as_of DESC kept the newer
    #    and DROPPED the other expiry's leg outright -- a silent halving again, this time
    #    by tenor. The GROUP BY then took max(expiry), so even correctly partitioned the
    #    two would have merged into a single leg labelled with the later date. Neither
    #    fires on the current book (0 groups collide today -- both are latent), but the
    #    calendar roll that creates one is routine: META 700C exists at Nov-20 and
    #    Dec-18 as soon as a position is rolled.
    #
    # 4. `qty <> 0` is tested on the ROWS, before aggregation, so two accounts that net to
    #    zero still produce a leg with qty 0. It has no sign, so every "is this short?"
    #    test below reads it as long, and it carries greeks and a mark into the profile.
    #    The HAVING applies the same test to the RESULT.
    #
    # `expiry` stays in the same SELECT position (index 7) even though it is now a
    # grouping key, so nothing downstream has to renumber.
    positions = con.execute("""
        WITH ranked AS (
            SELECT account, broker, underlying, strike, call_put, qty, avg_price, mark, spot,
                   expiry, delta_units, theta_day, vega_pt, gamma_units, delta_notional_usd, as_of,
                   -- `multiplier` must be carried by the CTE for the outer SELECT to be able
                   -- to read it. It was added to the outer list when the hardcoded *100 was
                   -- replaced with the stored contract size, and the CTE was not updated --
                   -- so the whole profile raised BinderException on the first run. Nothing
                   -- caught it because nothing in the gate EXECUTES this script.
                   multiplier,
                   ROW_NUMBER() OVER (PARTITION BY account, underlying, strike, call_put, expiry
                                      ORDER BY as_of DESC) as rn
            FROM positions
            WHERE sec_type = 'OPT' AND qty <> 0
        )
        SELECT underlying, strike, call_put,
               account,
               max(broker)                                         AS broker,
               sum(qty)                                            AS qty,
               sum(avg_price * abs(qty)) / nullif(sum(abs(qty)), 0) AS avg_price,
               max(mark)  AS mark,
               max(spot)  AS spot,
               max(expiry) AS expiry,
               sum(delta_units) AS delta_units,
               sum(theta_day)   AS theta_day,
               sum(vega_pt)     AS vega_pt,
               sum(gamma_units) AS gamma_units,
               sum(delta_notional_usd) AS delta_notional_usd,
               max(multiplier)          AS multiplier
        FROM ranked
        WHERE rn = 1
        GROUP BY underlying, strike, call_put, expiry, account
        HAVING sum(qty) <> 0
    """).fetchall()

    results = []

    # One baseline spot per underlying for the whole profile. Every leg of an
    # underlying must be measured against the same close, or the comparison
    # below is between two different things (see canonical_snapshot_spots).
    canonical = canonical_snapshot_spots(sorted({p[0] for p in positions}), theta_closes)
    theta_marks = theta_marks or {}
    disputed = []
    for underlying in sorted({p[0] for p in positions}):
        stored = con.execute(
            "SELECT DISTINCT spot FROM positions WHERE underlying = ? AND sec_type='OPT' AND qty <> 0",
            [underlying]).fetchall()
        if len({round(s[0], 4) for s in stored if s[0]}) > 1:
            disputed.append((underlying, sorted({s[0] for s in stored if s[0]})))

    # This function runs twice (snapshot + live); the table-level fault is the
    # same both times, so report it once rather than twice in one run.
    global _DISPUTED_REPORTED
    if disputed and not _DISPUTED_REPORTED:
        _DISPUTED_REPORTED = True
        print("  ⚠️  snapshot spot disagrees between legs of the same underlying:")
        for u, vals in disputed:
            print(f"      {u}: {vals} -> using last completed session close "
                  f"{canonical.get(u)}")

    # Fetch real option quotes if market is open
    real_option_quotes = {}
    if use_live and market_open:
        real_option_quotes = get_real_option_quotes(con, positions)

    for (underlying, strike, call_put, account, broker, qty, entry, snap_mark, snap_spot,
         expiry, delta_u, theta, vega, gamma, delta_not, mult) in positions:

        option_key = f"{underlying}_{strike}_{call_put}_{expiry}"
        use_estimated = True

        # Prefer the last completed session close over whatever per-leg value
        # happens to be stored.
        snap_spot = canonical.get(underlying) or snap_spot

        # Provenance of the two inputs that drive every number below. Both are
        # recorded on the row so a reader can tell a real price from a model
        # output -- the output used to present both identically, which is how a
        # Black-Scholes estimate came to be read as a market price.
        spot_source = 'snapshot'      # where the spot came from
        mark_source = 'snapshot'      # where the option mark came from

        if use_live:
            live_spot, _, session, source = get_latest_price(con, underlying)

            if live_spot:
                spot = live_spot
                spot_source = 'live'
            else:
                # No real-time quote for this ticker. Fall back to the snapshot
                # spot but SAY SO: previously these legs still reported the
                # session/source of nothing at all, and a "live" profile that
                # was byte-identical to the snapshot looked like a real result
                # rather than a missing feed.
                spot = snap_spot
                session = 'no_live_quote'
                source = 'snapshot_fallback'

            # A broker option quote is only a LIVE price during regular hours.
            #
            # Outside them these contracts have no two-sided market -- TWS returns a
            # close and nothing else -- so the "quote" is the same previous close the
            # snapshot column already holds, and labelling it Live claims a freshness it
            # does not have. In extended hours the honest live number is the model:
            # QuantLib re-priced at the real-time underlying, which HAS moved.
            if option_key in real_option_quotes and regular_hours:
                mark = real_option_quotes[option_key]['mark']
                mark_source = 'broker_quote'
                use_estimated = False
            elif regular_hours:
                mark_source = 'no_quote'
            else:
                mark_source = 'bs_estimate_ext'
        else:
            spot = snap_spot
            session = 'snapshot'
            source = 'snapshot'
            mark = snap_mark
            use_estimated = False
            # The snapshot side prices off the REAL traded close where ThetaData
            # has it, falling back to the stored mark. This is what makes the
            # snapshot column a market price rather than a model output.
            real = theta_marks.get((underlying, expiry.isoformat()
                                    if hasattr(expiry, 'isoformat') else str(expiry),
                                    float(strike), call_put))
            if real is not None:
                mark = real
                mark_source = 'theta_eod'

        if not spot or not entry or not snap_mark or not snap_spot:
            continue

        # Re-price option with current spot (if we don't have real quote)
        T = T_years(expiry)
        is_call = (call_put == 'C')

        # Solve IV from snapshot
        snap_iv = implied_vol(snap_mark, snap_spot, strike, T, R_US, is_call)

        if snap_iv and snap_iv > 0 and spot:
            # Only estimate if we don't have real quote
            if use_estimated:
                mark = bs_price(spot, strike, T, R_US, snap_iv, is_call)
                # A model output, not a market price. Held IV constant from the
                # snapshot, so this ignores any vol move since the close -- it is
                # a spot-sensitivity estimate, not a quote.
                mark_source = 'bs_estimate'

            # Calculate Greeks using QuantLib
            delta_per_share, gamma_val, theta_per_day, vega_per_point = bs_greeks(spot, strike, T, R_US, snap_iv, is_call)

            # Scale Greeks by position size
            if delta_per_share is not None:
                _m = mult or 100          # see the multiplier note on pnl_dollars below
                delta_units = delta_per_share * qty * _m  # delta in shares
                theta_day = theta_per_day * qty * _m      # theta in $/day
                vega_pt = vega_per_point * qty * _m       # vega in $/1% IV move
                gamma_units = gamma_val * qty * _m        # gamma
            else:
                delta_units = 0
                theta_day = 0
                vega_pt = 0
                gamma_units = 0
        else:
            if use_estimated:
                mark = snap_mark
                mark_source = 'snapshot'  # unsolvable IV: no estimate possible
            delta_units = 0
            theta_day = 0
            vega_pt = 0
            gamma_units = 0

        # P&L and 50% target, from the single shared implementation (targets.py).
        # Dollars stay here because they are the only part with a direction of its
        # own; the percentage, the target price and the distance are the arithmetic
        # that five files used to each re-derive.
        # MULTIPLIER FROM THE BOOK, not a hardcoded 100. Every leg reaching this line today
        # is US (the query filters sec_type='OPT', and CZCE futures options are 'FUT_OPT'),
        # so 100 happens to be right -- but it is a coincidence of what the filter excludes,
        # not a property of the position. MA701's multiplier is 10, and a leg that ever
        # reaches here would have had its P&L overstated tenfold, in the table the 50%
        # close rule is read off. `multiplier` is already stored per leg.
        mult = mult or 100
        pnl_dollars = (entry - mark) * abs(qty) * mult if qty < 0 else (mark - entry) * qty * mult
        _t = targets_analyze(entry, mark, qty)
        pnl_pct = _t['pnl_pct']
        target_50_price = _t['target_50']
        distance = _t['distance']

        results.append({
            'underlying': underlying,
            'strike': strike,
            'call_put': call_put,
            'broker': broker,
            'account': account,
            'qty': qty,
            'entry': entry,
            'mark': mark,
            'spot': spot,
            'pnl_pct': pnl_pct,
            'pnl_dollars': pnl_dollars,
            'target_50': target_50_price,
            'distance': distance,
            'session': session,
            'source': source,
            'spot_source': spot_source,
            'mark_source': mark_source,
            'snap_iv': snap_iv,
            'expiry': expiry,
            'delta': delta_units,
            'theta': theta_day,
            'vega': vega_pt,
            'gamma': gamma_units,
            'delta_notional': 0,
            'estimated': use_estimated
        })

    return results


def save_risk_snapshot(con, snapshot_results, live_results, snapshot_time, live_time):
    """Save risk profile to database."""
    ensure_risk_snapshots(con)

    # Match snapshot and live results
    for snap in snapshot_results:
        # Find corresponding live result
        live = next((l for l in live_results
                    if l['underlying'] == snap['underlying']
                    and l['strike'] == snap['strike']
                    and l['call_put'] == snap['call_put']
                    and l['expiry'] == snap['expiry']
                    and l['account'] == snap['account']), None)

        if not live:
            continue

        dte = (snap['expiry'] - live_time.date()).days if snap['expiry'] else None

        con.execute("""
            INSERT OR REPLACE INTO risk_snapshots (
                snapshot_timestamp_utc, live_timestamp_utc, account, broker,
                underlying, strike, call_put, qty,
                entry_price, snapshot_mark, snapshot_spot, snapshot_pnl_pct, snapshot_pnl_dollars,
                live_mark, live_spot, live_pnl_pct, live_pnl_dollars, target_50_price,
                distance_to_target, session_type, price_source, expiry, dte,
                delta_units, theta_day, vega_pt,
                spot_source, mark_source, snap_iv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            snapshot_time, live_time, snap['account'], snap['broker'],
            snap['underlying'], snap['strike'], snap['call_put'],
            snap['qty'], snap['entry'], snap['mark'], snap['spot'], snap['pnl_pct'],
            snap['pnl_dollars'], live['mark'], live['spot'], live['pnl_pct'],
            live['pnl_dollars'], live['target_50'], live['distance'], live['session'],
            live['source'], snap['expiry'], dte, snap['delta'], snap['theta'], snap['vega'],
            live.get('spot_source'), live.get('mark_source'), live.get('snap_iv')
        ])


def main():
    # Step 1: Fetch real-time prices
    if not fetch_extended_hours_prices():
        print("Failed to fetch extended hours prices")
        return

    print()
    print("=" * 100)
    print("STEP 2: Calculating Risk Profiles")
    print("=" * 100)

    con = db.connect()

    # Get the latest snapshot time for each position (use latest as_of per underlying)
    book_as_of = con.execute("SELECT max(as_of) FROM positions WHERE qty <> 0").fetchone()[0]
    # Fail HERE, with a reason. `positions.as_of` is stamped when the book is built,
    # and the snapshot it names is the baseline every P&L below is measured from. When
    # it is NULL the run used to fetch, price and display everything, then die on a
    # NOT NULL constraint in save_risk_snapshot -- after the expensive part, with no
    # indication of the cause.
    if book_as_of is None:
        print("positions.as_of is empty — the book has no vintage, so a snapshot risk "
              "profile would have no baseline to compare against.")
        print("Rebuild it first:  uv run python apps/plan/build_positions.py")
        con.close()
        return
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    # Real-time is the default, in extended hours as well as regular. `market_open`
    # still distinguishes the two for the label, but it no longer gates the fetch:
    # gating on 9:30-16:00 ET discarded every extended-hours quote, and the pre-market
    # book is a real market -- EWZ traded near 42 all night on 2026-10-05 while every
    # equity feed still reported the previous close of 38.19.
    market_open = is_market_hours()
    # No flag: real-time is what this profile IS. There was never an argument parser
    # here (the --help guard exists precisely because there is nothing to parse), so
    # "opt in to live prices" was not expressible anyway -- the only way to get them
    # was to edit the call below.
    live_enabled = True

    # Count positions
    pos_count = con.execute("SELECT COUNT(DISTINCT underlying || '-' || strike || '-' || call_put) FROM positions WHERE sec_type = 'OPT' AND qty <> 0").fetchone()[0]

    print(f"Snapshot time: {book_as_of:%Y-%m-%d %H:%M:%S} UTC ({pos_count} positions)")
    print(f"Live time:     {now_utc:%Y-%m-%d %H:%M:%S} UTC")
    print("Market status: " + ("OPEN" if market_open else
          "CLOSED (extended hours - real-time quotes are still fetched and used)"))
    print()

    # Real end-of-day prices. Two independent vendors are pulled and compared:
    # agreement between them is what makes the snapshot column trustworthy, and
    # a disagreement is reported rather than averaged away.
    print("Fetching EOD closes (ThetaData + Massive)...")
    theta_closes, theta_marks = fetch_theta_eod(con)
    theta_closes, theta_marks = fetch_massive_eod(
        con,
        con.execute("SELECT DISTINCT underlying, expiry, strike, call_put FROM positions "
                    "WHERE sec_type='OPT' AND qty <> 0").fetchall(),
        theta_closes, theta_marks)
    print()

    # Calculate both profiles - use latest positions for both snapshot and live
    snapshot_results = calculate_risk_profile(con, use_live=False, market_open=False,
                                              snapshot_time=None,
                                              theta_closes=theta_closes, theta_marks=theta_marks)
    live_results = calculate_risk_profile(con, use_live=live_enabled, market_open=True,
                                          snapshot_time=None,
                                          regular_hours=is_market_hours(),
                                          theta_closes=theta_closes, theta_marks=theta_marks)

    # Step 3: Save to database
    print("=" * 100)
    print("STEP 3: Saving Risk Snapshots to Database")
    print("=" * 100)

    save_risk_snapshot(con, snapshot_results, live_results, book_as_of, now_utc)
    print(f"Saved {len(snapshot_results)} risk snapshots")

    # Step 4: Display comparison
    print()
    print("=" * 150)

    # Mark provenance. The live column is a Black-Scholes re-pricing of the
    # snapshot IV against the live spot unless a broker quote was available --
    # state that per row rather than implying every number is a market price.
    n_bs = sum(1 for l in live_results if l.get('mark_source') == 'bs_estimate')
    n_real = sum(1 for l in live_results if l.get('mark_source') == 'broker_quote')
    n_nofeed = sum(1 for l in live_results if l.get('spot_source') == 'snapshot')

    pricing_note = (f" — {n_bs} leg(s) ESTIMATED from live underlying via Black-Scholes; "
                    f"{n_real} from broker quote(s)")
    if n_nofeed:
        pricing_note += f"; {n_nofeed} leg(s) had no live underlying quote"

    print(f"RISK PROFILE: Snapshot vs Estimated{pricing_note}")
    print("=" * 150)
    print("  BY LEGS, BY BROKER, at real-time underlying prices — this is the default reading.")
    print("  'Snap' is the last stored close. 'Est' is the option re-priced with QuantLib at")
    print("  the REAL-TIME underlying, IV held at its snapshot value.")
    print("  In EXTENDED HOURS that is the only live number: these contracts have no two-sided")
    print("  market, so TWS returns a close and a broker 'quote' would just restate the snapshot")
    print("  under a fresher label. During REGULAR hours a real broker quote is used instead and")
    print("  'Mark src' says so per row — never read the two columns as the same kind of number.")
    print("=" * 150)
    # The broker's OWN BP effect, read from its statement, beats anything we compute.
    # Comparing the two settled it: over the same eleven Schwab positions the Reg-T
    # formula gives 125,179 against the statement's 43,381 -- 2.9x too high -- and the
    # per-leg ratios run from 0.05 (EWZ 43C, netted inside a strangle) to 1.40 (SWKS
    # 110C, where Schwab's floor is not 10% of the underlying at all). No single
    # correction factor fits, because a broker nets within an account and applies its
    # own house rules; the number is not derivable from the position, it has to be read.
    broker_bp, acct_margin = {}, {}
    try:
        for r in con.execute("""SELECT broker, leg_key, bp_effect, account_margin_init,
                                       account_margin_maint FROM broker_margin
                                WHERE as_of = (SELECT max(as_of) FROM broker_margin)""").fetchall():
            if r[2] is not None:
                broker_bp[(r[0], r[1])] = r[2]
            if r[3] is not None:
                acct_margin[r[0]] = (r[3], r[4])
    except Exception:
        pass                      # no statement loaded; the formula below still runs

    # Calibration for a broker whose per-leg figures we do NOT have but whose ACCOUNT
    # total we do (IBKR: from reqAccountSummary). Without it the formula column summed to
    # 64,298 against a real 39,786 -- a column that is wrong in total is worse than one
    # that is wrong per row, because the total is what a reader adds up. Scaling the legs
    # by the measured ratio makes the column sum to the broker's own requirement, so each
    # row is an ATTRIBUTION of a known total rather than an unanchored guess. It is still
    # an estimate -- the ratio is one number applied to every leg, so it does not model
    # the netting structure within a strangle -- and the caller labels it `c` for that.
    calib = {}

    def bp_effect(S, K, cp, qty, mark, mult):
        """BP EFFECT: the broker's margin requirement for this option.

        Prefers the broker's own figure (broker_margin, from its statement). Where only
        the ACCOUNT total is known, the formula is scaled to it. Otherwise it is the raw
        Reg-T formula, which OVERSTATES -- see the note above; the caller labels which.

        Reg-T / maintenance, per contract: 20% of the underlying minus the out-of-the-money
        amount, floored at 10%, PLUS the premium received. The floor is taken against the
        UNDERLYING for a call and the EXERCISE PRICE for a put -- that asymmetry is what
        stops a deep-OTM put getting cheaper to carry once spot runs away from it.

        Each option is measured ON ITS OWN, which is what the broker shows per position.
        A long option occupies nothing: it is paid for in full, so its requirement is zero
        rather than negative. An earlier version of this column computed a MARGINAL figure
        -- the group's requirement with the leg minus without it -- which made long wings
        come out negative and was answering a different question: how much of the book's
        margin this row owns, rather than what this option costs to carry.

        The rule is margin_curve.naked_core, imported rather than reimplemented.
        """
        if qty >= 0:
            # A long option occupies its market value: the position is an asset worth
            # qty * mark * mult, and that is what it ties up. Returning 0 treated a long
            # as free, which made the ratio wings look like they cost nothing -- the
            # opposite error to the one before, where the marginal version made them
            # negative. This is the convention the user gave: "the bp effect for long
            # options is only the position size * option price".
            return abs(qty) * (mark or 0.0) * mult
        return (naked_core(S, K, cp, abs(qty), mult)
                + (mark or 0.0) * abs(qty) * mult)

    HDR = (f"{'Leg':<16} {'Qty':>4} {'Entry':>8} {'Mark':>8} {'Spot':>9} {'Spot Δ%':>8} | "
           f"{'Snap P&L%':>10} {'Est P&L%':>10} {'Δ':>7} | "
           f"{'Δunits':>8} {'θ/day':>8} {'vega':>8} | {'BP effect':>10} | "
           f"{'Mark src':<13} {'Spot src':<10}")

    # Sort all positions by live P&L percentage (descending)
    all_positions = sorted(snapshot_results, key=lambda x: -next((l['pnl_pct'] for l in live_results
                                          if l['underlying'] == x['underlying']
                                          and l['strike'] == x['strike']
                                          and l['call_put'] == x['call_put']
                                          and l['expiry'] == x['expiry']
                    and l['account'] == x['account']), 0))

    total_snap_pnl = 0
    total_live_pnl = 0

    # Grouped by broker. The leg view is the DEFAULT reading of this profile -- the
    # aggregated tables above answer "what is my exposure", but every action is taken on
    # a leg at one broker, so the leg list is what the profile is actually for.
    def _live_of(snap):
        # The key is (account, underlying, strike, call_put, expiry). Each column in it
        # was added after it silently paired the wrong legs: call_put when a call and a
        # put at one strike matched each other, expiry when a roll produced two, account
        # when the rows became per-broker and IBKR's leg started matching Schwab's.
        return next((l for l in live_results
                     if l['underlying'] == snap['underlying']
                     and l['strike'] == snap['strike']
                     and l['call_put'] == snap['call_put']
                     and l['expiry'] == snap['expiry']
                     and l['account'] == snap['account']), None)

    for broker in sorted({x['broker'] for x in all_positions}):
        grp = [x for x in all_positions if x['broker'] == broker]
        # per-leg broker figure missing but the account total known -> one ratio
        if broker in acct_margin and not any((broker, f"{x['strike']:g}{x['call_put']}") in broker_bp
                                             for x in grp):
            m = 10 if broker == "浙商期货" else 100
            raw = 0.0
            for x in grp:
                lv = _live_of(x) or x
                raw += bp_effect(lv.get("spot"), x["strike"], x["call_put"], x["qty"],
                                 lv.get("mark"), m)
            if raw > 0:
                calib[broker] = acct_margin[broker][1] / raw
        th = sum((_live_of(x) or x)['theta'] or 0.0 for x in grp)
        vg = sum((_live_of(x) or x)['vega'] or 0.0 for x in grp)
        fx = 7.13 if broker == "浙商期货" else 1.0
        print(f"\n[{broker}]  {len(grp)} legs · theta {th / fx:+,.1f}/day · "
              f"vega {vg / fx:+,.1f}/vol-pt")
        mult = 10 if broker == "浙商期货" else 100

        print(HDR)
        print("-" * len(HDR))

        for snap in grp:
            live = _live_of(snap)
            if not live:
                continue
            delta_pnl_pct = live['pnl_pct'] - snap['pnl_pct']
            delta_pnl_dollars = live['pnl_dollars'] - snap['pnl_dollars']
            total_snap_pnl += snap['pnl_dollars']
            total_live_pnl += live['pnl_dollars']
            leg = f"{snap['underlying']} {snap['strike']:.0f}{snap['call_put']}"
            # The underlying's move since the snapshot spot -- the single number that
            # explains the gap between the two P&L columns, and the one a leg view was
            # missing: -23.5% on a short put means nothing until you see TLT moved 0.1%.
            spot_move = ((live['spot'] / snap['spot'] - 1) * 100
                         if (live.get('spot') and snap.get('spot')) else None)
            lv = live if live else snap
            lk = f"{snap['strike']:g}{snap['call_put']}"
            # A LONG leg is qty * price by rule, and the rule wins over the statement.
            # The user gave it explicitly ("the bp effect for long options is only the
            # position size * option price") and then said the Schwab statement does not
            # print 0 for its longs -- which is what I read there, twice, on a page
            # rotated 90 degrees that I had already misread once. Rather than keep
            # asserting a broker figure I cannot confirm, longs take the stated rule
            # everywhere, so the column is internally consistent and every long row is
            # arithmetic the reader can check by hand.
            long_leg = snap["qty"] > 0
            if (broker, lk) in broker_bp and not long_leg:
                me, me_src = broker_bp[(broker, lk)], "r"
            elif broker in calib:
                me = bp_effect(lv["spot"], snap["strike"], snap["call_put"], snap["qty"],
                               lv["mark"], mult) * calib[broker]
                me_src = "c"
            else:
                me = bp_effect(lv["spot"], snap["strike"], snap["call_put"], snap["qty"],
                               lv["mark"], mult)
                me_src = "*"
            print(f"{leg:<16} {snap['qty']:>4} {snap['entry']:>8.4f} {live['mark']:>8.4f} "
                  f"{live['spot']:>9,.2f} "
                  f"{(f'{spot_move:>+7.1f}%' if spot_move is not None else f'{chr(8212):>8}')} | "
                  f"{snap['pnl_pct']:>+9.1f}% {live['pnl_pct']:>+9.1f}% "
                  f"{delta_pnl_pct:>+6.1f}% | {live['delta'] if live['delta'] is not None else 0:>8,.0f} "
                  f"{live['theta'] if live['theta'] is not None else 0:>8,.1f} "
                  f"{live['vega'] if live['vega'] is not None else 0:>8,.1f} | "
                  f"{(me / fx if me is not None else 0):>10,.0f}{me_src} | "
                  f"{str(live.get('mark_source')):<13} {str(live.get('spot_source')):<10}")
        continue

    delta_total_pnl = total_live_pnl - total_snap_pnl
    print(f"{'=' * 115}\nTOTAL  snapshot {total_snap_pnl:>+10,.0f}   live "
          f"{total_live_pnl:>+10,.0f}   delta {delta_total_pnl:>+10,.0f}")
    print("=" * 150)

    if n_bs:
        print()
        print(f"⚠️  All {n_bs} 'Est' marks are Black-Scholes ESTIMATES, not market prices.")
        print("   Method: solve IV from the last close mark, re-price at the live underlying spot.")
        print("   IV is held at its snapshot value, so any vol move since the close is ignored —")
        print("   treat these as spot-sensitivity, not as quotable prices.")
    if n_nofeed:
        print(f"⚠️  {n_nofeed} leg(s) had NO live underlying quote; spot fell back to the snapshot")
        print("   (session = 'no_live_quote'). Those rows are not a live view.")

    # Categorize by live pricing
    print()
    print("=" * 130)
    print("CATEGORIZATION (Estimated from live underlying)")
    print("=" * 130)

    shorts_live = [(s, next((l for l in live_results
                            if l['underlying'] == s['underlying']
                            and l['strike'] == s['strike']
                            and l['call_put'] == s['call_put']
                            and l['expiry'] == s['expiry']
                    and l['account'] == s['account']), None))
                   for s in all_positions if s['qty'] < 0]
    shorts_live = [(s, l) for s, l in shorts_live if l]

    longs_live = [(s, next((l for l in live_results
                            if l['underlying'] == s['underlying']
                            and l['strike'] == s['strike']
                            and l['call_put'] == s['call_put']
                            and l['expiry'] == s['expiry']
                    and l['account'] == s['account']), None))
                  for s in all_positions if s['qty'] > 0]
    longs_live = [(s, l) for s, l in longs_live if l]

    reached = [(s, l) for s, l in shorts_live if l['pnl_pct'] >= 50]
    approaching = [(s, l) for s, l in shorts_live if 40 <= l['pnl_pct'] < 50]
    losing_shorts = [(s, l) for s, l in shorts_live if l['pnl_pct'] < 0]
    losing_longs = [(s, l) for s, l in longs_live if l['pnl_pct'] < 0]

    # Grouped by broker, and the broker is printed on every line. An order goes to one
    # broker, so a leg listed without one cannot be acted on -- and before this the same
    # contract at two brokers produced two identical-looking lines (CRWD 220P appeared
    # twice at +44.6%) with nothing to say which was which.
    def by_broker(pairs):
        for broker in sorted({s['broker'] for s, _ in pairs}):
            yield broker, [(s, l) for s, l in pairs if s['broker'] == broker]

    if reached:
        print("\n✅ REACHED 50% - CLOSE NOW")
        for broker, grp in by_broker(reached):
            print(f"  [{broker}]")
            for s, l in grp:
                print(f"    {s['underlying']} {s['strike']:.0f}{s['call_put']} x{s['qty']} | "
                      f"P&L +{l['pnl_pct']:.1f}% (${l['pnl_dollars']:,.0f})")

    if approaching:
        print("\n⚡ APPROACHING 50% (40-50%)")
        for broker, grp in by_broker(approaching):
            print(f"  [{broker}]")
            for s, l in grp:
                dte = (s['expiry'] - now_utc.date()).days if s['expiry'] else None
                print(f"    {s['underlying']} {s['strike']:.0f}{s['call_put']} x{s['qty']} | "
                      f"P&L +{l['pnl_pct']:.1f}% | Need {l['distance']:.1f}% | DTE: {dte}d")

    if losing_shorts or losing_longs:
        print("\n❌ LOSING POSITIONS")
        all_losing = sorted(losing_shorts + losing_longs, key=lambda x: x[1]['pnl_pct'])
        # The cap was 5 across the whole book, which on a book of 18 cuts a broker out
        # entirely. Per broker instead, so every broker's worst legs are visible.
        for broker, grp in by_broker(all_losing):
            print(f"  [{broker}]")
            for s, l in grp[:5]:
                spot_chg = (l['spot'] - s['spot']) / s['spot'] * 100
                side = "SHORT" if s['qty'] < 0 else "LONG"
                print(f"    {s['underlying']} {s['strike']:.0f}{s['call_put']} x{s['qty']} ({side}) | "
                      f"P&L {l['pnl_pct']:.1f}% (${l['pnl_dollars']:,.0f}) | "
                      f"Spot: ${s['spot']:.2f}→${l['spot']:.2f} ({spot_chg:+.1f}%)")

    print()
    print(f"Risk snapshot saved to database: {len(snapshot_results)} legs")
    print(f"Query with: SELECT * FROM risk_snapshots WHERE live_timestamp_utc >= '{now_utc:%Y-%m-%d %H:%M:%S}'")

    con.close()


if __name__ == "__main__":
    main()
