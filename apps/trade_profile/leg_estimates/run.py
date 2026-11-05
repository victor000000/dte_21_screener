"""run.py — the orchestration: connect, collect, persist, render."""
import argparse

import bootstrap   # the package __init__ put the repo root on sys.path
from compute import bs
from data import db

from .collect import collect
from .persist import save
from .report import console, markdown


def rt_moves_for(con, rows):
    """Each underlying's move since the last stored daily close, in percent.

    Read from `positions.spot` against market_history, so it is the same live spot
    the estimate was priced at -- a second source here would make the narrative
    disagree with the table above it.
    """
    rt_moves = {}
    for u in {r["underlying"] for r in rows}:
        r = con.execute("""SELECT p.spot, d.close FROM positions p
                           LEFT JOIN (SELECT symbol, close, row_number() OVER
                                      (PARTITION BY symbol ORDER BY day DESC) rn
                                      FROM mh.underlying_daily WHERE close > 0) d
                             ON d.symbol = p.underlying AND d.rn = 1
                           WHERE p.underlying = ? AND p.qty <> 0 LIMIT 1""", [u]).fetchone()
        if r and r[0] and r[1]:
            rt_moves[u] = (r[0] / r[1] - 1) * 100
    return rt_moves


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None)
    args = ap.parse_args(argv)

    assert bs.USING_QUANTLIB, (
        "the estimate is defined as the native QuantLib price; the pure-Python fallback "
        "is a different model and would make these numbers a third thing")
    con = db.connect(log="rw", history="ro")   # rw: this run is persisted
    rows = collect(con, args.account)
    if not rows:
        print("no positions")
        return
    rt_moves = rt_moves_for(con, rows)
    run_ts = con.execute("SELECT CAST(current_timestamp AT TIME ZONE 'UTC' AS TIMESTAMP)").fetchone()[0]
    save(con, rows, run_ts)
    con.close()

    path = markdown(rows, rt_moves, bootstrap.ROOT)
    console(rows, rt_moves)
    print(f"\nsaved {len(rows)} legs to trades.leg_estimates (run_ts {run_ts})\nwritten: {path}")
