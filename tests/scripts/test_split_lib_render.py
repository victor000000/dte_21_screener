"""Tests for the spec helpers and the source rewrite.

Split out of test_split_lib.py: that file must stay under the 100-line limit
too, and the harness accepts `test_<stem>_*.py` for exactly this case.
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import split_lib as SL
from scripts import split_rewrite

SAMPLE = '''
def alpha():
    """One line."""
    return """SELECT a,
       b
    FROM t"""

def beta(x):
    return x
'''


def write(text):
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "sample.py"
    p.write_text(text)
    return p


class TestSpecHelpers(unittest.TestCase):
    def test_symbols_accepts_both_spec_shapes(self):
        bare = {"modules": {"a": ["x", "y"]}}
        rich = {"modules": {"a": {"symbols": ["x", "y"], "imports": ""}}}
        self.assertEqual(SL.symbols_of(bare), SL.symbols_of(rich))

    def test_duplicate_assignment_is_reported(self):
        # A symbol in two modules is emitted twice; the second copy silently wins
        # at import time and one module holds a function nothing calls.
        spec = {"modules": {"a": ["x"], "b": ["x"]}}
        self.assertEqual(SL.duplicate_assignments(spec), ["x"])

    def test_render_includes_imports_and_marks_the_module(self):
        defs = {"f": (None, "def f():\n    return 1")}
        text = SL.render("mod", ["f"], defs, "import os")
        self.assertIn('"""mod.py', text)
        self.assertIn("import os", text)
        self.assertIn("def f():", text)


class TestRewriteSource(unittest.TestCase):
    def test_removes_the_moved_span_and_keeps_the_rest(self):
        p = write(SAMPLE)
        _, _, defs = SL.top_level(p)
        split_rewrite.rewrite_source(p, defs, ["alpha"], [], "from pkg import alpha")
        after = p.read_text()
        self.assertNotIn("def alpha", after)
        self.assertIn("def beta", after)
        self.assertIn("from pkg import alpha", after)

    def test_it_does_not_touch_a_symbol_that_is_kept(self):
        # The hook that makes incremental passes possible: a function too long to
        # move stays in the source, and the rewrite must leave it byte-identical.
        p = write(SAMPLE)
        _, _, defs = SL.top_level(p)
        split_rewrite.rewrite_source(p, defs, ["alpha"], ["beta"], "")
        self.assertEqual(p.read_text().split("def beta(x):")[1],
                         "\n    return x\n")


if __name__ == "__main__":
    unittest.main()
