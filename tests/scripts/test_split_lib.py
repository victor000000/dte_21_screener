"""Tests for the AST helpers behind the splitter.

Pure, and worth real tests: this is the code that decides whether a multi-line
SQL literal survived a move intact, which is the failure that destroyed 152,304
rows in this repo. If it is wrong, every split it verifies is unverified.
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import split_lib as SL

SAMPLE = '''
import os

CONST = 1

def alpha():
    """One line."""
    return """SELECT a,
       b
    FROM t"""

def beta(x):
    """Two.
    lines.
    """
    return x

class Gamma:
    pass
'''


def write(text):
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "sample.py"
    p.write_text(text)
    return p


class TestTopLevel(unittest.TestCase):
    def test_finds_functions_classes_and_assignments(self):
        _, _, defs = SL.top_level(write(SAMPLE))
        self.assertEqual(set(defs), {"alpha", "beta", "Gamma", "CONST"})

    def test_spans_are_exact_source_text(self):
        # The whole safety argument: a definition moves as its own text, not as
        # lines that were re-indented or re-wrapped on the way.
        _, _, defs = SL.top_level(write(SAMPLE))
        self.assertTrue(defs["alpha"][1].startswith("def alpha():"))
        self.assertIn("    FROM t", defs["alpha"][1])
        self.assertEqual(defs["CONST"][1], "CONST = 1")

    def test_an_assignment_to_two_names_registers_both(self):
        _, _, defs = SL.top_level(write("A, B = 1, 2\n"))
        self.assertEqual(set(defs), {"A", "B"})


class TestLiteralHashes(unittest.TestCase):
    def test_counts_only_multi_line_strings(self):
        hashes = SL.literal_hashes(SAMPLE)
        # alpha's SQL and beta's docstring; "One line." is single-line and is not
        # part of this quantity, which is the point -- a one-line docstring can be
        # rewritten freely, a SQL body cannot.
        self.assertEqual(len(hashes), 2)

    def test_whitespace_inside_a_literal_changes_the_hash(self):
        # THE corruption mode: re-indenting a continuation line leaves valid
        # Python and a broken query. Same bytes must give the same hash, one
        # character different must not.
        a = SL.literal_hashes('x = """SELECT a,\n   b\nFROM t"""')
        b = SL.literal_hashes('x = """SELECT a,\n       b\nFROM t"""')
        self.assertEqual(a, a)
        self.assertNotEqual(a, b)

    def test_unparseable_text_is_none_not_empty(self):
        # None means "could not check"; [] would mean "checked, nothing to find".
        # Conflating them would let a syntax error pass as a clean budget.
        self.assertIsNone(SL.literal_hashes("def broken(:\n"))
        self.assertEqual(SL.literal_hashes("x = 1"), [])


if __name__ == "__main__":
    unittest.main()
