"""us_book.py — the US book DERIVED from what the brokers report.

Split out of build_positions.py, which is on the size ratchet, but it belongs apart
anyway: this is trade-log ingestion, not position building, and it exists because a
hand-written position list went stale five times.
"""
from data.schema import broker_costs


def us_book(con, fallback):
    """The US book DERIVED from `broker_positions`, entry prices from `fills`.

    `broker_positions` was ruled out as the source because it lacks `avg_price`. It does
    -- but the entry price of a position IS the weighted average of the fills that OPENED
    it, and `fills` has that. The caller's `fallback` still supplies entries whose opening fill
    predates our coverage, so this changes WHAT IS HELD (the staleness that recurred five
    times) without regressing what anything cost.
    """
    entry = {(a, u, str(e), float(k), cp): px for a, _b, u, _t, e, k, cp, _q, px in fallback}
    reported = broker_costs.current_prices(con)
    rows = con.execute("""
        WITH cur AS (
            SELECT b.* FROM broker_positions b
             WHERE b.as_of = (SELECT max(b2.as_of) FROM broker_positions b2
                               WHERE b2.account = b.account AND b2.broker = b.broker)
               AND b.sec_type = 'OPT' AND b.qty <> 0),
        opened AS (SELECT account, symbol, sum(qty * price) / sum(qty) AS px,
                          count(*) AS n_open
                     FROM fills WHERE open_close = 'OPEN' GROUP BY 1, 2),
        closed AS (SELECT account, symbol, count(*) AS n_close
                     FROM fills WHERE open_close = 'CLOSE' GROUP BY 1, 2)
        SELECT cur.account, cur.broker, cur.underlying, cur.sec_type, cur.expiry,
               cur.strike, cur.call_put, cur.qty, o.px, coalesce(o.n_open, 0),
               coalesce(c.n_close, 0)
          FROM cur LEFT JOIN opened o ON o.account = cur.account AND o.symbol = cur.symbol
                   LEFT JOIN closed c ON c.account = cur.account AND c.symbol = cur.symbol
         ORDER BY cur.broker, cur.underlying, cur.strike""").fetchall()
    out = []
    for acct, broker, u, typ, exp, K, cp, qty, px, n_open, n_close in rows:
        reported_price = reported.get((acct,broker,u,exp,float(K),cp))
        if reported_price is not None:
            px = reported_price
        # A BLENDED ENTRY IS NOT A WRONG ONE, BUT IT IS NOT NECESSARILY RIGHT EITHER. The
        # average spans every OPEN fill for the symbol, so a position opened, closed and
        # RE-opened -- a roll, or a new idea in the same contract -- averages two distinct
        # entry episodes into a price that was never paid for the holding that exists. The
        # BROKER check compares holdings, not costs, so nothing else would catch it. Named
        # rather than silently averaged.
        if n_open and n_close and reported_price is None:
            print(f"note: {u} {K:g}{cp} {exp}: {n_open} open and {n_close} close fill(s) — "
                  f"the entry blends episodes; check it against the broker's average")
        if px is None:
            px = entry.get((acct, u, str(exp), float(K), cp))
        if px is None:
            print(f"WARN: {u} {K:g}{cp} {exp}: no opening fill and no entry on file — "
                  f"this leg's P&L is unmeasurable")
            px = 0.0
        out.append((acct, broker, u, typ, str(exp), float(K), cp, int(qty), float(px)))
    return out
