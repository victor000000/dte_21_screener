"""restructure_fingerprint.py — per-table row counts for the four databases.

WHY THIS EXISTS. The previous restructure destroyed 152,304 rows of CN data.
Not by moving files -- by a migration script whose DELETE predicate was wider
than its INSERT. The lesson recorded at the time:

    "a delete whose predicate is wider than its insert is not idempotency,
     it is data loss with a reassuring comment."

This restructure is code-only and is not supposed to write to any database at
all. So the fingerprint is not a migration tool; it is a DETECTOR. Take one
before the moves, one after, and any difference means code ran that should not
have. Treat a diff as a stop-the-line event, not a number to explain away.

    python scripts/restructure_fingerprint.py write plans/restructure_fingerprint.json
    python scripts/restructure_fingerprint.py diff  plans/restructure_fingerprint.json

Opens every file READ-ONLY, so it is safe while a downloader holds a write lock
-- which on this box is most of the time, and specifically the condition under
which someone remembers to run checks.

market_history.duckdb is 2 GB and is not copied anywhere; for it the row counts
plus per-table max-timestamp ARE the check.
"""
import json
import pathlib
import bootstrap
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The four databases, by lifecycle (see plans/PROJECT_DESIGN.md §2).
DBS = [
    ("trades", bootstrap.DATA_ROOT / "trades.duckdb"),
    ("market_history", bootstrap.DATA_ROOT / "market_history.duckdb"),
    ("reference", bootstrap.DATA_ROOT / "reference.duckdb"),
    ("cn_market", bootstrap.DATA_ROOT / "cn_market.duckdb"),
]

# Columns worth tracking a high-water mark on, most specific first.
STAMP_COLS = ("as_of", "timestamp_utc", "day", "date", "created_at", "ts")


def snapshot():
    out = {}
    for name, path in DBS:
        if not path.exists():
            out[name] = {"_missing": True}
            continue
        try:
            con = duckdb.connect(str(path), read_only=True)
        except Exception as e:
            # A held write lock must NOT look like "zero rows" -- that is the
            # "failure recorded as absence of data" trap from
            # plans/NETWORK_RETRY_DESIGN.md.
            out[name] = {"_unreadable": repr(e)[:200]}
            continue
        tables = {}
        try:
            names = [r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' ORDER BY table_name").fetchall()]
            for t in names:
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception as e:
                    tables[t] = {"error": repr(e)[:120]}
                    continue
                entry = {"rows": n}
                cols = {r[0] for r in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ?", [t]).fetchall()}
                for c in STAMP_COLS:
                    if c in cols:
                        try:
                            hi = con.execute(
                                f'SELECT CAST(MAX("{c}") AS VARCHAR) FROM "{t}"').fetchone()[0]
                            entry["max_" + c] = hi
                        except Exception:
                            pass
                        break
                tables[t] = entry
        finally:
            con.close()
        out[name] = tables
    return out


def cmd_write(dest):
    snap = snapshot()
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    total = sum(v.get("rows", 0) for db in snap.values()
                for v in db.values() if isinstance(v, dict))
    print(f"wrote {dest} — {len(snap)} databases, {total:,} rows total")
    for db, tables in snap.items():
        if not isinstance(tables, dict) or "_missing" in tables or "_unreadable" in tables:
            print(f"  {db:<15} {tables}")
        else:
            print(f"  {db:<15} {len(tables):>3} tables, "
                  f"{sum(t.get('rows', 0) for t in tables.values()):>12,} rows")


def cmd_diff(ref):
    before = json.loads(pathlib.Path(ref).read_text())
    after = snapshot()
    diffs = []
    for db in sorted(set(before) | set(after)):
        b, a = before.get(db, {}), after.get(db, {})
        for name in sorted(set(b) | set(a)):
            bv, av = b.get(name), a.get(name)
            if bv is None:
                diffs.append(f"  + {db}.{name}: NEW table ({av.get('rows')} rows)")
                continue
            if av is None:
                diffs.append(f"  ! {db}.{name}: TABLE GONE (was {bv.get('rows')} rows)")
                continue
            if "_unreadable" in av or "_unreadable" in bv:
                if bv.get("_unreadable") != av.get("_unreadable"):
                    diffs.append(f"  ? {db}.{name}: readability changed")
                continue
            if bv.get("rows") != av.get("rows"):
                diffs.append(f"  ! {db}.{name}: {bv.get('rows')} -> {av.get('rows')} rows")
            for k in bv:
                if k.startswith("max_") and bv[k] != av.get(k):
                    diffs.append(f"  ~ {db}.{name}.{k[4:]}: {bv[k]} -> {av.get(k)}")

    if diffs:
        print("DIFFERENCES FOUND — something wrote to a database:")
        print("\n".join(diffs))
        return 1
    print("no differences — every table matches the fingerprint")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    mode, arg = sys.argv[1], sys.argv[2]
    if mode == "write":
        cmd_write(arg)
        sys.exit(0)
    elif mode == "diff":
        sys.exit(cmd_diff(arg))
    else:
        print(__doc__)
        sys.exit(2)
