import contextlib
import io
import pathlib
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import duckdb
import pandas as pd

from apps.screener import fetch_screen_futu as app
from data.schema import history


class FutuPanelUnitTests(unittest.TestCase):
    def test_low_and_high_percentage_iv_use_the_same_database_units(self):
        con=duckdb.connect(':memory:')
        for schema in ('mh','mhro','ref','yh'):
            con.execute(f'CREATE SCHEMA {schema}')
        history.ensure(con,prefix='mh.')
        con.execute('CREATE VIEW mhro.option_flow_daily AS SELECT * FROM mh.option_flow_daily')
        con.execute('CREATE TABLE ref.futures_products(product TEXT)')
        con.execute("INSERT INTO ref.futures_products VALUES ('MO'),('MA')")
        con.execute('CREATE TABLE yh.prices(symbol TEXT,date DATE,close DOUBLE)')
        con.execute("INSERT INTO yh.prices VALUES "
                    "('BIL','2026-10-15',100),('META','2026-10-15',700)")
        ctx=Mock()
        def quote(names):
            value=2.171 if names==['US.BIL'] else 43.784
            return 0,pd.DataFrame([{'iv':value,'iv_rank':25,'hv_30d':.245}])
        ctx.get_option_underlying_overview.side_effect=quote
        proxy=NS(execute=con.execute,close=lambda:None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                work=pathlib.Path(directory)/'tickers.txt'
                work.write_text('BIL\nMETA\nMO\nMA\nCN:CFFEX:MO\nCN:CZCE:MA\n')
                with patch('sys.argv',['fetch_screen_futu.py','--tickers-file',str(work)]), \
                        patch('futu.OpenQuoteContext',return_value=ctx), \
                        patch.object(app.db,'connect',return_value=proxy), \
                        patch.object(app,'throttle'),contextlib.redirect_stdout(io.StringIO()):
                    app.main()
            values=dict(con.execute('SELECT underlying,atm_iv FROM mh.iv_history').fetchall())
            self.assertAlmostEqual(values['BIL'],.02171)
            self.assertAlmostEqual(values['META'],.43784)
            self.assertAlmostEqual(values['MO'],.43784)
            self.assertAlmostEqual(values['MA'],.43784)
            self.assertEqual([c.args[0] for c in ctx.get_option_underlying_overview.call_args_list],
                             [['US.BIL'],['US.META'],['US.MO'],['US.MA']])
            self.assertEqual(con.execute("SELECT iv_rank FROM mh.option_flow_daily "
                                         "WHERE underlying='BIL'").fetchone()[0],25)
        finally:con.close()


    def test_staging_failure_closes_the_broker_context(self):
        ctx=Mock()
        with tempfile.TemporaryDirectory() as directory:
            work=pathlib.Path(directory)/'tickers.txt'
            work.write_text('MO\n')
            with patch('sys.argv',['fetch_screen_futu.py','--tickers-file',str(work)]), patch('futu.OpenQuoteContext',return_value=ctx), patch.object(app.db,'connect',side_effect=RuntimeError('staging locked')):
                with self.assertRaisesRegex(RuntimeError,'staging locked'):
                    app.main()
        ctx.close.assert_called_once()
        ctx.get_option_underlying_overview.assert_not_called()
