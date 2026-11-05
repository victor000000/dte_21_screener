"""Saved-screen UI retains historical provenance and failed gates."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from apps.screener.web_report import read_report


class WebReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        path=self.root/'ivr_all_us_2026-10-18.json'
        path.write_text(json.dumps({'asof':'2026-10-16','ivr_operator':'>','ivr_threshold':50}))
        with path.with_suffix('.csv').open('w') as handle:
            writer=csv.DictWriter(handle,fieldnames=['instrument','status','high_ivr'])
            writer.writeheader()
            writer.writerows([dict(instrument=f'S{i}',status='MATCH',high_ivr='True') for i in range(115)])
            writer.writerow(dict(instrument='BAD',status='STALE_IV',high_ivr='True'))

    def test_pagination_keeps_asof_and_excludes_failed_gates(self):
        first=read_report({},self.root)
        self.assertEqual(first['matched'],115);self.assertEqual(len(first['rows']),100)
        self.assertEqual(first['metadata']['asof'],'2026-10-16')
        second=read_report({'offset':['100']},self.root)
        self.assertEqual(len(second['rows']),15);self.assertIsNone(second['next_offset'])
        gaps=read_report({'mode':['high_ivr'],'search':['BAD']},self.root)
        self.assertEqual(gaps['rows'][0]['status'],'STALE_IV')

    def test_missing_and_invalid_filters(self):
        with self.assertRaises(ValueError):read_report({'offset':['-1']},self.root)
        with self.assertRaises(ValueError):read_report({'mode':['execute']},self.root)
        self.assertFalse(read_report({},self.root/'absent')['available'])

    def test_incomplete_new_report_does_not_hide_complete_one(self):
        (self.root/'ivr_all_us_2026-10-26.json').write_text('{}')
        self.assertEqual(read_report({},self.root)['report'],'ivr_all_us_2026-10-18.json')
