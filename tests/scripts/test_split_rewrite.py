"""Tests for putting the moved spans back into the source file.

This half of the splitter is where the worst bug of the whole exercise came
from: the import block was anchored on the last KEPT symbol, which placed it
below `if __name__ == "__main__": main()` -- so the script ran, called a moved
symbol, and raised NameError, while every static check stayed green. The first
test below is that case, pinned.
"""
import ast
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import split_lib as SL
from scripts import split_rewrite as SR

HEADER = '''import os

import bootstrap

def kept():
    return 1

def moved():
    return 2

if __name__ == "__main__":
    kept()
'''


def write(text):
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "src.py"
    p.write_text(text)
    return p


class TestImportPlacement(unittest.TestCase):
    def test_imports_land_above_the_main_guard(self):
        # THE regression. main() calls the moved symbol, so an import below the
        # guard is a NameError on the first line of real work.
        p = write(HEADER)
        _, _, defs = SL.top_level(p)
        SR.rewrite_source(p, defs, ["moved"], ["kept"], "from pkg import moved")
        tree = ast.parse(p.read_text())
        lines = [n for n in tree.body]
        guard = next(i for i, n in enumerate(lines) if isinstance(n, ast.If))
        imp = next(i for i, n in enumerate(lines)
                   if isinstance(n, ast.ImportFrom) and n.module == "pkg")
        self.assertLess(imp, guard, "the import is below the guard -- NameError on run")

    def test_imports_land_after_the_header_imports_not_at_the_bottom(self):
        p = write(HEADER)
        _, _, defs = SL.top_level(p)
        SR.rewrite_source(p, defs, ["moved"], ["kept"], "from pkg import moved")
        text = p.read_text()
        self.assertLess(text.index("from pkg import moved"), text.index("def kept"))


class TestSpanRemoval(unittest.TestCase):
    def test_the_moved_definition_is_gone_and_the_kept_one_is_byte_identical(self):
        p = write(HEADER)
        _, _, defs = SL.top_level(p)
        before = p.read_text().split("def kept():")[1].split("def moved")[0]
        SR.rewrite_source(p, defs, ["moved"], ["kept"], "")
        after = p.read_text()
        self.assertNotIn("def moved", after)
        self.assertIn(before, after)

    def test_nothing_is_inserted_when_there_are_no_imports(self):
        p = write(HEADER)
        _, _, defs = SL.top_level(p)
        n_lines = len(p.read_text().splitlines())
        SR.rewrite_source(p, defs, ["moved"], ["kept"], "")
        self.assertLess(len(p.read_text().splitlines()), n_lines)


if __name__ == "__main__":
    unittest.main()
