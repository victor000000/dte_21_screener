import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""snapshot_positions.py — keep a daily record of the book, not just its current state.

Found by reassessing the design (DATABASE_DESIGN §6b, defect D2): `positions` is overwritten on
every build, so the trade log could not answer "what did the book look like on Sep 25" — a
question a detailed trade log must be able to answer. This writes today's book into
`positions_daily`, idempotently (today's rows are replaced, never appended twice).

Run it after every `build_positions.py`, i.e. at the same points as the plan build.

    uv run python apps/plan/snapshot_positions.py [--day 2026-09-30]
"""
import argparse
import datetime as dt
from data import clock
import pathlib

import duckdb

ROOT = bootstrap.ROOT
DB = bootstrap.DATA_ROOT / "trades.duckdb"

DDL = """
CREATE TABLE IF NOT EXISTS positions_daily (
  day DATE, account TEXT, ckey TEXT,           -- ckey: contract key that tolerates NULLs
  broker TEXT, underlying TEXT, expiry DATE, strike DOUBLE, call_put TEXT,
  qty INTEGER, avg_price DOUBLE, mark DOUBLE, spot DOUBLE,
  delta_units DOUBLE, theta_day DOUBLE, vega_pt DOUBLE,
  unrealized DOUBLE, source TEXT,
  PRIMARY KEY (day, account, ckey)
)"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=clock.today().isoformat(),
                    help="the day this book belongs to (default: today, the process UTC clock)")
    args = ap.parse_args()

    con = duckdb.connect(str(DB))
    con.execute(DDL)
    rows = con.execute("""
        SELECT account,
               underlying || '|' || COALESCE(CAST(expiry AS VARCHAR),'-') || '|' ||
               COALESCE(CAST(strike AS VARCHAR),'-') || '|' || COALESCE(call_put,'-') AS ckey,
               broker, underlying, expiry, strike, call_put, qty, avg_price, mark,
               spot, delta_units, theta_day, vega_pt,
               CASE WHEN qty < 0 THEN (avg_price - mark) * (-qty) * COALESCE(multiplier, 100)
                    ELSE (mark - avg_price) * qty * COALESCE(multiplier, 100) END,
               'snapshot_from_positions'
        FROM positions""").fetchall()
    con.execute("DELETE FROM positions_daily WHERE day=?", [args.day])
    if rows:   # DuckDB raises on an empty list, not a no-op
        con.executemany("INSERT INTO positions_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [[args.day, *r] for r in rows])
    n, upl = con.execute("""SELECT count(*), sum(unrealized) FROM positions_daily WHERE day=?""",
                         [args.day]).fetchone()
    days = con.execute("SELECT count(DISTINCT day) FROM positions_daily").fetchone()[0]
    con.close()
    print(f"positions_daily: {n} legs for {args.day} · unrealized {upl:+,.0f} · "
          f"{days} day(s) now on record")


if __name__ == "__main__":
    main()
