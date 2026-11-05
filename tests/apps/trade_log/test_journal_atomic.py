import pathlib
import tempfile
import unittest
import duckdb
from apps.trade_log import load_journal as loader
from apps.trade_log.journal_fields import COLUMNS
from tests.apps.trade_log.test_load_journal import workbook, ENTRY


class JournalAtomicTests(unittest.TestCase):
    def test_mid_insert_failure_preserves_prior_revision(self):
        with tempfile.TemporaryDirectory() as tmp, duckdb.connect(':memory:') as con:
            path=pathlib.Path(tmp)/'journal.xlsx';workbook(path,[ENTRY,ENTRY])
            con.execute('CREATE TABLE journal_entries('+','.join(c+' VARCHAR' for c in COLUMNS)+')')
            con.execute("INSERT INTO journal_entries(source_file,major_plan) VALUES (?, 'saved')",[path.name])
            class Failing:
                inserts=0
                def execute(self,sql,params=None):
                    if sql.startswith('INSERT'):
                        self.inserts+=1
                        if self.inserts==2:raise RuntimeError('injected failure')
                    return con.execute(sql,params) if params is not None else con.execute(sql)
            with self.assertRaisesRegex(RuntimeError,'injected failure'):
                loader.load(path,Failing())
            self.assertEqual(con.execute('SELECT major_plan FROM journal_entries').fetchall(),[('saved',)])

    def test_empty_revision_does_not_delete_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import Mock
            path=pathlib.Path(tmp)/'journal.xlsx';workbook(path,[]);con=Mock()
            with self.assertRaisesRegex(ValueError,'existing journal retained'):
                loader.load(path,con)
            con.execute.assert_not_called()
