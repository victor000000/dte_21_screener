"""Coverage export preserves unknown scope and records the pinned delivery release."""
import csv
import pathlib
import tempfile
import unittest
from unittest import mock
from apps.screener import us_screen_report as report
from apps.screener.us_screen_rules import assess
from tests.apps.screener.test_us_inventory import TODAY


class TestReport(unittest.TestCase):
    def test_unknown_scope_is_retained_in_coverage_not_counted_as_a_match(self):
        row = assess(dict(instrument='FUT:X:UNSPECIFIED', root='X', venue='UNSPECIFIED',
                          asset_class='future', listing_scope='unknown', optionability='optionability_unknown'),
                     [], {}, TODAY)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(report.bootstrap, 'ROOT', pathlib.Path(tmp)), \
                mock.patch.object(report.clock, 'today', return_value=TODAY):
            summary = report.write_reports([row], TODAY, 35, ['missing venue'], release='pinned-release')
            self.assertEqual(summary['release'], 'pinned-release')
            self.assertEqual(summary['listing_scopes'], {'unknown': 1})
            self.assertEqual(summary['matches'], 0)
            with (pathlib.Path(tmp) / 'reports/ivr_all_us_2026-10-18.csv').open() as f:
                saved = list(csv.DictReader(f))
            self.assertIn('MARKET_SCOPE_UNVERIFIED', saved[0]['status'])
