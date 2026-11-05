"""A failed book rebuild must preserve the complete previous book on disk."""
import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from apps.plan import build_positions as bp


class TestAtomicRebuild(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.db = self.root / "trades.duckdb"
        duckdb.connect(str(self.root / "market_history.duckdb")).close()
        with duckdb.connect(str(self.db)) as con:
            con.execute("CREATE TABLE positions(marker TEXT)")
            con.execute("INSERT INTO positions VALUES ('complete previous book')")
            con.execute("CREATE TABLE classifications(marker TEXT)")
            con.execute("INSERT INTO classifications VALUES ('previous classes')")
        self.stack = self.enterContext(contextlib.ExitStack())
        self.stack.enter_context(patch.object(bp, "DB", self.db))
        self.stack.enter_context(patch.object(bp.bootstrap, "DATA_ROOT", self.root))
        self.book = self.stack.enter_context(patch.object(bp, "us_book", return_value=[]))
        self.stack.enter_context(patch.object(bp.broker_marks_mod, "for_book", return_value={}))
        self.cn = self.stack.enter_context(patch.object(bp.cn_book, "store"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def assert_previous_book(self):
        with duckdb.connect(str(self.db), read_only=True) as con:
            self.assertEqual(con.execute("SELECT * FROM positions").fetchall(),
                             [("complete previous book",)])
            self.assertEqual(con.execute("SELECT * FROM classifications").fetchall(),
                             [("previous classes",)])

    def test_a_failure_before_the_first_leg_preserves_the_old_book(self):
        self.book.side_effect = RuntimeError("source failed")
        with self.assertRaisesRegex(RuntimeError, "source failed"):
            bp.main()
        self.assert_previous_book()

    def test_an_interruption_after_writing_a_leg_rolls_back_the_whole_build(self):
        def interrupt(con, sector):
            con.execute("INSERT INTO positions(underlying) VALUES ('partial')")
            raise KeyboardInterrupt()
        self.cn.side_effect = interrupt
        with self.assertRaises(KeyboardInterrupt):
            bp.main()
        self.assert_previous_book()

    def test_a_complete_build_commits_positions_and_classifications_together(self):
        def store(con, sector):
            con.execute("INSERT INTO positions(underlying) VALUES ('new book')")
            return 1
        self.cn.side_effect = store
        bp.main()
        with duckdb.connect(str(self.db), read_only=True) as con:
            self.assertEqual(con.execute("SELECT underlying FROM positions").fetchall(), [("new book",)])
            self.assertEqual(con.execute("SELECT underlying FROM classifications").fetchall(), [("new book",)])
            self.assertIsNotNone(con.execute("SELECT as_of FROM positions").fetchone()[0])
