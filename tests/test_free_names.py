"""test_free_names.py — every module's global names must resolve.

THE BUG THIS EXISTS FOR, found the first time a split moved code. The splitter
carried `canonical_snapshot_spots` into a new module with an import list that
was missing `datetime as dt`. The result compiled, imported, and passed every
check the gate has -- the name is only looked up when the function is CALLED --
and would have raised NameError the first time the risk profile ran for real.
A second module had the same fault, and no test covered either yet.

Nothing else in the gate can see this. `py_compile` cannot: a NameError is a
runtime lookup. The dotted-import sweep cannot: importing does not call. The
literal and fingerprint detectors cannot: no content changed. Only asking "is
every global name this module reads one it defines, imports, or gets from
builtins" finds it, and after 113 splits that question is asked 400+ times.

Scope-aware via `symtable`, not a hand-rolled AST walk: a first attempt flagged
a lambda parameter and a comprehension target as undefined, which is how a check
earns the reputation that lets a real finding be ignored.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bootstrap  # noqa: F401

# The scanner lives in _free_names.py so this file stays under the 100-line limit.
from tests._free_names import modules, undefined_names  # noqa: E402
from tests._scan import ROOT  # noqa: E402


class TestFreeNames(unittest.TestCase):
    def test_the_scanner_finds_modules(self):
        self.assertGreater(sum(1 for _ in modules()), 200)

    def test_no_module_references_an_undefined_global(self):
        bad = {}
        for p in modules():
            missing = undefined_names(p)
            if missing:
                bad[str(p.relative_to(ROOT))] = missing
        if bad:
            lines = "\n".join(f"   {k}: {v}" for k, v in sorted(bad.items())[:12])
            self.fail(f"{len(bad)} module(s) read a name they do not bind -- a split "
                      f"whose import list was incomplete, most likely:\n{lines}")

    def test_the_reporting_path_has_what_it_needs(self):
        # THE CRASH. `ROOT` was used only inside `if missing:` -- so the check
        # reported nothing while no module had a free name, and raised NameError the
        # first time one did. A gate that fails only when it has something to say is
        # a gate that never says it. Assert the name it reports with exists.
        self.assertTrue(str(ROOT))

    def test_the_check_catches_a_known_bad_module(self):
        # The check must be able to FAIL. A module reading a name it never binds
        # is exactly what canonical.py was, so assert the detector still sees it
        # -- otherwise a regression in this file turns the whole test green.
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        p = d / "broken.py"
        p.write_text("def f(con):\n    return dt.datetime.now()\n")
        self.assertEqual(undefined_names(p), ["dt"])

    def test_a_lambda_parameter_is_not_flagged(self):
        # The false positive that made the first version unusable.
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        p = d / "fine.py"
        p.write_text("def f(d):\n"
                     "    return sorted(d.items(), key=lambda x: -x[1])\n")
        self.assertEqual(undefined_names(p), [])


if __name__ == "__main__":
    unittest.main()
