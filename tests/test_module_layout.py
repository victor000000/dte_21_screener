"""test_module_layout.py — the `__main__` guard must be the LAST statement.

THE BUG THIS EXISTS FOR. The first version of the splitter inserted the import
block after the last KEPT symbol, which in complete_risk_analysis.py put it
below:

    if __name__ == "__main__":
        main()

So running the script called main(), which called the first moved symbol, which
was not yet imported -- NameError every time. Every check stayed green:
py_compile cannot see a runtime lookup; the import sweep never runs the guard;
the free-names check sees the names as imported, just too late; and --help exits
near the top of the file. Only RUNNING the file finds it, and this is the static
form of that: guard last means nothing it calls is defined below it.
"""
import ast
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bootstrap  # noqa: F401

from tests._scan import ROOT


def main_guard_index(tree):
    """Index of the `if __name__ == "__main__":` node, or None."""
    for i, node in enumerate(tree.body):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in test.comparators)):
            return i
    return None


def modules():
    for layer in ("apps", "scripts", "datasources", "data", "compute",
                  "shared", "market_data"):
        base = ROOT / layer
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" not in p.parts:
                yield p


class TestMainGuardIsLast(unittest.TestCase):
    def test_the_scanner_finds_modules_with_guards(self):
        # A scanner that finds no guards passes every assertion below it.
        with_guard = 0
        for p in modules():
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            if main_guard_index(tree) is not None:
                with_guard += 1
        self.assertGreater(with_guard, 50, f"only {with_guard} guards found")

    def test_no_statement_follows_the_main_guard(self):
        bad = []
        for p in modules():
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            i = main_guard_index(tree)
            if i is None:
                continue
            tail = tree.body[i + 1:]
            if tail:
                bad.append(f"{p.relative_to(ROOT)}: "
                           f"{len(tail)} statement(s) after the guard, "
                           f"first is line {tail[0].lineno} "
                           f"({type(tail[0]).__name__})")
        self.assertFalse(bad, "the __main__ guard is not last -- anything it calls "
                              "below this line is a NameError when run as a script:\n  "
                              + "\n  ".join(sorted(bad)))

    def test_the_check_would_catch_the_real_case(self):
        # The exact shape complete_risk_analysis.py had after its first split.
        src = ("def main():\n    return helper()\n\n"
               "if __name__ == '__main__':\n    main()\n\n"
               "from pkg import helper\n")
        tree = ast.parse(src)
        i = main_guard_index(tree)
        self.assertIsNotNone(i)
        self.assertTrue(tree.body[i + 1:], "the detector missed a trailing import")


if __name__ == "__main__":
    unittest.main()
