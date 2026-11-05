import datetime as dt
import math
import duckdb
import unittest
from unittest.mock import patch
from apps.trade_profile import strategy_quantification_20261025 as source
from apps.trade_profile.strategy_history import load

class StrategyHistory(unittest.TestCase):
    def test_flat_iv_window_is_not_fabricated_rank(self):
        con=duckdb.connect(':memory:')
        try:
            con.execute('create table underlying_minutes(symbol varchar,ts_utc timestamp,close double)')
            con.execute('create table iv_history(underlying varchar,day date,atm_iv double,source varchar)')
            days=[dt.date(2025,1,1)+dt.timedelta(days=i) for i in range(280)]
            con.executemany('insert into underlying_minutes values (?,?,?)',
                            [('ABC',d,100+math.sin(i)) for i,d in enumerate(days)])
            con.executemany('insert into iv_history values (?,?,?,?)',
                            [('ABC',d,.3,'ibkr_tws30d') for d in days])
            with patch.multiple(source,NAMES=['ABC'],H=21):
                result=load(con)['ABC']
        finally:
            con.close()
        self.assertGreater(len(result),0)
        self.assertTrue(all(r['ivr'] is None and r['pct']==0 for r in result))
        self.assertTrue(all(r['fwd']>0 for r in result))
