"""persist.py — the leg_estimates table, write-only by design.

The schema is a contract: `apps/audit/risk_profile_check.py` reads this table
(underlying, strike, call_put, mark, est_price, keyed on max(run_ts)) to
cross-check the independent estimate path against `positions`. Column names and
order are load-bearing.
"""
from .constants import HARVEST


def save(con, rows, run_ts):
    """Persist the run. Keyed, so selfcheck's 'every table has a key' holds."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS leg_estimates (
            run_ts TIMESTAMP NOT NULL, account TEXT NOT NULL, underlying TEXT NOT NULL,
            leg_key TEXT NOT NULL, broker TEXT, expiry DATE, strike DOUBLE, call_put TEXT,
            sec_type TEXT, qty INTEGER, entry_price DOUBLE, mark DOUBLE, est_price DOUBLE,
            est_iv DOUBLE, mark_spot DOUBLE, rt_spot DOUBLE, pnl_pct_mark DOUBLE,
            pnl_pct_est DOUBLE, target_50 DOUBLE, reached_50 BOOLEAN,
            PRIMARY KEY (run_ts, account, underlying, leg_key))""")
    # The guard is HERE, in the same function and above the call, because
    # scripts/check_regressions.py walks outward from an executemany and stops at the
    # nearest enclosing FunctionDef -- a caller-side `if not rows: return` would not be
    # seen, and the gate would fail on code with identical behaviour.
    if rows:   # DuckDB raises on an empty list, not a no-op
        con.executemany("""INSERT INTO leg_estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [[run_ts, r["account"], r["underlying"], r["leg"], r["broker"], r["expiry"],
                          r["strike"], r["call_put"], r["sec_type"], r["qty"], r["entry"], r["mark"],
                          r["est"], r["iv"], r["est_mark_spot"], r["rt_spot"], r["pnl_mark"],
                          r["pnl_est"], r["target_50"], r["pnl_est"] >= HARVEST] for r in rows])
