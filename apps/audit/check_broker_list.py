"""check_broker_list.py — the built book against what the BROKERS say is held.

THE BUG THAT STARTED 2026-10-06, and the only check that could have caught it on sight.
Every number in this repo comes from `positions`, our BUILT book -- but the broker is the
authority on what is held, and the two are kept apart on purpose (fetch_tws_ibkr.py:
overwriting one with the other "would destroy the ability to see them disagree -- which is
the entire point of capturing it"). That morning they disagreed by a whole roll: the book
still held the EWZ Nov-20 32P, the SWKS strangle and six ETFs, while both brokers reported
the put rolled to Dec-18, SWKS closed and the ETFs sold. Every greek, every scenario and
the spot refresh itself -- which picks its tickers FROM this table -- described a
portfolio the user no longer had.

WHEN THE COMPARISON IS VALID. Not "the list must be newer than the book": a book REBUILT
from that very list is minutes newer than it, so that rule skipped both brokers on a
15-leg book facing a 7-leg list and reported nothing. A broker list stays authoritative
until something is TRADED, so the test is whether any fill landed after it.
"""
import datetime as dt

import duckdb
from apps.audit.broker_keys import option_key


def superseded(con, broker, as_of):
    """Did anything trade after this broker list was captured?

    If not, the list still describes the holdings and the comparison is valid however
    old the file is. If something did, the list cannot witness the book and comparing
    against it would fail on the staleness of the EVIDENCE rather than of the book.
    """
    try:
        row = con.execute("SELECT max(ts_utc) FROM fills WHERE broker = ?", [broker]).fetchone()
    except duckdb.Error:
        return True          # no fills table means no way to tell -- fail closed
    return bool(row and row[0] and row[0] > as_of)


def check(con, book, add):
    """The built book must agree with what the BROKERS say is held.

    THE BUG THAT STARTED 2026-10-06, and the only check here that could have caught it on
    sight. Every number in this repo comes from `positions`, our BUILT book -- but the
    broker is the authority on what is actually held, and the two are kept apart on purpose
    (see fetch_tws_ibkr.py: overwriting one with the other "would destroy the ability to see
    them disagree -- which is the entire point of capturing it"). That morning they
    disagreed by a whole roll: `positions` still held the EWZ Nov-20 32P, the SWKS strangle
    and six ETFs, while both brokers reported the put rolled to Dec-18, SWKS closed and the
    ETFs sold. Every greek, every scenario, and the spot refresh itself -- which chooses its
    tickers FROM this table -- described a portfolio the user no longer had.

    Compared only where the broker list is at least as new as the book. An import that
    predates the build cannot witness what the book should contain, and failing on that
    would be failing on the staleness of the EVIDENCE rather than of the book.
    """
    try:
        latest = dict(con.execute(
            "SELECT broker, max(as_of) FROM broker_positions GROUP BY 1").fetchall())
    except duckdb.Error as e:
        add("BROKER", "built book agrees with the broker's list", False, repr(e)[:70], warn=True)
        return
    if not latest:
        add("BROKER", "built book agrees with the broker's list", False,
            "no broker_positions captured — nothing to compare", warn=True)
        return

    vint = max((r[18] for r in book if r[18]), default=None)
    checked, stale_ev = [], []
    for broker, as_of in sorted(latest.items()):
        if vint and as_of < vint - dt.timedelta(minutes=1) and superseded(con, broker, as_of):
            stale_ev.append(f"{broker} {as_of:%m-%d %H:%M} < book {vint:%m-%d %H:%M}")
            continue
        rows = con.execute("""
            SELECT underlying, expiry, strike, call_put, qty FROM broker_positions
            WHERE broker = ? AND as_of = ?""", [broker, as_of]).fetchall()
        said = {option_key(broker,u,e,k,c): q for u,e,k,c,q in rows}
        ours = {option_key(broker,r[1],r[3],r[4],r[5]): r[6] for r in book if r[0] == broker}
        missing = sorted(f"{u} {k:g}{c} (broker {q:+g}, book absent)"
                         for (u, e, k, c), q in said.items() if (u, e, k, c) not in ours)
        extra = sorted(f"{u} {k:g}{c} (book {q:+g}, broker absent)"
                       for (u, e, k, c), q in ours.items() if (u, e, k, c) not in said)
        off = sorted(f"{u} {k:g}{c} broker {said[(u, e, k, c)]:+g} vs book {ours[(u, e, k, c)]:+g}"
                     for (u, e, k, c) in said.keys() & ours.keys()
                     if said[(u, e, k, c)] != ours[(u, e, k, c)])
        bad = missing + extra + off
        add("BROKER", f"{broker}: book == broker's own list", not bad,
            f"{len(said)} legs agree" if not bad else "; ".join(bad[:4]))
        checked.append(broker)

    if stale_ev and len(stale_ev) == len(latest):
        add("BROKER", "broker list is fresh enough to compare", False,
            "; ".join(stale_ev) + " — re-import the broker statements", warn=True)
