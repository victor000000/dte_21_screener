"""Twenty sessions and futures contract liquidity remain separate from stock share volume."""
import datetime as dt
import pathlib
import tempfile
import unittest
from apps.screener.us_screen_inputs import equity_metrics, futures_metrics
from tests.apps.screener.test_us_inventory import connection, TODAY


class TestInputs(unittest.TestCase):
    def test_equity_averages_and_missing_cap_remain_explicit(self):
        with connection() as con, tempfile.TemporaryDirectory() as tmp:
            for i in range(21):
                con.execute("INSERT INTO yh.prices VALUES ('TLT',?,80,10000000)",
                            [TODAY - dt.timedelta(days=i)])
            metrics = equity_metrics(con, pathlib.Path(tmp) / 'absent.json')['TLT']
        self.assertEqual(metrics['liquidity_sessions'], 20)
        self.assertEqual(metrics['avg_volume'], 10e6)
        self.assertEqual(metrics['volume_unit'], 'shares/day')
        self.assertIsNone(metrics['capitalization'])

    def test_futures_averages_use_one_unexpired_contract_and_source(self):
        with connection() as con:
            con.execute('CREATE TABLE mh.us_futures_contracts(source TEXT,contract_id TEXT,root TEXT,venue TEXT,sec_type TEXT,expiry DATE)')
            con.execute('CREATE TABLE mh.us_futures_daily(source TEXT,contract_id TEXT,root TEXT,venue TEXT,day DATE,close DOUBLE,volume DOUBLE)')
            for contract, expiry, volume in [('old', '2026-01-01', 999999),
                                             ('current', '2026-12-18', 1000),
                                             ('later', '2027-03-18', 10)]:
                con.execute("INSERT INTO mh.us_futures_contracts VALUES ('s',?,'ZN','CBOT','FUT',?)", [contract, expiry])
                for i in range(20):
                    con.execute("INSERT INTO mh.us_futures_daily VALUES ('s',?,'ZN','CBOT',?,100,?)",
                                [contract, TODAY - dt.timedelta(days=i), volume])
            metrics = futures_metrics(con, TODAY)[('ZN', 'CBOT')]
        self.assertEqual(metrics['liquidity_contract'], 'current')
        self.assertEqual(metrics['avg_volume'], 1000)
        self.assertEqual(metrics['liquidity_sessions'], 20)
        self.assertEqual(metrics['volume_unit'], 'contracts/day')
