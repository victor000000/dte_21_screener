"""The insertion audit distinguishes proven nonempty literals from unknown lists."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from scripts import check_regressions as app


class InsertGuardTests(unittest.TestCase):
    def test_literal_cardinality_and_unknown_iterables(self):
        examples = [("[(1,), (2,)]", False), ("((1,),)", False),
                    ("[]", True), ("rows", True), ("[*rows]", True)]
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / 'fixture.py'
            for value, should_fail in examples:
                with self.subTest(value=value):
                    source.write_text(f'def f(con, rows):\n    con.executemany("INSERT INTO t VALUES (?)", {value})\n')
                    failures = []
                    with patch.object(app, 'ROOT', pathlib.Path(tmp)), patch.object(app, 'sources', return_value=[source]):
                        app.check_executemany(failures)
                    self.assertEqual(bool(failures), should_fail)
