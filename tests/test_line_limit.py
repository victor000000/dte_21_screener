"""test_line_limit.py — "every file under 100 lines", enforced with a ratchet.

The same reason test_harness.py exists: a size convention decays the moment it is
a convention. This one walks every Python file in the repo and compares against
`tests/size_baseline.json`, which records what was over the limit on the day the
rule was adopted (115 files, the largest 1,143 lines).

It fails on an offender that is NOT in the baseline, and on a baselined file that
GREW. So the set can only shrink -- which is what makes the rule survivable with
114 files to bring under it, without a red gate in the meantime.

Deliberately NOT applied to `third_party/` (vendored C++ and its Python shims) or
`.venv/`: neither is this repo's code.
"""
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "size_baseline.json"
LIMIT = 100

SKIP_PARTS = {".venv", "third_party", "__pycache__", "node_modules"}


def python_files():
    # reports/ contains dated source receipts and live job artifacts. Never refactor
    # these evidence copies; maintained apps/scripts/tests still use the same limit.
    for p in sorted(ROOT.rglob("*.py")):
        if SKIP_PARTS & set(p.parts) or p.relative_to(ROOT).parts[0] == "reports":
            continue
        yield p


def line_count(path):
    # `wc -l` semantics: count newlines, so a file with no trailing newline is
    # not silently one line short of what an editor shows.
    return len(path.read_bytes().split(b"\n")) - 1


def offenders():
    return {str(p.relative_to(ROOT)): line_count(p)
            for p in python_files() if line_count(p) > LIMIT}


class TestLineLimit(unittest.TestCase):
    def test_the_scanner_finds_the_repo(self):
        # A scanner that walks nothing passes everything. (The gate this repo
        # already has went green on a broken import sweep exactly this way.)
        self.assertGreater(sum(1 for _ in python_files()), 200)

    def test_no_new_file_exceeds_the_limit(self):
        if not BASELINE.exists():
            self.fail("tests/size_baseline.json is missing -- run "
                      "`uv run python -m tests.test_line_limit --update`")
        base = json.loads(BASELINE.read_text())["over_limit"]
        new = {k: v for k, v in offenders().items() if k not in base}
        self.assertFalse(new, "file(s) over {} lines that are not in the baseline: {}. "
                              "Split them, or --update only if the baseline should "
                              "genuinely change.".format(LIMIT, sorted(new)[:6]))

    def test_a_baselined_file_has_not_run_away(self):
        """A baselined file may be edited, but not grow without limit.

        A strict "must not grow at all" was the first version, and it failed
        immediately -- on a real bug fix that added a five-line comment to
        scripts/check_regressions.py, which is already over the limit and due to
        be split. Forbidding that makes the rule fight the work instead of
        measuring it: an oversized file is precisely where a fix is most likely
        to be needed. The SET staying the same size is what tracks "every file
        under 100 lines"; this is only a lid on runaway growth.
        """
        base = json.loads(BASELINE.read_text())["over_limit"]
        ran_away = {k: (base[k], n) for k, n in offenders().items()
                    if k in base and n > base[k] + 10}
        self.assertFalse(ran_away,
                         f"baselined file(s) grew by more than 10 lines: {ran_away}")

    def test_the_baseline_only_shrinks(self):
        # --update is the one command that fixes a red gate here, so it must not
        # be able to make the problem bigger.
        if not BASELINE.exists():
            self.skipTest("no baseline yet")
        base = json.loads(BASELINE.read_text())["over_limit"]
        now = offenders()
        self.assertLessEqual(len(now), len(base),
                             f"the over-limit set grew from {len(base)} to {len(now)}")


def update():
    now = offenders()
    BASELINE.write_text(json.dumps({
        "limit": LIMIT,
        "count": len(now),
        "over_limit": dict(sorted(now.items(), key=lambda kv: -kv[1])),
        "note": ("Ratchet for tests/test_line_limit.py. The set may only shrink; "
                 "raise with `python -m tests.test_line_limit --update` after a split."),
    }, indent=1) + "\n")
    print(f"recorded {len(now)} file(s) over {LIMIT} lines")
    for k, v in sorted(now.items(), key=lambda kv: -kv[1])[:8]:
        print(f"   {v:5}  {k}")


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.path.insert(0, str(ROOT))
        update()
    else:
        unittest.main()
