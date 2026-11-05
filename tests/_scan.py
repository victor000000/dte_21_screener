"""_scan.py — which source modules exist, and which have a test.

Kept out of test_harness.py so that file stays under the 100-line limit this
repo enforces on every Python file -- including its own tests. Not itself a test
module, and `tests/` is deliberately not in LAYERS, so this does not recurse.
"""
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "coverage_baseline.json"

# Same list the gate uses, for the same reason: a directory missing here is a
# directory whose modules are silently unchecked. Kept in step with REPO_PKGS
# in scripts/check_all.sh.
LAYERS = ["apps", "scripts", "datasources", "data", "compute", "shared", "market_data"]


def is_shim(path):
    head = path.read_text(errors="replace")[:1200]
    return "COMPATIBILITY SHIM" in head


def source_modules():
    """Every module that should have a test, as repo-relative paths."""
    out = []
    for layer in LAYERS:
        base = ROOT / layer
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts or p.name in ("__init__.py", "__main__.py"):
                continue
            if is_shim(p):
                continue
            out.append(p.relative_to(ROOT))
    return out


def test_path_for(rel):
    """`apps/plan/build_positions/spot.py` -> `tests/apps/plan/build_positions/test_spot.py`."""
    return ROOT / "tests" / rel.parent / f"test_{rel.stem}.py"


def is_covered(rel):
    """True if some test module covers this source module.

    Accepts `test_<stem>.py` OR `test_<stem>_<suffix>.py`, because the two rules
    collide for a module with a lot of behaviour: the test file must stay under
    100 lines too, so a thorough module legitimately needs two. Requiring exactly
    one file would force tests to be dropped to satisfy a size limit -- the wrong
    trade in both directions.
    """
    d = ROOT / "tests" / rel.parent
    if not d.is_dir():
        return False
    # Leading underscores are stripped: a private module `_state.py` naturally gets
    # `test_state.py`, and requiring `test__state.py` meant a test that existed
    # counted as missing -- the harness reporting a gap it had already been given.
    stem = rel.stem.lstrip("_")
    return any(p.name == f"test_{stem}.py" or p.name.startswith(f"test_{stem}_")
               for p in d.glob("test_*.py"))


def coverage():
    mods = source_modules()
    covered = [m for m in mods if is_covered(m)]
    return mods, covered
