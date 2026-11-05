"""test_suite_size.py — the suite cannot SHRINK without someone saying so.

WHY THIS EXISTS. Nothing watched this. tests/test_harness.py ratchets which MODULES have tests
and tests/test_line_limit.py ratchets file sizes, but the NUMBER of tests was unguarded, and
it falls silently in ways neither of them sees:

  * a file renamed off the `test_*.py` pattern stops being discovered and reports nothing;
  * a class that no longer subclasses TestCase contributes zero tests, and passes;
  * a whole module guarded by a class-level skip counts as "covered" to the harness while
    running nothing at all.

None of those turns anything red. They just quietly make the green mean less.

The ratchet is a FLOOR, like the other two: it may only rise. Dropping it takes an explicit
`--update`, which is the point -- a suite that shrinks should require a decision, not a
merge.

    uv run python -m tests.test_suite_size --update
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "suite_baseline.json"


def discovered():
    """How many tests DISCOVERY sees -- the same entry point CI and check_all.sh use.

    Deliberately the loader and not a grep: a grep counts `def test_` lines, including ones
    inside classes that are never collected. This is the number that will actually run.
    """
    loader = unittest.TestLoader()
    return loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT)).countTestCases()


class TestSuiteSize(unittest.TestCase):
    def test_the_suite_has_not_shrunk(self):
        if not BASELINE.exists():
            self.fail(f"{BASELINE} is missing -- run "
                      f"`uv run python -m tests.test_suite_size --update`")
        floor = json.loads(BASELINE.read_text())["min_tests"]
        n = discovered()
        self.assertGreaterEqual(
            n, floor,
            f"the suite fell from {floor} to {n} tests. If a test was removed on purpose, "
            f"re-record the floor with `python -m tests.test_suite_size --update`; if not, "
            f"something stopped being COLLECTED, which is the failure this exists for.")

    def test_discovery_finds_a_suite_at_all(self):
        """A loader that finds nothing passes every floor. (The repo's own import sweep once
        went green on a broken import exactly this way.)"""
        self.assertGreater(discovered(), 100)


if __name__ == "__main__":
    if "--update" in sys.argv:
        n = discovered()
        BASELINE.write_text(json.dumps({
            "min_tests": n,
            "note": "Floor for tests/test_suite_size.py. It may only rise; lowering it is a "
                    "decision, which is what --update is for.",
        }, indent=1) + "\n")
        print(f"baseline written: {n} tests")
        sys.exit(0)
    unittest.main()
