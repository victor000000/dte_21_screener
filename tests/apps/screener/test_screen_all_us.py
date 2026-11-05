"""Default screening discovers futures and equities before filters and reports missing roots."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock
from apps.screener import screen_all_us as app, screener_21dte_v2 as old
from tests.apps.screener.test_us_inventory import connection, TODAY
from tests.apps.screener.test_us_screen_data import typed_table


class TestAllUS(unittest.TestCase):
    def test_short_typed_history_is_not_filled_from_legacy_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = connection()
            typed_table(con)
            for i in range(60):
                day = TODAY - dt.timedelta(days=59-i)
                con.execute("INSERT INTO mh.iv_history VALUES ('ES:CME','ibkr',?,?)", [day, .1+i*.001])
                if i >= 30:
                    con.execute("INSERT INTO mh.us_futures_iv VALUES ('ibkr','CME','ES','CME:ES:s',30,'unknown','continuous','reported','v1',?,?)", [day, .1+i*.001])
            with mock.patch.object(app, 'open_snapshot', return_value=(con, 'typed-release')), \
                    mock.patch.object(app.bootstrap, 'ROOT', pathlib.Path(tmp)), \
                    mock.patch.object(app.bootstrap, 'DATA_ROOT', pathlib.Path(tmp)), \
                    mock.patch.object(app.clock, 'today', return_value=TODAY):
                result = app.run()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['iv_sessions'], 30)
            self.assertIsNone(result[0]['ivr'])
            self.assertEqual(result[0]['iv_source'], 'ibkr')
            self.assertEqual(result[0]['iv_delivery'], 'us_futures_iv')

    def test_default_v2_routes_to_broad_inventory_without_equity_log_writes(self):
        with mock.patch('sys.argv', ['screen']), mock.patch.object(app, 'run') as run, \
                mock.patch.object(old.db, 'connect', side_effect=AssertionError('legacy log write')):
            old.main()
        run.assert_called_once_with()

    def test_colliding_equity_and_future_use_their_own_iv_and_missing_roots_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = connection()
            con.execute("INSERT INTO yh.symbols VALUES ('ES')")
            con.execute("INSERT INTO ref.option_contracts VALUES ('ES','2026-12-18',?)", [TODAY])
            con.execute("INSERT INTO mh.us_futures_products VALUES ('ES','CME'),('ZN','CBOT')")
            con.execute("INSERT INTO mh.us_futures_option_chains VALUES ('ES','CME',?,'[\"20261218\"]','[100]')", [TODAY])
            for i in range(60):
                day = TODAY - dt.timedelta(days=59-i)
                con.execute("INSERT INTO mh.iv_history VALUES ('ES','s',?,?)", [day, 0.1 if i == 59 else 0.2])
                con.execute("INSERT INTO mh.iv_history VALUES ('ES:CME','s',?,?)", [day, 0.2 if i == 59 else 0.1])
                con.execute("INSERT INTO yh.prices VALUES ('ES',?,100,10000000)", [day])
            with mock.patch.object(app, 'open_snapshot', return_value=(con, 'test-release')), \
                    mock.patch.object(app.bootstrap, 'ROOT', pathlib.Path(tmp)), \
                    mock.patch.object(app.bootstrap, 'DATA_ROOT', pathlib.Path(tmp)), \
                    mock.patch('apps.screener.us_screen_report.bootstrap.ROOT', pathlib.Path(tmp)), \
                    mock.patch.object(app.clock, 'today', return_value=TODAY):
                result = {r['instrument']: r for r in app.run()}
            self.assertEqual(result['ES']['ivr'], 0)
            self.assertEqual(result['FUT:ES:CME']['ivr'], 100)
            self.assertIn('UNRANKABLE', result['FUT:ZN:CBOT']['status'])
            text = (pathlib.Path(tmp) / 'reports/ivr_all_us_2026-10-18.md').read_text()
            self.assertIn('FUT:ZN:CBOT', text)
            self.assertTrue((pathlib.Path(tmp) / 'reports/ivr_all_us_2026-10-18.csv').exists())
