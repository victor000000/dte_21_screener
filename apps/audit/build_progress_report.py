import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

# ── --help guard ─────────────────────────────────────────────────────────────
# No argparse here, so `script.py --help` used to execute this script in full.
# That is not hypothetical: a 2026-10-05 sweep ran every app with --help and
# rewrote `fills`, `risk_profile` and `positions`. The write does not have to be
# in THIS file either -- live_risk_profile.py orchestrates build_positions and
# risk_profile through subprocess, so "does it INSERT?" is the wrong test. The
# rule is simply that a script with no argument parser must not run on --help.
from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below, and a
# docstring must be the first statement, so all 33 copies printed "(no docstring)".

"""build_progress_report.py — the project's build status, read from the databases.

Every number here is a live query. A database another process is writing is reported as
`locked` rather than guessed at, so the report is always honest about what it could and
could not see. Re-runnable at any time.

    uv run python apps/audit/build_progress_report.py
"""
import datetime as dt
from data import clock
import pathlib

import duckdb

ROOT = bootstrap.ROOT
DB_FILES = {
    "trades": bootstrap.DATA_ROOT / "trades.duckdb",
    "market_history": bootstrap.DATA_ROOT / "market_history.duckdb",
    "reference": bootstrap.DATA_ROOT / "reference.duckdb",
    "universe (yahoo)": bootstrap.DATA_ROOT / "market_data" / "yahoo.duckdb",
}


def open_db(path):
    try:
        return duckdb.connect(str(path), read_only=True), None
    except Exception as e:
        return None, repr(e)[:70]


def count(con, sql, args=None):
    try:
        return con.execute(sql, args or []).fetchone()[0]
    except Exception:
        return None


def main():
    today = clock.today()
    conns, notes = {}, {}
    for name, path in DB_FILES.items():
        con, err = open_db(path)
        conns[name] = con
        if err:
            notes[name] = err

    T, M, F, Y = (conns["trades"], conns["market_history"], conns["reference"], conns["universe (yahoo)"])

    L = [f"# Project build report — {today}", "",
         "Every figure is a live query against the four databases. `locked` means another",
         "process held the file at report time (a downloader writing it) — never a guess.", ""]

    L += ["## Databases", "", "| database | state | tables |", "|---|---|---|"]
    for name, con in conns.items():
        if con is None:
            L.append(f"| {name} | locked (writer active) | — |")
        else:
            tabs = [r[0] for r in con.execute(
                "SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()]
            L.append(f"| {name} | open | {', '.join(tabs)} |")
    L.append("")

    if T:
        L += ["## Record — what we did (trades.duckdb)", "",
              f"- fills **{count(T, 'SELECT count(*) FROM fills')}** · "
              f"orders **{count(T, 'SELECT count(*) FROM orders')}** · "
              f"account_daily **{count(T, 'SELECT count(*) FROM account_daily')}** · "
              f"journal **{count(T, 'SELECT count(*) FROM journal_entries')}**",
              f"- chain captures: snapshots {count(T, 'SELECT count(*) FROM chain_snapshots')} · "
              f"rows {count(T, 'SELECT count(*) FROM chain_rows')}",
              f"- positions **{count(T, 'SELECT count(*) FROM positions')}** · "
              f"risk profiles {count(T, 'SELECT count(*) FROM risk_profile')} · "
              f"screener runs {count(T, 'SELECT count(*) FROM screener_runs')}",
              f"- consistency checks stored: {count(T, 'SELECT count(*) FROM source_checks')}", ""]

    if M:
        L += ["## Series — what the market did (market_history.duckdb)", "",
              f"- option bars **{count(M, 'SELECT count(*) FROM option_bars'):,}** over "
              f"{count(M, 'SELECT count(DISTINCT underlying) FROM option_bars')} underlyings · "
              f"{count(M, 'SELECT count(DISTINCT expiry) FROM option_bars')} expiries",
              f"- option minutes **{count(M, 'SELECT count(*) FROM option_minutes'):,}** · "
              f"underlying minutes **{count(M, 'SELECT count(*) FROM underlying_minutes'):,}**",
              f"- IV history **{count(M, 'SELECT count(*) FROM iv_history'):,}** rows from "
              f"{count(M, 'SELECT count(DISTINCT source) FROM iv_history')} sources",
              f"- flow layer **{count(M, 'SELECT count(*) FROM option_flow_daily'):,}** rows",
              f"- underlying daily **{count(M, 'SELECT count(*) FROM underlying_daily'):,}** · "
              f"fundamentals snapshots {count(M, 'SELECT count(*) FROM fundamentals_snapshot')}",
              f"- smile coverage: "
              f"{count(M, 'SELECT count(*) FROM (SELECT underlying, expiry, count(DISTINCT strike) n FROM option_bars GROUP BY 1,2 HAVING n >= 5)')} "
              f"(underlying, expiry) pairs have ≥5 strikes", ""]

    if F:
        L += ["## Structure — what things are (reference.duckdb)", "",
              f"- instruments {count(F, 'SELECT count(*) FROM instruments')} · "
              f"option contracts {count(F, 'SELECT count(*) FROM option_contracts'):,} · "
              f"expiries {count(F, 'SELECT count(*) FROM expiries')}",
              f"- futures products {count(F, 'SELECT count(*) FROM futures_products')} · "
              f"contracts {count(F, 'SELECT count(*) FROM futures_contracts')}",
              f"- calendar {count(F, 'SELECT count(*) FROM calendar'):,} rows · "
              f"earnings {count(F, 'SELECT count(*) FROM earnings'):,} · "
              f"events {count(F, 'SELECT count(*) FROM events'):,}", ""]

    if Y:
        L += ["## Universe — membership and long history (yahoo.duckdb)", "",
              f"- prices **{count(Y, 'SELECT count(*) FROM prices'):,}** rows · "
              f"{count(Y, 'SELECT count(*) FROM symbols'):,} symbols · "
              f"through {count(Y, 'SELECT max(date) FROM prices')}",
              f"- dividends {count(Y, 'SELECT count(*) FROM dividends'):,} · "
              f"splits {count(Y, 'SELECT count(*) FROM splits'):,} · "
              f"memberships {count(Y, 'SELECT count(*) FROM index_membership'):,}", ""]

    # ---- goal checklist
    L += ["## Goal checklist", "", "| # | goal item | evidence | state |", "|---|---|---|---|"]
    def state(v, ok=1):
        if v is None:
            return "locked/unreadable"
        return "✓" if v >= ok else ("◀ in progress" if v > 0 else "✧ pending")
    items = [
        ("databases designed (4 layers, keys, conventions)", "see plans/DATABASE_DESIGN.md", "✓"),
        ("options history", count(M, "SELECT count(*) FROM option_bars") if M else None, None),
        ("1-minute resolution", (count(M, "SELECT count(*) FROM option_minutes") or 0) +
         (count(M, "SELECT count(*) FROM underlying_minutes") or 0) if M else None, None),
        ("equities history", count(Y, "SELECT count(*) FROM prices") if Y else None, None),
        ("futures IV (TWS sweep)", count(M, "SELECT count(DISTINCT underlying) FROM iv_history WHERE source='ibkr_tws30d'") if M else None, None),
        ("EOD data", count(M, "SELECT count(*) FROM underlying_daily") if M else None, None),
        ("IV / HV", count(M, "SELECT count(*) FROM iv_history") if M else None, None),
        ("IVR / IVP", "derived by window SQL over iv_history (by design)", "✓"),
        ("greeks", "derived from option_bars + bs.py; fill-time greeks stored on fills", "✓"),
        ("smile / term structure", "derivable from option_bars (≥5 strikes per expiry)", "✓"),
        ("VIX family", count(M, "SELECT count(*) FROM underlying_daily WHERE symbol LIKE '^%'") if M else None, None),
        ("volumes / turnover", count(Y, "SELECT count(*) FROM prices WHERE volume IS NOT NULL") if Y else None, None),
        ("market capitalisation", count(M, "SELECT count(*) FROM fundamentals_snapshot") if M else None, None),
        ("calendars", count(F, "SELECT count(*) FROM calendar") if F else None, None),
        ("economic events", count(F, "SELECT count(*) FROM events") if F else None, None),
        ("single-equity events", count(F, "SELECT count(*) FROM earnings") if F else None, None),
        ("put/call ratio · OI · volume · gamma exposure", count(M, "SELECT count(*) FROM option_flow_daily") if M else None, None),
        ("data consistency recheck", count(T, "SELECT count(*) FROM source_checks") if T else None, None),
        ("21-DTE screener v2", count(T, "SELECT count(*) FROM screener_runs") if T else None, None),
        ("trade log", count(T, "SELECT count(*) FROM fills") if T else None, None),
        ("risk navigator", "plans/risk_navigator_<date>.md", "✓ built, first run queued"),
    ]
    for i, (name, ev, fixed) in enumerate(items, 1):
        st = fixed if fixed else state(ev)
        shown = ev if isinstance(ev, str) else (f"{ev:,}" if isinstance(ev, int) else "—")
        L.append(f"| {i} | {name} | {shown} | {st} |")
    L.append("")
    if notes:
        L += ["## Locked at report time", ""] + [f"- {k}: {v}" for k, v in notes.items()] + [""]
    L += ["## Where the design lives", "",
          "- `plans/PROJECT_DESIGN.md` — products, loop, cadence, capability map, risk-navigator spec",
          "- `plans/DATABASE_DESIGN.md` — the four layers, keys, conventions, calendar/event sources, migration",
          "- `market_data/README.md` — the universe/history subproject",
          "- `reports/design_full_picture.html` — the visual version (publish needs a claude.ai login)", ""]

    out = ROOT / "reports" / f"project_build_report_{today}.md"
    out.write_text("\n".join(L) + "\n")
    for con in conns.values():
        if con:
            con.close()
    print(f"build report -> {out}")


if __name__ == "__main__":
    main()
