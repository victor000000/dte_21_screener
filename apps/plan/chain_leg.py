"""chain_leg.py — one option's price from yfinance's chain, for the book builder.

The last tier of the pricing ladder: `broker_marks` asks the broker first, and when it
has no two-sided book this is what answers. Returns `(price, iv, is_book)` where
`is_book` says whether the price is an OBSERVATION (a live two-sided mid) or a stale
last trade the caller must reprice at the live spot.

Extracted from `build_positions`, which had reached its size ceiling for the fourth time
and whose own plan says it should be split. The chain cache moved with the function that
is its only user, so it stays a process-lifetime singleton -- one `option_chain` call per
underlying per build, which is what it is for.

WHY THE `impliedVolatility` FIELD IS MOSTLY IGNORED. See the last branch: the caller
solves the vol from the mid, and this only supplies yfinance's number for a mid that will
not solve at all. Taking it as the answer is what made 39 of the book's 52 greeks stop
reproducing on 2026-10-06.

`is_book` is the whole contract of this module: a caller that treats a last-session price
as current values the book off the previous close.

THE FOURTH ELEMENT IS THE QUOTE ITSELF, `(bid, ask)`, or None when there is no book. The
mid alone is not enough to report a P&L: you BUY a short back at the ASK, so on a wide
market the mid overstates what closing realises. Measured 2026-10-06: CRWD's Dec-18 225P
sat at a 6.65 mid inside a 5.90/7.40 market -- 22.6% wide -- and was up $2,492 on paper
against $1,742 actually realisable. The mid is still the right MARK (it is what the
market is quoted at); it is the wrong number to read as profit without the spread beside
it.
"""
import yfinance as yf

_chain_cache = {}


def yf_leg(u, exp, K, cp):
    key = (u, exp)
    if key not in _chain_cache:
        try:
            _chain_cache[key] = yf.Ticker(u).option_chain(exp)
        except Exception as e:
            print(f"yf chain fail {u}: {repr(e)[:100]}")
            _chain_cache[key] = None
    ch = _chain_cache[key]
    if ch is None:
        return None
    df = ch.calls if cp == "C" else ch.puts
    r = df[df["strike"] == K]
    if r.empty:
        return None
    r = r.iloc[0]
    bid, ask, iv = float(r["bid"]), float(r["ask"]), float(r["impliedVolatility"])
    # BOTH SIDES OR IT IS NOT A BOOK. `bid or ask` accepted a lone side as a live mid, so
    # `bid=2.0, ask=0.0` came back as an OBSERVATION and the caller quoted it as current --
    # while `broker_marks` refuses exactly that shape ("a crossed or one-sided book is a
    # data fault, not a price"). Two mark sources feeding one book cannot hold two rules:
    # the broker rejects a one-sided quote, this falls to it second, and accepting it here
    # would undo the broker's own decision. A zero on one side of an option is a missing
    # field far more often than a real one-sided market, and the caller re-prices a last
    # trade at the live spot, which is a defensible mark; a lone bid is not a market.
    mid = (bid + ask) / 2 if (bid and ask and ask >= bid) else None
    # yfinance leaves impliedVolatility NaN (or 0) when it has no view. NaN is truthy, so it
    # passes `if leg and spot` and every downstream check, and turns delta/gamma/theta into
    # NaN -- which then poisons the scenario ladder exactly as a NaN spot would. Return it
    # as None rather than rejecting the row: the caller can solve the IV from the PRICE,
    # which is the number yfinance is actually reliable on. It reported 0.001 for the very
    # 43C below that the broker marked at 38.9%.
    if iv != iv or iv <= 0:
        iv = None
    if mid is None or mid != mid:
        # NO BOOK. Outside regular hours that is the normal state, not an error: measured
        # 2026-10-06 08:30 UTC, 0 of EWZ's 34 Nov-20 calls had a two-sided quote. But
        # lastPrice still carries the previous session's CLOSE -- EWZ Nov-20 43C 2.38
        # against the broker's own 2.35, TLT Nov-20 82C 0.30 against 0.31 -- and that is a
        # full session NEWER than anything in chain_snapshots. The snapshots are written
        # pre-market, so a snapshot observed Monday 07:15 UTC holds FRIDAY's close; on
        # 2026-10-06 the book was being priced off Friday, before EWZ moved 12%, which
        # valued an at-the-money call off a deep-in-the-money one (43C: mark 1.155, IV
        # 17.5%, against a real 2.38 at 38.9%). Preferring a real trade from the latest
        # session to a stale snapshot is not a trade-off: it is newer in every case.
        last = float(r["lastPrice"]) if "lastPrice" in df.columns else 0.0
        if last and last == last and last > 0:
            # Third element False: this is a LAST-SESSION mark, not a live book, so the
            # caller must estimate it at the live spot rather than quote it as current.
            return last, None, False, None
        return None
    return mid, iv, True, (bid, ask)
