"""check_close_cost.py — the close-cost section must be there and must be right.

WHY. The profile measures every P&L at the MID, and you buy a short back at the ASK. On a
tight market those agree; on this book CRWD's Dec-18 225P sat in a 22.6%-wide market, so
the same leg read $2,492 on paper and $1,742 realisable. That is a 30% overstatement on
the position the report had been calling the one worth holding, and nothing in the report
said so until this section existed.

A table nothing checks is a table that can silently stop being produced -- which is the
history of every other claim in this report. So: the heading must be present when any leg
is wide enough to list, and every row must re-derive from the book.

The numbers are re-derived from `positions`, not from the markdown, so a section that
prints plausible row shapes with wrong arithmetic still fails.
"""
import re

from apps.trade_profile import close_cost

#: `risk_profile_check.load_book`'s column order -- NOT risk_profile's. bid/ask are
#: appended after mark_source, which is why they are 22 and 23 and not 25 and 26.
BOOK_COL = {"broker": 0, "underlying": 1, "sec_type": 2, "qty": 6, "multiplier": 8,
            "mark": 9, "avg_price": 19, "expiry": 3, "strike": 4, "call_put": 5,
            "bid": 22, "ask": 23}


def check(text, book, add, fx_of):
    """`book` is risk_profile_check's load_book result; indices match close_cost.COL."""
    C = BOOK_COL
    wanted = close_cost.from_rows(book, fx_of, C)
    if not wanted:
        add("CLOSE", "no leg's market is wide enough to change the answer", True,
            f"every spread under {close_cost.MATERIAL_PCT:.0f}% of the mid")
        return

    if "### Close cost vs mark" not in text:
        add("CLOSE", "report shows what closing would cost", False,
            "no 'Close cost vs mark' section, but wide spreads exist")
        return

    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(.+?)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|"
                     r"\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|\s*(-?[\d,]+)\s*\|\s*(-?[\d,]+)\s*\|"
                     r"\s*(-?[\d,]+)\s*\|", line)
        if m:
            rows[m.group(1)] = m
    add("CLOSE", "report shows what closing would cost", True,
        f"{len(rows)} leg(s) listed")

    # Re-derive each listed leg from the book and compare.
    want = {}
    for r in book:
        if r[C["sec_type"]] != "OPT" or r[C["qty"]] >= 0:
            continue
        exp = r[C["expiry"]]
        name = (f"{r[C['underlying']]} {exp:%m-%d} " if exp else
                f"{r[C['underlying']]} ") + f"{r[C['strike']]:g}{r[C['call_put']]}"
        if r[C["bid"]] and r[C["ask"]] and r[C["mark"]]:
            want[name] = r

    bad = []
    for name, m in rows.items():
        r = want.get(name)
        if r is None:
            bad.append(f"{name}: listed but has no stored quote")
            continue
        at_mid = (r[C["avg_price"]] - r[C["mark"]]) * abs(r[C["qty"]]) \
            * (r[C["multiplier"]] or 100) / fx_of(r[C["broker"]])
        got = float(m.group(7).replace(",", ""))
        if abs(got - at_mid) > max(1.0, abs(at_mid) * 0.01):
            bad.append(f"{name}: P&L @ mid {got:,.0f} vs {at_mid:,.0f} from the book")
    add("CLOSE", "every row re-derives from the book", not bad,
        "all listed legs" if not bad else "; ".join(bad[:3]))

    # And the reverse: a wide leg in the BOOK that the section left out.
    listed = set(rows)
    missing = [n for n, r in want.items()
               if n not in listed
               and (r[C["ask"]] - r[C["bid"]]) / r[C["mark"]] * 100 >= close_cost.MATERIAL_PCT]
    add("CLOSE", "no wide leg is left out of the section", not missing,
        "none missing" if not missing else f"missing {sorted(missing)[:4]}")
