import datetime as dt
import unittest
import pathlib
import tempfile
from types import SimpleNamespace as NS

import duckdb

from apps.plan.us_book import us_book
from apps.trade_log.position_costs import save_schwab, save_tws, statement_day, write_schwab
from data.schema import broker_costs


class BrokerCostTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.stamp = dt.datetime(2026, 10, 16, 14)
        self.expiry = dt.date(2026, 11, 20)
        self.con.execute("CREATE TABLE broker_positions(as_of TIMESTAMP,account TEXT,"
                         "broker TEXT,underlying TEXT,sec_type TEXT,symbol TEXT,expiry DATE,"
                         "strike DOUBLE,call_put TEXT,currency TEXT,qty DOUBLE)")
        self.con.execute("CREATE TABLE fills(account TEXT,symbol TEXT,qty DOUBLE,price DOUBLE,"
                         "open_close TEXT,underlying TEXT,expiry DATE,strike DOUBLE,"
                         "call_put TEXT,ts_utc TIMESTAMP)")
        self.con.execute("INSERT INTO broker_positions VALUES "
                         "(?,'A','IBKR','CRWD','OPT','call',?,270,'C','USD',-5)",
                         [self.stamp,self.expiry])
        self.con.execute("INSERT INTO fills VALUES "
                         "('A','call',5,1,'OPEN','CRWD',?,270,'C','2025-01-01')",[self.expiry])

    def tearDown(self):
        self.con.close()

    def save_cost(self, stamp=None, qty=-5):
        broker_costs.write(self.con, [[stamp or self.stamp,'A','IBKR','CRWD',
                                      self.expiry,270,'C',qty,4.426,'broker']])

    def test_broker_cost_overrides_average_from_an_older_episode(self):
        self.save_cost()
        self.assertEqual(us_book(self.con, [])[0][-1], 4.426)

    def test_changed_quantity_rejects_previous_cost(self):
        self.save_cost(qty=-4)
        self.assertEqual(us_book(self.con, [])[0][-1], 1)

    def test_intervening_trade_rejects_previous_cost(self):
        self.save_cost(stamp=self.stamp-dt.timedelta(hours=2))
        self.con.execute("INSERT INTO fills VALUES "
                         "('A','call',1,2,'CLOSE','CRWD',?,270,'C','2026-10-16 13:00')",
                         [self.expiry])
        self.assertEqual(us_book(self.con, [])[0][-1], 1)

    def test_broker_parsers_preserve_reported_unit_costs(self):
        contract = NS(secType='OPT',lastTradeDateOrContractMonth='20261120',
                      multiplier='100',symbol='CRWD',strike=270,right='C')
        save_tws(self.con,[NS(account='A',contract=contract,position=-5,avgCost=442.6)],self.stamp)
        self.assertAlmostEqual(us_book(self.con, [])[0][-1],4.426)
        row=['CRWD','unused','20 Nov 26','290','CALL','-3','5.00']
        pos=[[self.stamp,'S','Schwab','CRWD','OPT','other',self.expiry,290,'C','USD',-3]]
        save_schwab(self.con,[row],pos,'statement')
        self.assertEqual(self.con.execute("SELECT avg_price FROM broker_position_costs "
                                          "WHERE account='S'").fetchone()[0],5)

    def test_reimport_keeps_the_statements_own_account_date(self):
        self.con.execute('CREATE TABLE account_daily(day DATE,account TEXT,currency TEXT,'
                         'net_liq DOUBLE,available DOUBLE,source TEXT,notes TEXT,'
                         'PRIMARY KEY(day,account,source))')
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'2026-10-16-AccountStatement.csv'
            path.write_text('Account Statement for S on 10/05/26 12:34:56\n')
            write_schwab(self.con,[],[],[],{'Net Liquidating Value':123},[],
                         'statement',day=statement_day(path))
        self.assertEqual(self.con.execute('SELECT day FROM account_daily').fetchone()[0],
                         dt.date(2026,10,5))
