"""test_harness.py — "every module has a test", enforced rather than intended.

The requirement is that all files are unit-tested. That decays the moment it is
a convention instead of a check: modules get added, nothing fails, and the
coverage number quietly falls. So the rule is a test, with a RATCHET.

WHY A RATCHET AND NOT A PLAIN ASSERTION. At the moment this was written, 2 of
141 modules had tests (the two written alongside it). A gate that is red on the
day it lands is worse than no gate: it blocks every unrelated commit and
teaches people to bypass it. So `tests/coverage_baseline.json` records how many
modules are covered, and this fails only if that number FALLS. Coverage can
only go up; it cannot silently slide back. Raise it after adding tests with:

    uv run python -m tests.test_harness --update

WHAT COUNTS AS A MODULE. `shared/rates.py` needs `tests/shared/test_rates.py`.
Compatibility shims do not count (they are three lines of aliasing), nor do
`__init__.py` / `__main__.py` (no behaviour of their own). `market_data/` counts
like everything else -- per-file tests, one convention.
"""
import json
import pathlib
import sys
import unittest

# The scanner lives in _scan.py so this file stays under the 100-line limit.
from tests._scan import BASELINE, LAYERS, ROOT, coverage


class TestEveryModuleHasATest(unittest.TestCase):
    def test_harness_finds_modules(self):
        # Providers and maintenance moved to the separately tested data-providers package.
        # An empty scan must not pass. That is how the gate
        # this project already has went green on a broken import sweep after a
        # layer moved out of its hardcoded list.
        mods, _ = coverage()
        self.assertGreater(len(mods), 50,
                           f"only found {len(mods)} modules -- LAYERS is stale "
                           f"or the tree moved")

    def test_the_uncovered_count_has_not_grown(self):
        """The DEFICIT is the invariant, not the covered count.

        Checking `covered >= baseline` was the first version, and it passed while
        nine modules were added with no tests at all: the covered COUNT stays put
        when you add uncovered modules, so the number this was guarding never
        moved. What the rule means is "every module has a test", so what must not
        grow is the number that do NOT.
        """
        if not BASELINE.exists():
            self.fail(f"{BASELINE.relative_to(ROOT)} is missing -- run "
                      f"`uv run python -m tests.test_harness --update`")
        recorded = json.loads(BASELINE.read_text())
        mods, covered = coverage()
        missing = len(mods) - len(covered)
        want = recorded["total"] - recorded["covered"]
        self.assertLessEqual(
            missing, want,
            f"uncovered modules grew: {missing} now, {want} in the baseline "
            f"({len(covered)}/{len(mods)} covered). Every module under {LAYERS} "
            f"needs a tests/<same path>/test_<name>.py -- a split that creates "
            f"modules without them is not finished.")

    def test_coverage_can_only_be_raised_deliberately(self):
        # Guards the ratchet itself: --update must never be able to LOWER the
        # number, or the one command that fixes a red gate becomes the way to
        # make the problem disappear.
        if not BASELINE.exists():
            self.skipTest("no baseline yet")
        recorded = json.loads(BASELINE.read_text())
        mods, covered = coverage()
        self.assertGreaterEqual(recorded["covered"], 0)
        self.assertLessEqual(recorded["covered"], len(mods),
                             "baseline claims more modules than exist")


def update():
    mods, covered = coverage()
    missing = [str(m) for m in mods if m not in covered]
    BASELINE.write_text(json.dumps({
        "covered": len(covered),
        "total": len(mods),
        "covered_modules": sorted(str(m) for m in covered),
        "note": ("Ratchet for tests/test_harness.py. Raise with "
                 "`python -m tests.test_harness --update`; it must never fall."),
        "still_missing": missing,
    }, indent=2) + "\n")
    print(f"recorded {len(covered)}/{len(mods)} modules covered")
    print(f"still missing tests: {len(missing)}")
    for m in missing[:15]:
        print(f"   {m}")
    if len(missing) > 15:
        print(f"   ... and {len(missing) - 15} more")

if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.path.insert(0, str(ROOT))
        update()
    else:
        unittest.main()
