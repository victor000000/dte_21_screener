import pathlib
import tempfile
import unittest
import warnings
from unittest.mock import patch
from apps.trade_log import source_dirs


class SourceMountTests(unittest.TestCase):
    def test_missing_source_is_visible_while_archives_remain_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);backup=base/'backup';backup.mkdir()
            saved=backup/'trades.csv';saved.write_text('archived')
            with patch.object(source_dirs,'SOURCE_DIRS',(base/'missing',backup)):
                with self.assertWarnsRegex(RuntimeWarning,'Restore the source mount'):
                    self.assertEqual(source_dirs.find('*.csv'),[str(saved)])

    def test_available_source_wins_without_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);source=base/'source';backup=base/'backup'
            source.mkdir();backup.mkdir()
            for folder in (source,backup):(folder/'trades.csv').write_text('data')
            with patch.object(source_dirs,'SOURCE_DIRS',(source,backup)),warnings.catch_warnings(record=True) as caught:
                self.assertEqual(source_dirs.find('*.csv'),[str(source/'trades.csv')])
            self.assertEqual(caught,[])
