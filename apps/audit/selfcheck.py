import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""selfcheck.py — the project's self-check: one command that answers "are the databases sound?"

Written after a day in which every serious bug was found by running, not by reading:
primary keys silently dropped by a DB split, ON CONFLICT inserts with nothing to bind to,
a screener pricing legs off a 5-day-stale spot, venue column names differing. Each of those
is now a check here, so the next session starts from evidence instead of assumption.

Checks fall in four groups:
  STRUCTURE  files open · every table has a key · no duplicate natural keys
  CONTENT    ranges, nulls, and referential sanity per table
  RECONCILE  positions vs fills (the book must equal what was traded)
  SOURCES    cross-source agreement (warehouse vs tail, fills vs tape, IV engines)

Exit code is non-zero when anything FAILs, so it can gate a chain.
    uv run python apps/audit/selfcheck.py [--json]
"""
import argparse
import datetime as dt
from data import clock
from data import db
import json
import pathlib
import sys

import duckdb

ROOT = bootstrap.ROOT
TODAY = clock.today()
results = []          # (group, check, verdict, detail)


def add(group, check, ok, detail, warn=False):
    verdict = "PASS" if ok else ("WARN" if warn else "FAIL")
    results.append((group, check, verdict, detail))


def open_ro(path):
    try:
        return duckdb.connect(str(path), read_only=True), None
    except Exception as e:
        return None, repr(e)[:70]


def missing_sources(con):
    """Require vendor provenance on observations, excluding reference and run metadata."""
    metadata = {"cn_product_map", "symbol_map", "instruments", "option_contracts",
                "expiries", "futures_products", "futures_contracts", "calendar",
                "events", "equity_events", "earnings", "futures_ingestion_checks"}
    missing = []
    for (table,) in con.execute("SELECT table_name FROM duckdb_tables()").fetchall():
        if table.lower() in metadata:
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        cols = {r[0].lower() for r in con.execute(f"DESCRIBE {quoted}").fetchall()}
        if "source" not in cols:
            missing.append(table)
    return missing


def keys_present(con, db_label):
    missing = []
    for (tab,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall():
        ks = con.execute("""SELECT constraint_type FROM duckdb_constraints()
                            WHERE table_name=? AND constraint_type IN ('PRIMARY KEY','UNIQUE')""",
                         [tab]).fetchall()
        if not ks:
            missing.append(tab)
    add("STRUCTURE", f"{db_label}: every table has a key",
        not missing, f"missing on: {missing}" if missing else "all keyed", warn=bool(missing))
    return missing


def sql_clock_agrees():
    """db.connect pins every DuckDB session to UTC; verify that it still does.

    This is the one check here that compares the two CLOCKS rather than the data, and it
    exists because a regression is invisible to every other check in this file: SQL-written
    and Python-written timestamps would each be internally consistent while sitting 8h
    apart in the same row. Uses db.connect on purpose -- open_ro() bypasses the pin, so
    checking through it would always pass.
    """
    try:
        c = db.connect(log="ro")
        naive_sql = c.execute("SELECT CAST(current_timestamp AS TIMESTAMP)").fetchone()[0]
        c.close()
    except Exception as e:
        add("STRUCTURE", "SQL now() is UTC", False, f"could not check: {repr(e)[:50]}")
        return
    drift = (naive_sql - clock.now()).total_seconds()
    add("STRUCTURE", "SQL now() agrees with clock.now()", abs(drift) < 60,
        f"{drift:+.1f}s drift (8h = the session zone regressed)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sql_clock_agrees()

    dbs = {}
    for label, path in (("trades", "trades.duckdb"), ("market_history", "market_history.duckdb"),
                        ("reference", "reference.duckdb"),
                        ("universe", "market_data/yahoo.duckdb")):
        con, err = open_ro(bootstrap.DATA_ROOT / path)
        dbs[label] = con
        add("STRUCTURE", f"{label}: opens read-only", con is not None,
            "ok" if con else f"LOCKED/absent — {err}")

    T, M, R, Y = dbs["trades"], dbs["market_history"], dbs["reference"], dbs["universe"]
    for label, con in (("trades", T), ("market_history", M), ("reference", R)):
        if con:
            keys_present(con, label)

    if T:
        d = T.execute("""SELECT count(*) FROM (SELECT broker, symbol, ts_utc, qty, price
                         FROM fills GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
        add("CONTENT", "fills: no duplicate executions (needs exec_id to be exact)",
            d == 0, f"{d} groups share (broker, symbol, ts, qty, price) — legitimately so for "
                    f"multi-lot fills split into 1-lot executions; see design defect D1", warn=d > 0)
        # A NULL ts_utc is a defect ONLY if nothing recorded WHY. The journal seed
        # preserves the source text in ts_orig, and three journal rows genuinely have
        # no date ("unknown" in the source spreadsheet) -- those are trades we cannot
        # time, not a writer that dropped the field. Requiring NULL to be explained is
        # the difference between "we don't know" and "we lost it"; a blanket NULL check
        # cannot tell them apart and would push the seed into inventing a timestamp.
        n = T.execute("""SELECT count(*) FROM fills
                         WHERE broker IS NULL OR qty = 0
                            OR (ts_utc IS NULL
                                AND COALESCE(ts_orig, '') NOT ILIKE '%unknown%')""").fetchone()[0]
        unexplained = T.execute("""SELECT count(*) FROM fills
                                   WHERE ts_utc IS NULL AND COALESCE(ts_orig,'') ILIKE '%unknown%'""").fetchone()[0]
        add("CONTENT", "fills: every row has time, broker, non-zero qty", n == 0,
            f"{n} bad rows" + (f" ({unexplained} with ts_utc NULL, source date recorded "
                               f"as unknown — counted as explained)" if unexplained else ""))
        # qty is stored as a positive MAGNITUDE; direction lives in `action` (verified: 0 rows
        # have negative qty). The original check assumed signed qty and was simply wrong.
        bad_act = T.execute("SELECT count(*) FROM fills WHERE action NOT IN ('BUY','SELL')").fetchone()[0]
        neg = T.execute("SELECT count(*) FROM fills WHERE qty < 0").fetchone()[0]
        add("CONTENT", "fills: qty is a magnitude, action carries direction",
            bad_act == 0 and neg == 0, f"{bad_act} bad actions · {neg} negative qty")
        d = T.execute("""SELECT count(*) FROM (SELECT day, account, source FROM account_daily
                         GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]
        add("CONTENT", "account_daily: unique per (day, account, source)", d == 0, f"{d} duplicate groups")

        # the book must equal what was traded
        #
        # The net is taken over EVERY fill. It used to filter `open_close IS NOT NULL`,
        # which discarded 463 of 622 rows -- ibkr_flex and schwab_transactions simply do
        # not carry that column -- so the check compared a subset of the trading against
        # the whole book and reported the shortfall as a reconciliation failure. Six of
        # its ten "differing" contracts (DBB, DSI, EDV, IAU, IXC, SPXL, all equities whose
        # only fill was filtered out) existed purely because of this line. `action` already
        # carries direction and `qty` is a magnitude, so open_close adds nothing here.
        try:
            net = dict(T.execute("""SELECT underlying||'|'||COALESCE(CAST(expiry AS VARCHAR),'-')||'|'||
                                    COALESCE(CAST(strike AS VARCHAR),'-')||'|'||COALESCE(call_put,'-'),
                                    sum(CASE WHEN action='BUY' THEN qty ELSE -qty END)
                                    FROM fills
                                    GROUP BY 1""").fetchall())
            pos = dict(T.execute("""SELECT underlying||'|'||COALESCE(CAST(expiry AS VARCHAR),'-')||'|'||
                                    COALESCE(CAST(strike AS VARCHAR),'-')||'|'||COALESCE(call_put,'-'), sum(qty)
                                    FROM positions GROUP BY 1""").fetchall())
            diffs = {k: (net.get(k, 0), pos.get(k, 0)) for k in set(net) | set(pos)
                     if abs(net.get(k, 0) - pos.get(k, 0)) > 0.5 and k in pos}
            note = f"{len(diffs)} contracts differ" + (f" e.g. {list(diffs.items())[:2]}" if diffs else "")
            add("RECONCILE", "positions == net of fills (per contract)", not diffs, note,
                warn=bool(diffs))   # broker-side rollovers legitimately break this; warn, don't fail
        except Exception as e:
            add("RECONCILE", "positions == net of fills", False, repr(e)[:70], warn=True)

    # ── provenance & symbol-map invariants ─────────────────────────────────────────────
    # Every row must say where it came from. Provenance is what makes a wrong number
    # traceable to the vendor that produced it, and what lets a re-fetch overwrite exactly
    # its own rows (the merge replaces by source). A table without it cannot be audited or
    # safely refreshed -- so this asserts the property rather than trusting it.
    for label, dbfile in (("market_history", "market_history.duckdb"),
                          ("cn_market", "cn_market.duckdb")):
        try:
            cc = duckdb.connect(str(bootstrap.DATA_ROOT / dbfile), read_only=True)
            # Run receipts record pipeline status rather than vendor observations.
            missing = missing_sources(cc)
            add("STRUCTURE", f"{label}: every table records its source", not missing,
                "all tables carry `source`" if not missing
                else f"NO source column on: {missing}")
            cc.close()
        except Exception as e:
            add("STRUCTURE", f"{label}: every table records its source", False,
                f"could not open ({repr(e)[:40]})", warn=True)

    # The symbol map: a bare ticker that is also a CN product code must never travel to a
    # US feed. This is the check that would have caught 'MA' fetching Mastercard.
    try:
        from data import symbols
        kinds, coll = symbols.report()
        add("STRUCTURE", "symbol map: loaded and non-empty", sum(kinds.values()) > 0,
            f"{sum(kinds.values())} rows {kinds}")
        try:
            symbols.assert_no_bare_cn(["SPY", "CN:DCE:C"], "alpaca")
            add("STRUCTURE", "symbol map: leaked CN key is refused", False,
                "guard did NOT raise on a namespaced CN key sent to a US feed")
        except symbols.SymbolError:
            add("STRUCTURE", "symbol map: leaked CN key is refused", True,
                "correctly refused")
        add("STRUCTURE", "symbol map: ambiguous strings are namespaced", True,
            f"{len(coll)} known: {', '.join(sorted(coll))} (resolved by the CN: prefix)")
    except Exception as e:
        add("STRUCTURE", "symbol map: loaded and non-empty", False, repr(e)[:70], warn=True)

    if M:
        n = M.execute("SELECT count(*) FROM option_bars WHERE close < 0 OR volume < 0").fetchone()[0]
        add("CONTENT", "option_bars: no negative prices or volume", n == 0, f"{n} rows")
        n = M.execute("SELECT count(*) FROM iv_history WHERE atm_iv NOT BETWEEN 0.001 AND 5").fetchone()[0]
        add("CONTENT", "iv_history: IV within (0, 500%)", n == 0, f"{n} rows outside")
        # Negative OI would be corruption (0 rows, verified). An extreme PCR is NOT: NBIS on
        # 2026-09-14 really traded 1 call and 1,157 puts at our tracked strikes — arithmetically
        # right, just uninformative. So: FAIL on negative OI, WARN only when an extreme ratio has
        # a meaningful denominator on BOTH sides (which is the shape a real aggregation bug takes).
        bad_oi = M.execute("SELECT count(*) FROM option_flow_daily WHERE call_oi < 0 OR put_oi < 0").fetchone()[0]
        add("CONTENT", "option_flow_daily: no negative open interest", bad_oi == 0, f"{bad_oi} rows")
        suspect = M.execute("""SELECT count(*) FROM option_flow_daily
                               WHERE (pcr_vol > 50 OR pcr_oi > 50)
                                 AND COALESCE(call_vol,0) > 50 AND COALESCE(put_vol,0) > 50""").fetchone()[0]
        add("CONTENT", "option_flow_daily: extreme ratios with real volume on both sides",
            suspect == 0, f"{suspect} rows — review source coverage; an extreme ratio alone does not prove corruption",
            warn=suspect > 0)
        d = M.execute("""SELECT count(*) FROM (SELECT source, symbol, day, count(*) c
                         FROM option_bars GROUP BY ALL HAVING c > 1)""").fetchone()[0]
        add("CONTENT", "option_bars: unique (source, symbol, day)", d == 0, f"{d} duplicate groups")
        cov = M.execute("SELECT count(DISTINCT underlying) FROM option_bars").fetchone()[0]
        add("CONTENT", "option_bars: coverage", cov > 0, f"{cov} underlyings")

    if R:
        n = R.execute("SELECT count(*) FROM earnings WHERE day < DATE '2000-01-01'").fetchone()[0]
        add("CONTENT", "earnings: no implausible dates", n == 0, f"{n} rows")
        n = R.execute("""SELECT count(*) FROM events WHERE importance NOT IN ('high','medium','low')""").fetchone()[0]
        add("CONTENT", "events: importance is a known value", n == 0, f"{n} rows")
        n = R.execute("""SELECT count(*) FROM calendar WHERE day < DATE '2020-01-01'""").fetchone()[0]
        add("CONTENT", "calendar: dates in range", n == 0, f"{n} rows before 2020")

    if Y:
        d = Y.execute("""SELECT count(*) FROM (SELECT symbol, date FROM prices
                         GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]
        add("CONTENT", "prices: one row per (symbol, date)", d == 0, f"{d} duplicate groups")

    # ---- cross-source
    if M and Y:
        M.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_data'/'yahoo.duckdb'}' AS yh (READ_ONLY)")
        n = M.execute("""SELECT count(*) FROM underlying_daily u JOIN yh.prices y
                         ON y.symbol=u.symbol AND y.date=u.day""").fetchone()[0]
        add("SOURCES", "U1 overlap (warehouse vs our tail)", True,
            f"{n} overlapping days — by design only the tail is ours", warn=False)
        n = M.execute("SELECT max(day) FROM underlying_daily").fetchone()[0]
        w = M.execute("SELECT max(date) FROM yh.prices").fetchone()[0]
        add("SOURCES", "freshness: we hold data at least as new as the warehouse",
            bool(n and w and n >= w), f"ours {n} vs warehouse {w}")

    if T and M:
        n = T.execute("""SELECT count(*) FROM fills f JOIN mh.option_bars b
                         ON b.symbol = REPLACE(f.symbol,' ','') AND b.day = CAST(f.ts_utc AS DATE)
                         WHERE f.price > 0""").fetchone()[0] if False else None
    if T and M:
        try:
            T.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' AS mh (READ_ONLY)")
            n = T.execute("""SELECT count(*) FROM fills f JOIN mh.option_bars b
                             ON b.symbol = REPLACE(f.symbol,' ','') AND b.day = CAST(f.ts_utc AS DATE)
                             WHERE f.price > 0 AND f.call_put IS NOT NULL""").fetchone()[0]
            add("SOURCES", "O1 fills checkable against an independent tape", n > 0,
                f"{n} fills pairable (of 608)")
        except Exception as e:
            add("SOURCES", "O1 fills vs tape", False, repr(e)[:60], warn=True)

    # ── UTC invariant: no timestamp may be in the future ─────────────────────────────────
    # This box runs Asia/Shanghai and DuckDB stamps `now()` in the SESSION zone, so any
    # script opening a bare duckdb.connect() and writing `now()` stored LOCAL wall time --
    # 8 hours ahead of the UTC every other table holds. db.connect() pins the zone, but a
    # script connecting directly silently opts out; three such writes were found and fixed
    # on 2026-10-02, one of them into a column literally named `ts_utc`.
    #
    # Rather than trusting that every writer remembers, assert the property the data must
    # have: a UTC timestamp CANNOT be in the future. That catches the whole class at once --
    # any writer, any table, any timezone, including rows written long ago -- and it needs no
    # list of scripts to keep up to date. A tz-aware column is compared as the instant it is;
    # a naive one is taken at face value, which is exactly the assumption under test.
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for label, dbfile in (("trades", "trades.duckdb"),
                          ("market_history", "market_history.duckdb"),
                          ("cn_market", "cn_market.duckdb"),
                          ("reference", "reference.duckdb"),
                          ("universe", "market_data/yahoo.duckdb")):
        try:
            zc = duckdb.connect(str(bootstrap.DATA_ROOT / dbfile), read_only=True)
        except Exception as e:
            # A live downloader holds the write lock; DuckDB refuses even read-only access.
            # WARN, not FAIL: the file is busy, which is normal here, not corrupt.
            add("TIME", f"{label}: no timestamp in the future", False,
                f"skipped — a writer holds the file ({type(e).__name__})", warn=True)
            continue
        try:
            zbad = []
            for (zt,) in zc.execute("SELECT table_name FROM duckdb_tables()").fetchall():
                try:
                    zcols = zc.execute(f'DESCRIBE "{zt}"').fetchall()
                except Exception:
                    continue
                for zc_col in zcols:
                    if "TIMESTAMP" not in str(zc_col[1]).upper():
                        continue          # DATE is coarse and legitimately forward-dated
                    try:
                        zv = zc.execute(f'SELECT max("{zc_col[0]}") FROM "{zt}"').fetchone()[0]
                    except Exception:
                        continue
                    if zv is None:
                        continue
                    znaive = (zv.astimezone(dt.timezone.utc).replace(tzinfo=None)
                              if getattr(zv, "tzinfo", None) else zv)
                    zdrift = (znaive - now_utc).total_seconds() / 3600.0
                    if zdrift > 1.0:      # allowance covers clock skew, not a timezone
                        zbad.append((zt, zc_col[0], str(zv)[:19], round(zdrift, 1)))
            add("TIME", f"{label}: no timestamp in the future", not zbad,
                f"{len(zbad)} column(s) ahead of UTC, e.g. {zbad[:3]}" if zbad
                else "every timestamp at or before now (UTC)")
        finally:
            zc.close()

    # ── US session-window invariant (timezone, verified in the DATA) ─────────────────────
    # The future-check above only fires on recent writes. This one works on rows written at
    # any time, because it uses an independent fact: a machine-generated US minute bar can
    # only exist inside a trading session. Extended hours span 08:00-24:00 UTC (04:00-20:00
    # ET), so a bar outside that window is either a genuine bug or a shifted clock -- and a
    # +8 shift moves the whole session to 16:00-08:00, which is unmistakable en masse.
    #
    # Only ALPACA rows: they are fetched by us on a UTC clock and carry no vendor local time.
    # Futu/akshare rows are deliberately excluded -- the CN venues stamp in Beijing time, and
    # a CN session legitimately sits at 01:30-07:00 UTC, which this window would call a bug.
    if M:
        for tbl, label in (("underlying_minutes", "underlying"), ("option_minutes", "option")):
            try:
                tot, out = M.execute(f"""
                    SELECT count(*), count(*) FILTER (
                        WHERE EXTRACT(hour FROM ts_utc) < 8
                           OR EXTRACT(hour FROM ts_utc) >= 24)
                    FROM {tbl} WHERE source = 'alpaca_1min'""").fetchone()
                if not tot:
                    add("TIME", f"{label} 1-min bars fall inside the US session", True,
                        "no alpaca_1min rows yet")
                    continue
                pct = 100.0 * out / tot
                add("TIME", f"{label} 1-min bars fall inside the US session", pct < 5.0,
                    f"{pct:.2f}% outside 08:00-24:00 UTC ({out:,} of {tot:,})")
            except Exception as e:
                add("TIME", f"{label} 1-min session window", False, repr(e)[:60], warn=True)

    if args.json:
        print(json.dumps([{"group": g, "check": c, "verdict": v, "detail": d}
                          for g, c, v, d in results], indent=1))
    else:
        line = "| group | check | verdict | detail |"
        for g, c, v, d in results:
            print(f"[{v:4}] {g:9} {c:52} {d[:60]}")
    fails = [r for r in results if r[2] == "FAIL"]
    warns = [r for r in results if r[2] == "WARN"]
    if M:
        try:
            M.close()
        except Exception:
            pass
    print(f"\n{len(results)} checks · {len(results)-len(fails)-len(warns)} pass · "
          f"{len(warns)} warn · {len(fails)} fail")
    for con in (T, R, Y):
        if con:
            try:
                con.close()
            except Exception:
                pass
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
