"""close_cost.py — what each short leg would cost to buy back, against the mid.

WHY THIS EXISTS. Every P&L in the profile is measured at the MID. The mid is the right
MARK -- it is what the market is quoted at -- but the wrong number to read as profit: you
BUY a short back, so closing costs the ASK. On a tight market the two are cents apart; on
a wide one it is the whole decision. Measured 2026-10-06: CRWD's Dec-18 225P, the leg the
profile called the position worth holding all session, sat in a 5.90/7.40 market around a
6.65 mid -- up $2,492 on paper, $1,742 realisable.

This is the defect the repo fixed once already: `mark_obs` exists because "what did this
trade at" and "what is it worth now" were being answered by one number. "What is it worth
on paper" and "what would closing cost" are the same kind of pair.

A SEPARATE SECTION, not an extra column: `risk_profile_check` parses the leg table by
position, and the plan is explicit that the table's shape is an API both sides move
together. A new heading cannot break a parser that anchors on headings.
"""

#: Spreads below this are noise: the mid is within a rounding of what closing realises.
MATERIAL_PCT = 5.0


def _row(name, qty, bid, mid, ask, entry, mult, fx):
    """Everything the table prints for one short leg.

    TWO DIFFERENT PERCENTAGES, and conflating them is easy. `bid_ask_pct` is the
    conventional spread, ask minus bid over the mid -- 22.6% on CRWD's Dec-18 225P.
    `cross_pct` is what it costs to go from the MID to the ASK, which is half of that and
    is the number that belongs beside a P&L measured at the mid.
    """
    at_mid = (entry - mid) * abs(qty) * mult / fx
    at_ask = (entry - ask) * abs(qty) * mult / fx
    return {"name": name, "bid": bid, "mid": mid, "ask": ask,
            "bid_ask_pct": (ask - bid) / mid * 100, "cross_pct": (ask - mid) / mid * 100,
            "at_mid": at_mid, "at_ask": at_ask}


def build(legs, material_pct=MATERIAL_PCT):
    """Markdown lines for the close-cost table, or [] when no leg has a quote.

    `legs` is (name, qty, bid, mid, ask, entry, mult, fx) for SHORT option legs with a
    stored two-sided quote. Legs whose spread is under `material_pct` are left out:
    listing 0.1% spreads beside 22% ones teaches the reader to skip the table.
    """
    rows = []
    for name, qty, bid, mid, ask, entry, mult, fx in legs:
        if qty >= 0 or not bid or not mid or not ask or not entry:
            continue
        rows.append(_row(name, qty, bid, mid, ask, entry, mult, fx))
    rows = [r for r in rows if r["bid_ask_pct"] >= material_pct]
    if not rows:
        return []
    rows.sort(key=lambda r: -r["bid_ask_pct"])
    out = ["\n### Close cost vs mark",
           "*Every P&L above is measured at the **mid**. You buy a short back at the "
           "**ask**, so on a wide market the mid overstates what closing realises — the "
           f"gap is what the spread costs. Legs under {material_pct:.0f}% wide are not "
           "listed.*\n",
           "| Short leg | Bid | Mid | Ask | Bid-ask | Mid→ask | P&L @ mid | P&L @ ask "
           "| Give-up |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['bid']:.3f} | {r['mid']:.3f} | {r['ask']:.3f} | "
                   f"{r['bid_ask_pct']:.1f}% | {r['cross_pct']:.1f}% | {r['at_mid']:,.0f} | "
                   f"{r['at_ask']:,.0f} | {r['at_mid'] - r['at_ask']:,.0f} |")
    return out


#: Indices into the `positions` row `risk_profile` reads -- the same tuple `agg` indexes.
#: Named because a bare r[26] gives no hint what it is, and the LAST TWO were appended to
#: a 25-column SELECT: reading one position too early is how `mark_source` was once read
#: as `mark_obs` and the header announced "no option mark is a live quote" for a book of
#: live quotes.
COL = {"broker": 0, "underlying": 1, "sec_type": 2, "strike": 3, "call_put": 4, "qty": 5,
       "multiplier": 20, "expiry": 21, "mark": 22, "avg_price": 19, "bid": 25, "ask": 26}


def from_rows(pos, fx_of, cols=COL):
    """The section for a query's result set, or [] when nothing is quoted.

    `cols` IS A PARAMETER because the two callers read different result sets:
    `risk_profile`'s SELECT and `risk_profile_check.load_book`'s are different orders, and
    a single hardcoded map read one file's `expiry` out of the other's tuple -- a string
    where a date belonged, which surfaced as "Invalid format specifier '%m-%d' for object
    of type 'str'" rather than as a wrong number. Both callers name their own map.
    """
    legs = []
    for r in pos:
        if r[cols["sec_type"]] != "OPT":
            continue
        exp = r[cols["expiry"]]
        name = (f"{r[cols['underlying']]} {exp:%m-%d} " if exp else
                f"{r[cols['underlying']]} ") + f"{r[cols['strike']]:g}{r[cols['call_put']]}"
        legs.append((name, r[cols["qty"]], r[cols["bid"]] or 0, r[cols["mark"]] or 0,
                     r[cols["ask"]] or 0, r[cols["avg_price"]] or 0,
                     r[cols["multiplier"]] or 100, fx_of(r[cols["broker"]])))
    return build(legs)
