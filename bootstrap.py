"""bootstrap.py — the one place that puts the repo root on sys.path.

Every entry point under apps/ and every module under core/ starts with:

    import bootstrap                              # noqa: F401  (import for the side effect)
    from core import db, clock

WHY THIS EXISTS. The repo runs as `uv run --no-project ... python <path>`, which installs
nothing: there is no package for `import core.db` to resolve against. So the repo root has to
be on sys.path before the first `from core import ...`.

The alternative — and what the old flat scripts/ directory did — is a `sys.path.insert(
dirname(__file__))` at the top of every file. That worked only because every file was in the
same directory, and it meant 84 copies of the same three lines, each subtly different (some
insert at 0, some append, some resolve symlinks, some do not). It also made the import graph
invisible: you could not tell a data-layer import from an application one.

One implementation, imported once, at the top of the file that needs it. A file that is
IMPORTED rather than run does not need to import this — its importer will already have done
so, which is what keeps the library modules free of import side effects.

NOTE ON ORDERING: this must be imported before anything that imports a local module. Python
executes imports in order, so putting it first is sufficient — but nothing enforces that, and
a `from core import db` placed above it fails with ModuleNotFoundError. Keep it at the top.
"""
import os
import pathlib
import platform
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent

# WSL reaches Windows broker services through localhost in mirrored networking.
# Keep explicit user overrides and the container's existing defaults intact.
if "microsoft" in platform.release().lower() and not pathlib.Path("/.dockerenv").exists():
    os.environ.setdefault("IB_HOST", "127.0.0.1")
    os.environ.setdefault("FUTU_HOST", "127.0.0.1")

# Source and data ownership are independent. Honor the provider configuration.
from data_providers.runtime import data_home
DATA_ROOT = data_home()

if str(ROOT) not in sys.path:
    # insert(0) rather than append: a stray same-named module elsewhere on the path must not
    # shadow this repo's.
    sys.path.insert(0, str(ROOT))

# ── The project runs on UTC, and says so as early as it can ──────────────────────────────
#
# This box's system zone is Asia/Shanghai (UTC+8) while every timestamp column here stores
# NAIVE UTC, so anything that reads the machine's zone is eight hours ahead of the data it is
# compared against. core/clock.py documents the incidents that rule exists for; it also pins
# TZ=UTC, but only inside the PROCESS THAT IMPORTS IT — and bootstrap is imported first by
# every entry point, while clock is not.
#
# Pinning here closes the gap between "the modules that remembered" and "everything else":
#
#   * a script that imports bootstrap but never clock now still gets UTC;
#   * CHILD PROCESSES inherit $TZ, so a shell `date`, an `ls` in a script, or a subprocess
#     that resolves its own zone lands on UTC rather than on the box's zone;
#   * the pin happens before the first local-module import, so nothing can have cached the
#     system zone yet (clock.py notes that timing is exactly why it must be at import).
#
# It does NOT fix DuckDB, which reads the SYSTEM zone rather than $TZ — that is what the
# explicit `SET TimeZone='UTC'` in db.connect() is for, and why a script opening its own
# connection must still set it. Nothing here should be read as covering that case.
#
# A script needing a genuine market-local day keeps it explicit (`ZoneInfo`), which is
# unaffected by this pin — ibkr_order_collector.py's Asia/Shanghai session day still works.
if os.environ.get("TZ") != "UTC":
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()               # re-read TZ for this process; absent on non-POSIX
    except AttributeError:
        pass
