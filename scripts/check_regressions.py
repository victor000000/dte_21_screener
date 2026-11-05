import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bootstrap  # noqa: F401

"""check_regressions.py — the specific mistakes made on 2026-10-05, as checks.

Every bug found that day was one of four shapes, and each shape is detectable without
knowing anything about the data. The point is not to test the code; it is to make the
SAME mistake fail loudly the next time instead of presenting as a plausible number.

  1. executemany() ON AN EMPTY LIST. DuckDB raises rather than doing nothing. It killed
     build_option_flow mid-symbol (after the DELETE had committed, destroying 268
     flow-days) and hit the Schwab loader too. Detectable: a call with no guard.

  2. A BARE `except: pass`. This hid the reason spot_for fell back to the previous close
     for every ticker -- market_history was not attached, the query threw, and the
     handler erased it. Also hid whatIfOrder returning a list rather than a state. Two
     bugs, both invisible, both found only by instrumenting the function.

  3. A ROW THAT INSERTS CLEANLY AND HOLDS NOTHING. The Schwab CSV loader wrote qty 0 and
     price NULL for all 12 fills -- off-by-one column indices plus a regex that did not
     accept a leading '+'. Every write succeeded. Detectable in the data.

  4. A KEY THAT CANNOT JOIN. broker_positions stored the statement's human string
     ("100 20 NOV 26 220 PUT") as the symbol while `positions` used OCC, producing 18
     phantom mismatches that were one bad key.

    uv run python scripts/check_regressions.py
"""
import ast
import pathlib
import sys

ROOT = bootstrap.ROOT
SKIP = {".venv", "third_party", "backup", "__pycache__", "market_data"}


def sources():
    for p in sorted(ROOT.rglob("*.py")):
        if any(s in p.parts for s in SKIP):
            continue
        yield p


def check_executemany(fails):
    """A call not enclosed by a truthiness test on the very list it inserts.

    The enclosing test is found on the AST, not by scanning lines above the call. A
    line scan gets this wrong in both directions: it accepts an unrelated `if rows:`
    that happens to sit higher up, and -- the mistake actually made here -- it misses
    that `if symbol:` does not protect a call whose argument is `ticks`.
    """
    for p in sources():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # a full parent map -- a Call's parent is its Expr, not the If, so a
        # statement-only map would never get the walk started
        parent_of = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_of[id(child)] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "executemany"):
                continue
            if len(node.args) < 2:
                continue  # execute()-style: params passed elsewhere, nothing to guard
            data = node.args[-1]
            if isinstance(data, (ast.List, ast.Tuple)) and any(not isinstance(e, ast.Starred) for e in data.elts):
                continue  # A literal with an explicit element cannot be empty.
            # the list being inserted: a bare name, or a comprehension over one
            names = [data.id] if isinstance(data, ast.Name) else \
                    [g.iter.id for g in data.generators if isinstance(g.iter, ast.Name)] \
                    if isinstance(data, (ast.ListComp, ast.SetComp)) else []
            # walk outward to the function boundary, looking for an If that tests one
            # of the names -- and that encloses the call on the branch being taken
            stmt, guarded = node, False
            while id(stmt) in parent_of:
                parent = parent_of[id(stmt)]
                if isinstance(parent, ast.If):
                    branch = parent.body if stmt in parent.body else parent.orelse
                    if stmt in branch:  # an else: branch means the test was FALSE
                        for nm in names:
                            t = parent.test
                            hit = (isinstance(t, ast.Name) and t.id == nm) or \
                                  (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                                   and isinstance(t.operand, ast.Name) and t.operand.id == nm
                                   and branch is parent.orelse)
                            if hit:
                                guarded = True
                # the early-exit guard: `if not rows: ... continue` in the same block,
                # above the call. Every caller of this check writes it this way.
                body = getattr(parent, "body", None)
                if isinstance(body, list) and stmt in body:
                    for prev in body[:body.index(stmt)]:
                        if not isinstance(prev, ast.If):
                            continue
                        t = prev.test
                        if not (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                                and isinstance(t.operand, ast.Name)):
                            continue
                        exits = any(isinstance(s, (ast.Continue, ast.Break, ast.Return,
                                                   ast.Raise, ast.Expr)) and
                                    (isinstance(s, (ast.Continue, ast.Break, ast.Return, ast.Raise))
                                     or (isinstance(s, ast.Expr)
                                         and isinstance(s.value, ast.Call)
                                         and getattr(s.value.func, "id", "") == "exit"))
                                    for s in prev.body)
                        if exits and t.operand.id in names:
                            guarded = True
                stmt = parent
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    break
            if not guarded:
                label = names[0] if names else ast.unparse(data)[:30]
                fails.append(f"{p.relative_to(ROOT)}:{node.lineno} executemany with no "
                             f"empty guard on `{label}` — DuckDB raises on []")


def check_local_tz(warns):
    """`datetime.now().astimezone()` in a file that imports bootstrap is ALWAYS UTC.

    bootstrap.py forces TZ=UTC in-process. So this idiom -- the obvious way to write
    "convert local to UTC" -- silently becomes a no-op: it attaches UTC to a wall-clock
    time that was read in some other zone. It produced no error and no wrong-looking
    value; it stored the Schwab export's China-local fill times as if they were UTC,
    which put all 12 of 2026-10-05's fills in the future. Recover the offset from the
    data instead (see session_offset in load_schwab_csv.py).
    """
    for p in sources():
        try:
            text = p.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except Exception:
            continue
        if "import bootstrap" not in text:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "astimezone" and not node.args):
                continue
            warns.append(f"{p.relative_to(ROOT)}:{node.lineno} .astimezone() with no zone "
                         f"in a bootstrap file — bootstrap forces TZ=UTC, so this is a no-op")


def check_bare_except(warns):
    """`except ...: pass` with nothing else -- the shape that hid two bugs."""
    for p in sources():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = [b for b in node.body if not isinstance(b, ast.Pass)]
            if len(body) == 0 and len(node.body) == 1:
                warns.append(f"{p.relative_to(ROOT)}:{node.lineno} bare `except: pass`")


def check_data(fails):
    """Rows that are recorded but empty, and keys that cannot join."""
    try:
        import duckdb
        con = duckdb.connect(str(bootstrap.DATA_ROOT / "trades.duckdb"), read_only=True)
    except Exception:
        return
    try:
        n = con.execute("""SELECT count(*) FROM fills
                           WHERE qty = 0 OR (price IS NULL AND security_type <> 'COMBO')""").fetchone()[0]
        if n:
            fails.append(f"trades.fills: {n} row(s) with qty 0 or a NULL price — a row "
                         f"that looks recorded and holds nothing (the Schwab CSV wrote 12)")
        n = con.execute("""SELECT count(*) FROM fills WHERE ts_utc IS NULL
                           AND COALESCE(ts_orig,'') NOT ILIKE '%unknown%'""").fetchone()[0]
        if n:
            fails.append(f"trades.fills: {n} row(s) with no ts_utc — every trade carries a "
                         f"timestamp, and 3 are allowed only as source-recorded 'unknown'")
        try:
            # Validate each broker's contract format against the structured leg.
            from apps.audit.broker_keys import invalid_broker_symbol_count
            bad = invalid_broker_symbol_count(con)
            if bad:
                fails.append(f"trades.broker_positions: {bad} symbol(s) with an invalid US/CN broker key — "
                             f"cannot join with `positions`")
        except Exception as e:
            # This check is about symbols that cannot join; if the join check itself
            # cannot run, say so. A silent pass here is the exact shape being hunted.
            #
            # `fails`, not `warns`: this handler is inside check_data(fails), which has
            # no `warns` in scope, so the reporting path raised NameError instead of
            # reporting -- and the outer handler then filed it as "data checks could
            # not run", which is a different fault with a different cause. The gate's
            # own diagnostics were the bug.
            fails.append(f"broker_positions symbol check could not run: {repr(e)[:60]}")
    except Exception as e:
        fails.append(f"data checks could not run: {repr(e)[:60]}")
    finally:
        con.close()


def main():
    # `warns` are shown one by one and mean something; `noise` is the bare-except census,
    # which is only worth a count. They were one list, so main() labelled every advisory
    # "advisory bare `except: pass`" -- which HID the timezone warning this file exists to
    # raise. An advisory nobody can read is not an advisory.
    fails, warns, noise = [], [], []
    check_executemany(fails)
    check_local_tz(warns)
    check_bare_except(noise)
    check_data(fails)
    if fails:
        print(f"  {len(fails)} FAIL of the 2026-10-05 shapes:")
        for f in fails:
            print(f"    ! {f}")
    else:
        print("  no crash-or-corrupt shapes present")
    for w in warns:
        print(f"    ~ {w}")
    if noise:
        print(f"  ({len(noise)} bare `except: pass` sites — census only, not gating)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
