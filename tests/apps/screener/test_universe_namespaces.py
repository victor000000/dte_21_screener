"""The mixed watchlist keeps CN futures away from equity vendors."""
import datetime as dt
import duckdb
from types import SimpleNamespace
import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest.mock import Mock,patch
import pandas as pd
from shared.files import safe_read_ticker_file
from apps.screener import screener_21dte as app

ROOT=pathlib.Path(__file__).resolve().parents[3]


class UniverseNamespaceTests(unittest.TestCase):
    @unittest.skipUnless((app.bootstrap.DATA_ROOT/"plans/screener_universe.txt").exists(),
                         "Provider runtime watchlist is not distributed in public source")
    def test_default_watchlist_identifies_cn_venues(self):
        names=set(safe_read_ticker_file(app.bootstrap.DATA_ROOT/'plans/screener_universe.txt'))
        self.assertTrue({'CN:CZCE:MA','CN:INE:SC','CN:CFFEX:MO'}<=names)

    def test_legacy_screen_requests_the_us_equity_and_skips_cn_keys(self):
        con=Mock();con.execute.return_value.fetchall.return_value=[]
        frame=pd.DataFrame(columns=['Close','High','Low'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',pathlib.Path(tmp)), patch.object(app,'SYMS',['MO','CN:CFFEX:MO','CN:CZCE:MA']), patch.object(app.db,'connect',return_value=con) as connect, patch.object(app.yf,'Ticker') as ticker, contextlib.redirect_stdout(io.StringIO()):
            ticker.return_value.history.return_value=frame
            app.main()
            self.assertEqual(ticker.call_count,1)
            self.assertEqual(ticker.call_args.args,('MO',))
            connect.assert_called_once_with(history='rw')


class LegacyScreenPersistenceTests(unittest.TestCase):
    def test_repeated_screen_refreshes_iv_without_losing_a_run(self):
        con=duckdb.connect(':memory:')
        con.execute("ATTACH ':memory:' AS mh")
        con.execute('CREATE TABLE positions(underlying TEXT,expiry DATE)')
        con.execute('CREATE TABLE mh.iv_history(day DATE,underlying TEXT,expiry DATE,atm_iv DOUBLE,spot DOUBLE,source TEXT,PRIMARY KEY(source,underlying,day))')
        index=pd.date_range(end=pd.Timestamp(app.clock.today())-pd.Timedelta(days=1),periods=100)
        close=[100+i*.05 for i in range(100)]
        frame=pd.DataFrame({'Close':close,'High':[x+1 for x in close],'Low':[x-1 for x in close],'Volume':[2000000]*100},index=index)
        expiry=(app.clock.today()+dt.timedelta(days=45)).isoformat()
        chain=pd.DataFrame({'strike':[100.], 'impliedVolatility':[.4], 'bid':[5.], 'ask':[5.2], 'openInterest':[1000], 'volume':[100]})
        ticker=SimpleNamespace(history=lambda **kwargs:frame,options=[expiry],option_chain=lambda exp:SimpleNamespace(calls=chain,puts=chain))
        proxy=SimpleNamespace(execute=con.execute,close=lambda:None)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',pathlib.Path(tmp)), patch.object(app,'SYMS',['XYZ']), patch.object(app.db,'connect',return_value=proxy), patch.object(app.yf,'Ticker',return_value=ticker), contextlib.redirect_stdout(io.StringIO()):
                app.main()
                app.main()
            self.assertEqual(con.execute('SELECT count(*) FROM mh.iv_history').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT count(*) FROM screener_runs').fetchone()[0],2)
        finally:con.close()
