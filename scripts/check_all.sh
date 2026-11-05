#!/bin/bash
# check_all.sh — every check this repo has, behind one command. This is what CI runs.
#
# WHY THIS EXISTS
#
# The repo had the checks (selfcheck's 38 assertions, check_iv_solvers, check_duplicates) but
# nothing that ran them together, so they ran when someone remembered. On 2026-10-03 four
# separate edits to the download path were each verified ad hoc — a hand-written outage test
# here, a throughput measurement there — and the project's own harness was run once, at the
# very end. Nothing would have caught a subtle break earlier.
#
# THREE LANGUAGES, and the third is the one that bites silently:
#
#   Python  — 187 modules compile; each imports under BOTH its new dotted path and its
#             scripts/ shim; each shim must ALIAS the real module, not copy it.
#   shell   — every script parses.
#   C++     — third_party/qliv links the vendored QuantLib behind a ctypes shim, and
#             core/quant/bs.py loads it ONLY IF the .so is present, falling back to a
#             pure-Python solver otherwise. That fallback is silent, and this repo has
#             already shipped it once by accident (a depth-dependent path bug downgraded
#             bs.py "with no error at all"). So the native check asserts USING_QUANTLIB
#             rather than trusting that the import worked.
#
# MODES
#
#   --fast  (default)  code only, no data. Safe to run WHILE a download holds a database,
#                      which on this box is the only time anyone thinks to run checks. It
#                      is also all CI can run: *.duckdb and third_party/ are gitignored.
#   --full             adds the data checks (selfcheck, IV solvers, duplicate keys). Needs
#                      the four databases AND a quiet box — a merge holding market_history
#                      makes them fail spuriously.
#   --build            adds the C++ build (libQuantLib.a + qliv.so). Needs the vendored
#                      source, cmake and Boost headers; ~10 min cold, seconds warm.
#
#   scripts/check_all.sh [--fast|--full|--build]
set -u
# pipefail is LOAD-BEARING, not hygiene. Every data check below is invoked as
#     uv run ... python scripts/selfcheck.py 2>&1 | tail -3 || fail=1
# and without pipefail a pipeline's exit status is the LAST command's -- tail's,
# which is always 0. So `|| fail=1` could never fire and a FAILING selfcheck was
# discarded while the script still printed "PASS — check_all --full". The gate
# looked green by construction. Fixed 2026-10-05 during the layer restructure,
# when it mattered that the gate actually gate.
set -o pipefail
cd "$(dirname "$0")/.." || { echo "cannot cd to the repo root"; exit 1; }

MODE="${1:---fast}"
fail=0
note() { printf '\n=== %s ===\n' "$1"; }

# Top-level packages that belong to THIS repo. A ModuleNotFoundError naming one of
# these is a broken import -- a bad path, a stale name, a file that moved -- and fails
# the check. Anything else is an absent third-party dep and is only reported.
#
# This list is the one thing here that silently rots: it was ("core","apps","scripts"),
# and during the layer restructure a module living in datasources/ or compute/ that
# failed to import would have been reported as "needs an absent third-party dep" and
# TOLERATED -- the gate would have gone green on a genuinely broken import. Keep it in
# step with the top-level directories; a new layer MUST be added here.
REPO_PKGS="apps scripts datasources data compute shared market_data"
# Exported so the Python heredocs below can read it. They are QUOTED heredocs
# (<<'PY'), so shell expansion does NOT happen inside them -- referencing
# $REPO_PKGS there yields a NameError, not the value.
export REPO_PKGS

# ── 1. shell ─────────────────────────────────────────────────────────────────────────────
note "shell syntax (bash -n)"
sh_bad=0
for f in scripts/*.sh; do
    [ -f "$f" ] || continue
    bash -n "$f" 2>/dev/null || { echo "  FAIL  $f"; sh_bad=$((sh_bad + 1)); }
done
[ "$sh_bad" -eq 0 ] && echo "  ok — every script parses" || fail=1

# ── 2. python: compile, import, shim aliasing ────────────────────────────────────────────
note "python — compile, import by dotted path, shim aliasing"
uv run --locked python - <<'PY' || fail=1
import importlib, os, pathlib, py_compile, sys

ROOT = pathlib.Path.cwd()
sys.path.insert(0, str(ROOT))
# scripts/ too: the shims exist so a file INSIDE scripts/ can still `import db`. Without it
# on the path, 40 healthy shims report as broken.
sys.path.insert(0, str(ROOT / "scripts"))

# Modules whose IMPORT performs work. Importing one is not a check, it is a side effect —
# and `import merge_staging` would run the merge against live staging files. The root cause
# is that merge_staging has no main(): its whole program sits at module level, so importing
# it IS running it (the same reason `import merge_staging` used to die on the importer's
# argv — see the parse_args guard in that file). Excluded until it gets a main().
# EMPTY as of 2026-10-05. merge_staging was the only entry: it had no main(), so
# importing it ran the merge (and raised SystemExit when staging/ was empty).
# It now has main() + a __main__ guard, verified inert to import, so the gate
# checks it like anything else. Keep the mechanism -- it is the right guard for
# the next module that grows import-time work.
EXECUTES_ON_IMPORT = set()

bad = []
files = [ROOT / "bootstrap.py"]
# Derived from REPO_PKGS, NOT a literal. The hardcoded ("core","apps","scripts")
# here meant that as soon as a layer moved to shared/ or data/ or compute/, the
# gate stopped seeing those modules entirely -- silently unchecking the very code
# the move had just touched, while still printing PASS. Caught because the
# imported-module count FELL after a move that should not have changed it.
for d in os.environ.get("REPO_PKGS", "core apps scripts").split():
    if (ROOT / d).is_dir():
        files += sorted((ROOT / d).rglob("*.py"))
files = [f for f in files if "__pycache__" not in f.parts and "third_party" not in f.parts]
for f in files:
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        bad.append(f"{f.relative_to(ROOT)}: {(e.msg or '').splitlines()[0]}")
print(f"  compiled {len(files)} modules" + (f" — {len(bad)} FAILED" if bad else " — ok"))
for b in bad:
    print(f"    FAIL {b}")

# Derived from REPO_PKGS, like the compile loop. This line was literally
# ("core", "apps") and `core/` no longer exists -- Path.rglob on a missing dir
# yields [] silently, so the dotted-import check had quietly narrowed to apps/
# only, and a broken import in datasources/ or compute/ would have passed.
# scripts/ is excluded, and that exclusion is load-bearing rather than tidiness.
# Shims have their own loop below which skips any shim whose target executes on
# import; the dotted sweep has no such guard, and importing a shim imports its
# target -- pulling scripts/ in here re-imported scripts/merge_staging.py, which
# ran the merge. It aborted only because merge_staging raises SystemExit with
# "nothing staged"; on a quiet box with staging files present it would have
# merged for real, as a side effect of "checking imports".
#
# market_data/ was briefly excluded too, because four archived scripts there
# executed at module level and read fixed paths from a finished migration
# (/workspace/..., filing1993.txt), so importing them raised FileNotFoundError.
# That was the gate being narrowed to accommodate a defect rather than the defect
# being fixed -- a module the sweep cannot import is precisely what it exists to
# find. All four now have main() + a __main__ guard and the subproject is covered
# like everything else.
IMPORT_SWEEP = [d for d in os.environ.get("REPO_PKGS", "apps").split()
                if d != "scripts"]
real = [p for d in IMPORT_SWEEP for p in (ROOT / d).rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"]
imp_bad, skipped, nodep = [], 0, []
for p in real:
    dotted = ".".join(p.relative_to(ROOT).with_suffix("").parts)
    if dotted in EXECUTES_ON_IMPORT:
        skipped += 1
        continue
    try:
        importlib.import_module(dotted)
    except ModuleNotFoundError as e:
        # Distinguish the two cases that look alike and mean opposite things. A missing
        # THIRD-PARTY package (ib_async, yfinance, openpyxl) says nothing about this repo's
        # import wiring — the environment simply lacks an optional dep, and failing on it
        # would make the check red for reasons that are not defects. A missing REPO module
        # is a genuine break: a bad path, a stale import, a moved file. So the first is
        # reported and tolerated, the second fails. See REPO_PKGS at the top.
        missing = (e.name or "").split(".")[0]
        if missing in os.environ.get("REPO_PKGS", "core apps scripts").split():
            imp_bad.append(f"{dotted}: {type(e).__name__}: {e}")
        else:
            nodep.append(f"{dotted} (needs {missing})")
    except Exception as e:
        imp_bad.append(f"{dotted}: {type(e).__name__}: {e}")
print(f"  imported {len(real) - skipped - len(nodep)} modules by dotted path"
      + (f" ({skipped} skipped: import executes work)" if skipped else "")
      + (f" ({len(nodep)} need an absent third-party dep)" if nodep else "")
      + (f" — {len(imp_bad)} FAILED" if imp_bad else " — ok"))
for b in imp_bad:
    print(f"    FAIL {b}")
if nodep:
    for n in nodep[:4]:
        print(f"    note {n}")
    if len(nodep) > 4:
        print(f"    note ... and {len(nodep) - 4} more (add the dep or ignore)")

# A shim must ALIAS (`sys.modules[__name__] = real`), not copy. A copy still imports cleanly
# and silently loses reload() and underscore-private names, so assert identity.
#
# Detection is anchored to the module DOCSTRING'S first line, not a bare substring: the
# marker also appears in move_layer.py, which GENERATES shims and therefore quotes the
# template. A substring test flagged that tool as a broken shim.
import re
shim_re = re.compile(r'^\s*"""\w+\.py — COMPATIBILITY SHIM\.')
# BOTH locations. Five shims live beside their old app module rather than in
# scripts/, and only scripts/ was ever scanned, so those five were never
# alias-checked. (Their marker also sits after the imports rather than as a
# docstring, which is why an anchored ^ regex cannot see them -- hence the
# search-from-anywhere form below.)
shims = [p for p in sorted((ROOT / "scripts").glob("*.py"))]
shims += [p for p in sorted((ROOT / "apps").rglob("*.py"))
          if "COMPATIBILITY SHIM" in p.read_text(errors="replace")[:600]]
alias_bad, aliased = [], 0
for p in shims:
    text = p.read_text(errors="replace")
    # The anchored match is right for scripts/ shims and is what keeps move_layer.py
    # (which quotes the shim TEMPLATE in its own source) from being mistaken for
    # one. The apps shims put their imports first, so the marker is not at
    # position 0 and the anchored form would skip them; they were already
    # identified by the marker search when the list was built.
    if "apps" not in p.parts and not shim_re.match(text):
        continue
    # Skip a shim whose TARGET executes on import. The dotted-path loop already skips those,
    # but a shim imports its target too — and a shim is a plain `import <dotted>`, so the
    # first version of this check ran the whole merge as a side effect of "checking imports".
    # It survived only because the running shards held those staging files and DuckDB
    # refused the lock; with a quiet box it would have merged for real.
    if any(re.search(rf"^\s*import\s+{re.escape(t)}\b", text, re.M) for t in EXECUTES_ON_IMPORT):
        print(f"  skipped shim {p.stem} — its target executes work on import")
        continue
    aliased += 1
    try:
        name = p.stem if p.parent.name == "scripts" else ".".join(p.relative_to(ROOT).with_suffix("").parts)
        m = importlib.import_module(name)
    except ModuleNotFoundError as e:
        # Same split as above, and it applies here too: most shims front a module that needs
        # ib_async, yfinance, openpyxl or numpy, none of which this environment installs. An
        # absent optional dep is not a broken shim.
        missing = (e.name or "").split(".")[0]
        if missing in os.environ.get("REPO_PKGS", "core apps scripts").split():
            alias_bad.append(f"{p.stem}: import failed — {type(e).__name__}: {e}")
        else:
            nodep.append(f"{p.stem} (needs {missing})")
        continue
    except Exception as e:
        alias_bad.append(f"{p.stem}: import failed — {type(e).__name__}: {e}")
        continue
    if getattr(m, "__name__", "") == p.stem:
        alias_bad.append(f"{p.stem}: imported but did NOT alias — a copy breaks reload() "
                         f"and _private names")
print(f"  aliased {aliased} shims" + (f" — {len(alias_bad)} FAILED" if alias_bad else " — ok"))
for b in alias_bad:
    print(f"    FAIL {b}")

sys.exit(1 if (bad or imp_bad or alias_bad) else 0)
PY

# ── 3. the C++ solver bridge ─────────────────────────────────────────────────────────────
note "native IV solver (QuantLib via third_party/qliv/qliv.so)"
if [ -d ../data_providers/third_party/QuantLib ] && [ "${CHECK_NATIVE_REQUIRED:-1}" != "0" ]; then
    # The sources are here, so the native path MUST be live. A missing or unloadable .so is
    # the failure this check exists for: bs.py falls back to pure Python silently, every
    # timing in the repo then describes the fallback, and the reports still claim QuantLib.
    uv run --locked python - <<'PY' || fail=1
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.cwd()))
from compute import bs
if bs.USING_QUANTLIB:
    v = bs.implied_vol(12.5, 100.0, 100.0, 0.25, 0.04, True)
    print(f"  ok — USING_QUANTLIB=True; ATM 25d call backed out to IV={v:.4f}")
else:
    print("  FAIL — third_party/QuantLib is present but bs.USING_QUANTLIB is False.")
    print("         The solver silently fell back to pure Python. Build it:")
    print("           bash scripts/build_qliv.sh")
    sys.exit(1)
PY
else
    # A fresh clone has no vendored C++ (third_party/ is gitignored), so this cannot be
    # judged here. Say so instead of passing quietly.
    echo "  SKIP — native library check unavailable or explicitly excluded by CHECK_NATIVE_REQUIRED=0."
    echo "         The Python fallback is in use. Not a native pass: a runner has"
    echo "         nothing to test, a developer off the vendored source has a real gap."
fi

# ── 4. C++ build (--build) ───────────────────────────────────────────────────────────────
if [ "$MODE" = "--build" ]; then
    note "C++ build (vendored QuantLib + qliv.so)"
    if bash scripts/build_qliv.sh 2>&1 | tail -5; then
        echo "  ok — build_qliv.sh completed"
    else
        echo "  FAIL — build_qliv.sh failed"; fail=1
    fi
fi

# ── 4b. the risk profile, against the book it claims to describe ─────────────────────────
#
# Runs in --full because it compares mutable runtime book and report evidence.
# --fast remains code-only; pure valuation invariants run in the unit suite.
# Missing/locked runtime data is reported explicitly by the integration audit.
#
# Every failure of 2026-10-06 presented as a plausible number rather than an error, which
# is why this is a check and not a habit:
#   * a book that still held a position that had been rolled (Nov-20 32P for a Dec-18 43P)
#   * spots taken from the previous session's close, presented as current
#   * a Dec-18 leg silently carrying a Nov-20 row's greeks and mark -- EWZ's came from a
#     snapshot taken when EWZ was 36.03, and it moved EWZ's delta notional by ~$15k
#   * a report describing a different set of spots than the marks beside it
# So: the greeks must re-derive from the row's OWN mark+spot+IV, delta_notional must equal
# delta_units*spot, the report's headline and whole scenario ladder must reproduce from
# `positions`, and leg_estimates (an independent estimate path) must agree with the book.
#
# WITHOUT --live, deliberately. Live mode refetches quotes and rebuilds the book, needs TWS
# or the vendor feeds, and must not decide whether a commit lands. It is `make risk-check`,
# and it is the only mode that catches a STALE book -- a stale book and a fresh one are
# bit-identical to any check that does not refetch.
if [ "$MODE" = "--full" ]; then
    note "risk profile (book ↔ report)"
    uv run --locked python scripts/risk_profile_check.py --quiet || fail=1
else
    note "risk profile integration deferred to --full"
    echo "  Offline risk invariants run in the unit suite. Runtime book/report freshness"
    echo "  requires the data audit: make check-full or make risk-check."
fi

# ── 4c. unit tests ───────────────────────────────────────────────────────────────────────
#
# Runs in EVERY mode, including --fast and CI, because the tests that belong here need
# no database and no broker: they are the pure functions -- the rates and rank tables,
# the pricing helpers, the validators, the formatters. Tests that DO need a database
# carry @unittest.skipUnless and skip themselves on a runner, which is the same
# contract --full uses for everything else.
#
# The dependency list is not decoration: some tests deliberately import the modules that
# wire these tables up (tests/datasources/test_source_rank.py asserts the fetch module
# reads through to the shared rank table rather than keeping its own copy), and that
# import pulls ib_async, futu-api and alpaca-py.
#
# tests/test_harness.py is the ratchet: it fails if the number of modules with tests
# falls below tests/coverage_baseline.json. A gate that is red on the day it lands
# teaches people to bypass it, so this one starts where the coverage actually is and
# can only rise.
note "unit tests (unittest)"
uv run --locked python -m unittest discover -s tests -t . || fail=1

# ── 5. data checks (--full) ──────────────────────────────────────────────────────────────
if [ "$MODE" = "--full" ]; then
    note "selfcheck (data integrity)"
    uv run --locked python scripts/selfcheck.py 2>&1 | tail -3 || fail=1
    note "IV solvers (QuantLib vs the pure-Python fallback)"
    uv run --locked python scripts/check_iv_solvers.py 2>&1 | tail -3 || fail=1
    note "duplicate keys (all four databases)"
    uv run --locked python scripts/check_duplicates.py 2>&1 | tail -6 || fail=1
    # The 2026-10-05 shapes, as checks. Static and data: an executemany with no empty
    # guard crashes (it killed build_option_flow mid-symbol), and rows that insert
    # cleanly while holding nothing (qty 0, NULL price, a symbol that cannot join) are
    # invisible without looking at the data. --full because half of it reads the DB.
    note "regressions of the 2026-10-05 shapes"
    uv run --locked python scripts/check_regressions.py 2>&1 | tail -4 || fail=1
else
    note "data checks skipped (not --full)"
    echo "  selfcheck, IV solvers and duplicate keys need the databases and a quiet box."
fi

note "verdict"
if [ "$fail" -eq 0 ]; then echo "  PASS — check_all $MODE"; else echo "  FAIL — check_all $MODE"; fi
exit "$fail"
