"""broker_marks.py — live option quotes from the broker, for the book builder.

WHY THIS EXISTS. `build_positions` priced every option leg off yfinance's chain,
and yfinance publishes NO option book: measured during the session on 2026-10-06,
bid and ask were 0.0 for every held strike while `lastPrice` still carried the
previous close. So the book was built from a stale observation, repriced at the
live spot, and the report said so -- honestly, and wrongly: the broker had a real
two-sided market the whole time. CRWD's Nov-20 220P was marked 2.82 from Monday
while TWS quoted 2.03/2.29, a 23% difference on the leg the 50% rule is read off.

`datasources.tws.option_marks` already had the fetching pattern; `complete_risk`
used it and this path did not. This is the wiring, kept in its own module so
`build_positions` -- already long, and baselined by the size ratchet -- grows by
an import rather than by twenty lines.

NEVER FATAL. Every failure returns an empty mapping: the gateway is down, the
contract does not qualify, the market is closed and IB returns its -1 sentinel.
A leg with no broker quote falls through to the existing chain/snapshot/fill
ladder, which is a worse price but not a broken run. Callers must not treat an
empty result as "no position".
"""
import datetime as dt


def tws_option_marks(legs, client_id=147):
    """{(underlying, expiry, strike, call_put): mid} for legs with a real book.

    A quote counts only with BOTH sides and ask >= bid: IB leaves NaN or -1 where
    it has no value, and `ibmarks.clean` has already mapped those to None. A
    crossed or one-sided book is a data fault, not a price.
    """
    if not legs:
        return {}
    # The book stores the expiry as a string ('2026-11-20'); option_marks wants a
    # date and calls strftime on it. Passing the string through raised
    # AttributeError('str' object has no attribute 'strftime') -- swallowed by the
    # except below and reported as "no broker quotes", which is exactly the kind
    # of quiet degradation this module's docstring promises not to do. Hence the
    # conversion here and the explicit note.
    norm = [(u, dt.date.fromisoformat(e) if isinstance(e, str) else e, k, cp)
            for u, e, k, cp in legs]
    try:
        from datasources import tws
        raw = tws.option_marks(norm, client_id=client_id)
    except Exception as e:
        print(f"  note: no broker option quotes this run ({repr(e)[:70]})")
        return {}

    out = {}
    for key, q in raw.items():
        if not isinstance(key, tuple) or len(key) != 4:
            continue
        bid, ask = q.get("bid"), q.get("ask")
        if bid and ask and ask >= bid > 0:
            out[key] = (bid + ask) / 2
    return out


def for_book(us_rows, client_id=147):
    """One broker round trip for a whole book, announcing its own coverage.

    Kept here rather than in build_positions so that file grows by an import and a
    call instead of by the block -- it is already over the size limit and every
    line added to it has to be argued for.
    """
    legs = [(u, exp, k, cp) for _, _, u, typ, exp, k, cp, _, _ in us_rows if typ == "OPT"]
    if not legs:
        return {}
    got = tws_option_marks(legs, client_id=client_id)
    # COUNT CONTRACTS FOR THE DENOMINATOR, LEGS FOR THE NUMERATOR. Two brokers can hold
    # the same contract -- CRWD's Nov-20 230P and 330C each sit at IBKR and at Schwab --
    # and `tws_option_marks` keys on the full contract, so the duplicate
    # collapses. Printing "11 of 13 legs" therefore read as "two legs fell back to the
    # chain ladder" when every row was priced off the live book and only the COUNT
    # differed. The number a reader needs is how many LEGS got a live quote.
    unique = set(legs)
    # Match the full contract; the same strike in another month is a different quote.
    covered = sum(1 for u, e, k, cp in legs
                  if (u, dt.date.fromisoformat(e) if isinstance(e, str) else e, k, cp) in got)
    print(f"  broker option quotes: {covered} of {len(legs)} legs "
          f"({len(got)} of {len(unique)} contracts) have a live two-sided book"
          + ("" if got else " — falling back to the chain ladder"))
    return got
