"""Reject corrupt evidence before accessing databases."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.trade_profile import cn_held_leg_report as m

class EvidenceIntegrity(unittest.TestCase):
    def test_bad_receipt_does_not_open_database(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'raw').write_text('changed')
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'files':[{'name':'raw','sha256':'invalid'}]}))
            with patch('sys.argv',['tool','--handoff',str(manifest)]+['--date', '2026-11-05', '--fx-report', 'missing.json']), \
                 patch.object(m.duckdb,'connect') as connect, \
                 patch.object(m.bs,'USING_QUANTLIB',True) if hasattr(m,'bs') else patch('builtins.print'):
                with self.assertRaises(AssertionError):
                    m.main()
                connect.assert_not_called()
