"""broker_quotes.py — see the package docstring."""
import bootstrap
from datasources import tws
from datasources import ibmarks

def get_real_option_quotes(con, positions):
    """Live option marks from the broker, keyed the way the leg loop reads them.

    This was a stub that returned {} from the day it was written, so `mark_source` was
    never once 'broker_quote' and EVERY option price in every risk profile was a
    Black-Scholes estimate. The reports printed those beside real underlying prices
    without distinguishing them, which is how an estimate came to be read as a quote --
    and why the estimate column and the model column were identical down the whole table.

    Prefers the bid/ask mid, the only two-sided number here; then last; then close.
    Outside regular hours an illiquid option frequently has nothing but a close, and
    that is still the exchange's own print rather than a model output, so it is used --
    with the field it came from carried through, because "mark from a close" and "mark
    from a live two-sided market" are different strengths of evidence.
    """
    legs = [(p[0], p[9], float(p[1]), p[2]) for p in positions if p[9] and p[1] and p[2]]
    if not legs:
        return {}
    try:
        from datasources import tws
        marks = tws.option_marks(legs)
    except Exception as e:
        print(f"  !! live option quotes unavailable ({repr(e)[:70]}) — every option "
              f"mark below is a MODEL ESTIMATE, not a market price")
        return {}
    # option_key must match the loop's f"{underlying}_{strike}_{call_put}_{expiry}".
    # Built from the leg spec we already hold rather than re-derived from the quote,
    # so the two cannot drift apart on a float-vs-int strike or a date format.
    key_of = {(u, e, float(k), cp): f"{u}_{k}_{cp}_{e}" for u, e, k, cp in legs}
    out, by_field = {}, {}
    for key, q in marks.items():
        for field in ("mid", "last", "close"):
            if q.get(field):
                out[key_of[key]] = {"mark": q[field], "field": field}
                by_field[field] = by_field.get(field, 0) + 1
                break
    if by_field:
        print(f"  live option quotes: " + ", ".join(
            f"{n} from {f}" for f, n in sorted(by_field.items(), key=lambda x: -x[1])))
    return out
