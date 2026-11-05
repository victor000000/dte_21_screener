"""theta_eod.py — see the package docstring."""
import datetime as dt
import bootstrap

def _table_exists(con, name):
    try:
        return con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [name]).fetchone()[0] > 0
    except Exception:
        return False


def fetch_theta_eod(con):
    """Pull last-close and real option prices from the local ThetaData terminal.

    Returns (underlying_closes, option_marks): {SYM: close} and
    {(sym, exp, strike, cp): close}. Both empty when the terminal is down.

    This is the ONLY source here that gives a REAL traded option price. Every
    other mark in the live profile is a Black-Scholes re-pricing. ThetaData's
    free tier serves end-of-day only, which is precisely the snapshot side of
    the comparison, so it slots in as the authority for "last close" rather
    than as another live feed.
    """
    closes, marks = {}, {}
    try:
        from datasources.thetadata import get_client
    except Exception as e:
        print(f"  ThetaData client unavailable: {repr(e)[:80]}")
        return closes, marks

    client = get_client()
    if not client.terminal_available():
        print(f"  ThetaData: terminal unreachable at {client.base_url} -- skipping")
        return closes, marks

    rows = con.execute("""
        SELECT DISTINCT underlying, expiry, strike, call_put
        FROM positions WHERE sec_type='OPT' AND qty <> 0
    """).fetchall()
    if not rows:
        return closes, marks

    symbols = sorted({r[0] for r in rows})
    # 14 calendar days back is enough to clear a weekend; the LAST row is the
    # most recent completed session.
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=14)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    # One request PER symbol. The endpoint rejects a comma-joined list with
    # "472: This endpoint takes one symbol, but the request has N".
    for sym in symbols:
        try:
            got = client.get_stock_eod(sym, s, e)
            if got and got[-1].get('close'):
                closes[sym] = got[-1]['close']
        except Exception as ex:
            print(f"  ThetaData stock EOD failed {sym}: {repr(ex)[:80]}")

    n_opt = 0
    for u, exp, k, cp in rows:
        try:
            got = client.get_option_eod(u, exp.isoformat(), float(k), cp, s, e)
            if got and got[-1].get('close') is not None:
                marks[(u, exp.isoformat(), float(k), cp)] = got[-1]['close']
                n_opt += 1
        except Exception as ex:
            print(f"  ThetaData option EOD failed {u} {k}{cp}: {repr(ex)[:80]}")

    print(f"  ThetaData: {len(closes)} underlying closes, {n_opt} real option marks")

    con.execute("""
        CREATE TABLE IF NOT EXISTS theta_eod_marks (
            as_of_utc TIMESTAMP, kind TEXT, symbol TEXT, expiration TEXT,
            strike DOUBLE, call_put TEXT, close DOUBLE, source TEXT
        )
    """)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for sym, c in closes.items():
        con.execute("INSERT INTO theta_eod_marks VALUES (?, 'underlying', ?, NULL, NULL, NULL, ?, 'theta_eod')",
                    [now, sym, c])
    for (sym, exp, k, cp), c in marks.items():
        con.execute("INSERT INTO theta_eod_marks VALUES (?, 'option', ?, ?, ?, ?, ?, 'theta_eod')",
                    [now, sym, exp, k, cp, c])

    return closes, marks
