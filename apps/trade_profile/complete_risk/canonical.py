"""canonical.py — see the package docstring."""
import datetime as dt
import bootstrap

def canonical_snapshot_spots(underlyings, theta_closes=None):
    """Last COMPLETED regular-session close per underlying, fetched once.

    Why this is not just `positions.spot`. Those rows are written by independent
    per-leg fetches, and a fetch that runs during extended hours returns the
    price *now* -- so a live overnight print gets stored as a "close" and mixed
    in with genuine ones. On 2026-10-05 that left EWZ with two different
    snapshot spots in the same table: 38.19 (the real 10-02 close) on the 32P
    and 37.32 (an overnight print) on the 43C. Both legs describe one
    underlying, so the two could not both be right, and the reported overnight
    move differed depending on which leg you read.

    Daily bars before today's ET date are completed. Today's bar is eligible
    only after the vendor's dated regular-session end, including early closes.
    Without that metadata, use the previous session conservatively.
    """
    import yfinance as yf
    import pytz

    now_et = dt.datetime.now(pytz.timezone('US/Eastern'))
    today_et = now_et.date()
    # ThetaData EOD wins where present: it is a vendor session close keyed to a
    # date, not a scraped last-print that may be intraday.
    spots = dict(theta_closes or {})
    for u in underlyings:
        if u in spots:
            continue
        try:
            ticker = yf.Ticker(u)
            h = ticker.history(period='5d', auto_adjust=False)
            if h.empty:
                continue
            end = (ticker.history_metadata or {}).get('currentTradingPeriod', {}).get('regular', {}).get('end')
            end_et = dt.datetime.fromtimestamp(end, now_et.tzinfo) if end else None
            today_complete = bool(end_et and end_et.date() == today_et and now_et >= end_et)
            past = [(idx.date(), float(c)) for idx, c in zip(h.index, h['Close'])
                    if hasattr(idx, 'date') and (idx.date() < today_et or (today_complete and idx.date() == today_et)) and c == c]
            if past:
                spots[u] = past[-1][1]
        except Exception as e:
            print(f"  last-close fetch failed for {u}: {repr(e)[:80]}")
    return spots
