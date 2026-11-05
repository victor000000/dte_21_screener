"""stock_row.py — the STOCK branch of the book build, extracted.

A stock's mark IS its spot: no chain, no IV, no repricing, which is why the row
looks nothing like an option's and why it is worth keeping apart from one. It
moved out of `build_positions` because `mark_source` took that file past its
size ratchet, and this was the one seam in the loop that is genuinely
self-contained -- it reads a spot, writes a row, and returns nothing the rest of
the loop needs.

`spot_for` and `spot_meta` are PASSED IN, not imported. `build_positions` owns
those caches and they exist to stop the same underlying being fetched twice per
build; importing them here would give this module its own copy and silently
double every request. They are the caller's, so the caller hands them over.
"""


def insert(con, acct, broker, u, qty, avg, spot_for, spot_meta, sector):
    """Write one stock leg. Returns the spot used, or None if the leg was skipped.

    A None return means the caller must NOT count the row: `spot_for` giving
    nothing and `avg` giving nothing is a leg with no price at all, and writing
    a NULL spot would put it in the book as a position with zero risk.
    """
    # `float('nan') or avg` returns nan -- bool(nan) is True -- so a halted or
    # delisted ticker wrote NaN into spot/mark/delta_notional_usd and then
    # poisoned the whole scenario ladder. Test for NaN explicitly.
    _s = spot_for(con, u)
    spot = _s if (_s == _s and _s) else avg
    if not spot:
        return None
    sm = spot_meta(u)
    con.execute(
        """INSERT INTO positions (account,broker,underlying,sec_type,expiry,strike,call_put,qty,avg_price,spot,multiplier,mark,delta_units,gamma_units,theta_day,vega_pt,delta_notional_usd,asset_class,sector,industry,subindustry,spot_source,spot_class,spot_is_realtime,mark_obs,mark_source,bid,ask) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [acct, broker, u, "STOCK", None, None, None, qty, avg, spot, 1.0, spot,
         float(qty), 0.0, 0.0, 0.0, qty * spot, *sector.get(u, ("?", "?", "?", "?")),
         sm['source'], sm['quote_class'], sm['is_realtime'],
         spot, 'spot', None, None])   # a stock's mark IS its spot; no spread taken
    return spot
