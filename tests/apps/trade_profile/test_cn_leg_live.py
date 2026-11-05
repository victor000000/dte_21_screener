import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from apps.trade_profile import cn_leg_live

class CNLiveReportTests(unittest.TestCase):
    def test_read_saved_report_does_not_acquire_quotes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cn_leg_live, 'OUT', Path(folder)), patch.object(cn_leg_live, 'refresh') as refresh:
            self.assertEqual(cn_leg_live.report()['legs'], [])
            (Path(folder)/'latest.json').write_text('{"legs":[{"symbol":"LC"}]}')
            self.assertEqual(cn_leg_live.report()['legs'][0]['symbol'],'LC')
            refresh.assert_not_called()

    def test_refresh_failure_does_not_replace_saved_profile(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cn_leg_live, 'OUT', Path(folder)), patch.object(cn_leg_live, 'refresh', side_effect=RuntimeError('source unavailable')):
            saved=Path(folder)/'latest.json';saved.write_text('{"legs":[]}')
            with patch.object(cn_leg_live, 'LAST_ATTEMPT', float('-inf')), patch.object(cn_leg_live, 'LAST_ERROR', None):
                self.assertIn('failed',cn_leg_live.report(update=True)['refresh_error'])
            self.assertEqual(saved.read_text(),'{"legs":[]}')

    def test_refresh_coalesces_requests_and_retries_after_cooldown(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cn_leg_live, 'OUT', Path(folder)), patch.object(cn_leg_live, 'LAST_ATTEMPT', float('-inf')), patch.object(cn_leg_live, 'LAST_ERROR', None), patch.object(cn_leg_live.time, 'monotonic', side_effect=[100,100,105]), patch.object(cn_leg_live, 'refresh', side_effect=RuntimeError() ) as fetch:
            (Path(folder)/'latest.json').write_text('{"legs":[]}')
            self.assertIn('failed',cn_leg_live.report(update=True)['refresh_error'])
            self.assertIn('failed',cn_leg_live.report(update=True)['refresh_error'])
            self.assertEqual(fetch.call_count,1)

    def test_ten_second_poll_tolerates_network_arrival_jitter(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cn_leg_live, 'OUT', Path(folder)), \
             patch.object(cn_leg_live, 'LAST_ATTEMPT', float('-inf')), \
             patch.object(cn_leg_live, 'LAST_ERROR', None), \
             patch.object(cn_leg_live.time, 'monotonic', side_effect=[100,100,101,109.8,109.8]), \
             patch.object(cn_leg_live, 'refresh', return_value={'legs':[]}) as fetch:
            cn_leg_live.report(update=True)
            cn_leg_live.report(update=True)
            self.assertEqual(fetch.call_count,1)
            result=cn_leg_live.report(update=True)
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(result['refresh_interval_seconds'],10)
