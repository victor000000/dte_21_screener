import datetime as dt
import unittest

import duckdb

from apps.audit.check_broker_list import check


class CNBrokerKeyTests(unittest.TestCase):
    def run_check(self, quantity=-31, expiry=dt.date(2026,12,11)):
        stamp=dt.datetime(2026,10,16,14)
        con=duckdb.connect(':memory:')
        con.execute('CREATE TABLE broker_positions(broker TEXT,as_of TIMESTAMP,'
                    'underlying TEXT,expiry DATE,strike DOUBLE,call_put TEXT,qty DOUBLE)')
        con.execute("INSERT INTO broker_positions VALUES "
                    "('浙商期货',?,'MA2701',?,2900,'P',?)",[stamp,expiry,quantity])
        row=[None]*19
        row[0:2]=['浙商期货','MA701']
        row[3:7]=[dt.date(2026,12,11),2900,'P',-31]
        row[18]=stamp
        results=[]
        try:
            check(con,[row],lambda *a,**k:results.append(a))
            return results[0][2]
        finally:con.close()

    def test_delivery_formats_match(self):
        self.assertTrue(self.run_check())

    def test_quantity_difference_still_fails(self):
        self.assertFalse(self.run_check(quantity=-30))

    def test_expiry_difference_still_fails(self):
        self.assertFalse(self.run_check(expiry=dt.date(2027,12,11)))


class BrokerSymbolShapeTests(unittest.TestCase):
    def test_cn_symbol_matches_its_structured_leg(self):
        from apps.audit.broker_keys import valid_broker_symbol
        self.assertTrue(valid_broker_symbol('浙商期货', 'MA2701-P-2900', 'MA701', 2900, 'P'))
        self.assertTrue(valid_broker_symbol('浙商期货', 'ru2701-C-22500', 'RU2701', 22500, 'C'))

    def test_cn_shaped_symbol_does_not_bypass_us_validation(self):
        from apps.audit.broker_keys import valid_broker_symbol
        self.assertFalse(valid_broker_symbol('IBKR', 'MA2701-P-2900', 'MA701', 2900, 'P'))

    def test_mismatched_strike_and_delivery_are_rejected(self):
        from apps.audit.broker_keys import valid_broker_symbol
        self.assertFalse(valid_broker_symbol('浙商期货', 'MA2701-P-2900', 'MA701', 3000, 'P'))
        self.assertFalse(valid_broker_symbol('浙商期货', 'MA2701-P-2900', 'MA702', 2900, 'P'))
        self.assertFalse(valid_broker_symbol('浙商期货', 'MA2701-P-2900', 'MA1701', 2900, 'P'))

    def test_us_occ_and_unparsed_statement_strings(self):
        from apps.audit.broker_keys import valid_broker_symbol
        self.assertTrue(valid_broker_symbol('IBKR', 'META261120C00820000', 'META', 820, 'C'))
        self.assertFalse(valid_broker_symbol('Schwab', '100 20 NOV 26 220 PUT', 'META', 220, 'P'))
