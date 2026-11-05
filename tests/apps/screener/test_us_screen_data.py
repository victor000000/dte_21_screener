"""Typed futures IV cannot pool sources, tenors or methods to manufacture a rank."""
import datetime as dt
import unittest
from apps.screener.us_screen_data import futures_iv
from compute.iv_rank import rank_series
from tests.apps.screener.test_us_inventory import connection, TODAY


def typed_table(con):
    con.execute('CREATE TABLE mh.us_futures_iv(source TEXT,venue TEXT,root TEXT,series_id TEXT,'
                'tenor_days DOUBLE,moneyness_method TEXT,roll_method TEXT,model TEXT,'
                'method_version TEXT,day DATE,atm_iv DOUBLE)')


class TestTypedIV(unittest.TestCase):
    def test_different_tenors_and_models_cannot_combine_into_sixty_sessions(self):
        for difference in ('source', 'tenor', 'model'):
            with self.subTest(difference=difference), connection() as con:
                typed_table(con)
                for i in range(60):
                    second = i >= 30
                    source = 'other' if difference == 'source' and second else 'ibkr'
                    tenor = 60 if difference == 'tenor' and second else 30
                    model = 'other' if difference == 'model' and second else 'reported'
                    con.execute("INSERT INTO mh.us_futures_iv VALUES (?,'CME','ES','CME:ES:series',?,'ATM','continuous',?,'v1',?,?)",
                                [source, tenor, model, TODAY-dt.timedelta(days=59-i), .1+i*.001])
                per, methods = futures_iv(con)
                result = rank_series(per['ES:CME'])
                self.assertEqual(result['n'], 30)
                self.assertIsNone(result['ivr'])
                self.assertEqual(len(methods), 2)

    def test_valid_series_retains_methodology_and_uses_range_rank(self):
        with connection() as con:
            typed_table(con)
            for i, iv in enumerate([.1] * 58 + [1.1, .2]):
                con.execute("INSERT INTO mh.us_futures_iv VALUES ('ibkr','CME','ES','CME:ES:s',30,'unknown','continuous','reported','v1',?,?)",
                            [TODAY-dt.timedelta(days=59-i), iv])
            per, methods = futures_iv(con)
            result = rank_series(per['ES:CME'])
        self.assertAlmostEqual(result['ivr'], 10)
        self.assertGreater(result['ivp'], 98)
        metadata = methods[result['source']]
        self.assertEqual(metadata['iv_source'], 'ibkr')
        self.assertEqual(metadata['iv_series_id'], 'CME:ES:s')
        self.assertEqual(metadata['iv_tenor_days'], 30)

    def test_wrong_venue_identity_is_rejected_instead_of_relabelled(self):
        with connection() as con:
            typed_table(con)
            con.execute("INSERT INTO mh.us_futures_iv VALUES ('s','CME','ES','CBOT:ZN:s',30,'ATM','r','m','v',?,.2)", [TODAY])
            with self.assertRaisesRegex(ValueError, 'identity'):
                futures_iv(con)
