import contextlib
import datetime as dt
import io
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import duckdb
from ib_async import CommissionReport, Contract, Execution

from apps.trade_log import fetch_tws_ibkr as app


class ExecutionLegTests(unittest.TestCase):
    def test_combo_receipts_do_not_double_count_economic_fills(self):
        stamp = dt.datetime(2026,10,16,14,tzinfo=dt.timezone.utc)
        def execution(kind, key, side, strike, price):
            contract=Contract(secType=kind,symbol='CRWD',currency='USD',exchange='SMART',
                              lastTradeDateOrContractMonth='20261120' if kind=='OPT' else '',
                              strike=strike,right='C' if kind=='OPT' else '',localSymbol=key)
            record=Execution(execId=key,time=stamp,acctNumber=app.ACCOUNT,exchange='SMART',
                             side=side,shares=1,price=price,orderId=1,permId=100)
            return NS(contract=contract,execution=record,
                      commissionReport=CommissionReport(commission=.5))
        raw=[execution('BAG','summary','BOT',0,-2),
             execution('OPT','buy-leg','BOT',290,2),
             execution('OPT','sell-leg','SLD',270,4)]
        ib=Mock()
        ib.managedAccounts.return_value=[app.ACCOUNT]
        ib.reqExecutions.return_value=raw
        ib.reqPositions.return_value=[]
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            db=root/'trades.duckdb'
            con=duckdb.connect(str(db))
            con.execute("CREATE TABLE fills(ts_utc TIMESTAMP,ts_orig TEXT,account TEXT,"
                        "broker TEXT,underlying TEXT,symbol TEXT,security_type TEXT,"
                        "expiry DATE,strike DOUBLE,call_put TEXT,action TEXT,open_close TEXT,"
                        "qty INTEGER,price DOUBLE,fee DOUBLE,realized_pnl DOUBLE,"
                        "exchange TEXT,currency TEXT,source TEXT,notes TEXT)")
            con.execute("CREATE TABLE positions(underlying TEXT,expiry DATE,strike DOUBLE,"
                        "call_put TEXT,broker TEXT,qty DOUBLE)")
            con.close()
            with patch.object(app,'DB',db), patch('sys.argv',['fetch_tws_ibkr.py']), \
                    patch('ib_async.IB',return_value=ib), \
                    patch('datasources.tws.connect',return_value=ib), \
                    patch('apps.trade_log.broker_receipts.ROOT',root), \
                    contextlib.redirect_stdout(io.StringIO()):
                app.main()
                app.main()
            receipts=list((root/'var/raw/broker_receipts').glob('*.json'))
            self.assertEqual(len(receipts),2)
            self.assertEqual(len(json.loads(receipts[0].read_text())['executions']),3)
            with duckdb.connect(str(db)) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM fills').fetchone()[0],2)
                self.assertEqual(con.execute('SELECT DISTINCT security_type FROM fills').fetchall(),
                                 [('OPT',)])
