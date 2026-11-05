"""US/CN code collisions must neither suppress equities nor delete their history."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import duckdb
from data.schema import history
from apps.data_ops import fetch_fundamentals as app


class FundamentalNamespaceTests(unittest.TestCase):
    def test_us_equities_survive_cn_registry_collisions(self):
        con=duckdb.connect(':memory:')
        con.execute('CREATE SCHEMA mh');history.ensure(con,prefix='mh.')
        con.execute('CREATE SCHEMA ref')
        con.execute('CREATE TABLE ref.futures_products(product TEXT)')
        con.execute("INSERT INTO ref.futures_products VALUES ('MA'),('MO')")
        con.execute("INSERT INTO mh.fundamentals_snapshot(day,symbol,market_cap,source) VALUES ('2001-01-01','MO',123,'yfinance_fast_info')")
        try:
            with patch('yfinance.Ticker') as ticker, patch('datasources.yahoo_session.create_session'):
                ticker.return_value.fast_info=SimpleNamespace(market_cap=1000,shares=10)
                n=app.mode_caps(con,['MO','MA','CN:CFFEX:MO','CN:CZCE:MA'])
            self.assertEqual(n,2)
            self.assertEqual([c.args[0] for c in ticker.call_args_list],['MO','MA'])
            self.assertEqual(con.execute("SELECT market_cap FROM mh.fundamentals_snapshot WHERE day=DATE '2001-01-01' AND symbol='MO'").fetchone()[0],123)
            self.assertEqual(con.execute("SELECT count(*) FROM mh.fundamentals_snapshot WHERE symbol LIKE 'CN:%'").fetchone()[0],0)
        finally:con.close()


    def test_missing_or_invalid_caps_do_not_create_fresh_empty_snapshots(self):
        with duckdb.connect(':memory:') as con:
            con.execute('CREATE SCHEMA mh');history.ensure(con,prefix='mh.')
            con.execute("INSERT INTO mh.fundamentals_snapshot(day,symbol,market_cap,source) VALUES ('2001-01-01','SPY',123,'yfinance_fast_info')")
            for mc, shares in [(None, None), (float('nan'), 10), (1000, 0)]:
                with patch('yfinance.Ticker') as ticker, patch('datasources.yahoo_session.create_session'):
                    ticker.return_value.fast_info=SimpleNamespace(market_cap=mc, shares=shares)
                    self.assertEqual(app.mode_caps(con,['SPY']),0)
                self.assertEqual(con.execute('SELECT day,market_cap FROM mh.fundamentals_snapshot').fetchall(),
                                 [(app.dt.date(2001,1,1),123.)])
