"""quotes.py — see the package docstring."""
import bootstrap

def get_latest_price(con, ticker):
    """Most recent REAL-TIME extended hours price, or None.

    Only rows the fetcher flagged is_realtime are eligible. A last-trade with no
    book (Futu's copy of the RTH close) is not a live price, and using one as
    the live spot is what made every ticker report a 0.00% move -- the live
    profile was silently identical to the snapshot.

    Among real-time rows, higher-quality sources win: a two-sided TWS quote
    before Alpaca before yfinance. The fetch step already rejects quotes that
    disagree with the cross-source consensus, so this is ordering, not filtering.

    Returns (None, None, None, None) when the ticker has no live quote; callers
    fall back to the snapshot spot and should label it as such.
    """
    result = con.execute("""
        SELECT mid, last, timestamp_utc, session_type, source
        FROM extended_hours_quotes
        WHERE ticker = ?
          AND is_realtime
          AND timestamp_utc >= CAST(current_timestamp AT TIME ZONE 'UTC' AS TIMESTAMP) - INTERVAL '1 hour'
        ORDER BY
            CASE source
                WHEN 'TWS' THEN 1
                WHEN 'Alpaca' THEN 2
                WHEN 'ThetaData' THEN 3
                WHEN 'yfinance' THEN 4
                ELSE 5
            END,
            timestamp_utc DESC
        LIMIT 1
    """, [ticker]).fetchone()

    if not result:
        return None, None, None, None

    mid, last, ts, session, source = result
    price = mid if mid else last
    return price, ts, session, source
