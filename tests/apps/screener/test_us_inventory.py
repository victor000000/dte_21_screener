"""All discovered classes stay visible; equity and futures root collisions are impossible."""
import datetime as dt
import unittest
import duckdb
from apps.screener.us_inventory import inventory, table_exists

TODAY = dt.date(2026, 10, 18)


def connection():
    con = duckdb.connect(':memory:')
    con.execute('CREATE SCHEMA mh; CREATE SCHEMA ref; CREATE SCHEMA yh')
    con.execute('CREATE TABLE yh.symbols(symbol TEXT)')
    con.execute('CREATE TABLE mh.iv_history(underlying TEXT,source TEXT,day DATE,atm_iv DOUBLE)')
    con.execute('CREATE TABLE yh.prices(symbol TEXT,date DATE,close DOUBLE,volume DOUBLE)')
    con.execute('CREATE TABLE ref.option_contracts(underlying TEXT,expiry DATE,last_seen DATE)')
    con.execute('CREATE TABLE mh.us_futures_products(product_code TEXT,venue TEXT)')
    con.execute('CREATE TABLE mh.us_futures_option_chains(root TEXT,venue TEXT,day DATE,expirations JSON,strikes JSON)')
    return con


class TestInventory(unittest.TestCase):
    def test_full_catalog_and_bond_funds_survive_before_strategy_filtering(self):
        with connection() as con:
            con.execute("INSERT INTO yh.symbols VALUES ('CL'),('TLT'),('NO_OPTIONS')")
            con.execute("INSERT INTO mh.us_futures_products VALUES ('CL','NYMEX'),('NEW','CBOT')")
            con.execute("INSERT INTO mh.us_futures_option_chains VALUES ('CL','NYMEX',?,'[\"20261218\"]','[60]')", [TODAY])
            con.execute("INSERT INTO ref.option_contracts VALUES ('TLT','2026-12-18',?)", [TODAY])
            rows = {r['instrument']: r for r in inventory(con, TODAY)}
        self.assertIn('CL', rows)
        self.assertIn('FUT:CL:NYMEX', rows)
        self.assertIn('FUT:NEW:CBOT', rows)
        self.assertIn('NO_OPTIONS', rows)
        self.assertEqual(rows['FUT:CL:NYMEX']['series_label'], 'CL:NYMEX')
        self.assertEqual(rows['FUT:NEW:CBOT']['optionability'], 'optionability_unknown')
        self.assertEqual(rows['TLT']['optionability'], 'unexpired_contract_observed')

    def test_expired_chain_is_not_current_optionability_evidence(self):
        with connection() as con:
            con.execute("INSERT INTO mh.us_futures_option_chains VALUES ('ZN','CBOT',?,'[\"20250101\"]','[100]')", [TODAY])
            row = inventory(con, TODAY)[0]
        self.assertEqual(row['instrument'], 'FUT:ZN:CBOT')
        self.assertEqual(row['optionability'], 'optionability_unknown')

    def test_catalog_scope_and_mixed_definition_types_are_preserved(self):
        with connection() as con:
            con.execute('ALTER TABLE mh.us_futures_products ADD COLUMN details JSON')
            con.execute("INSERT INTO mh.us_futures_products VALUES ('X','UNSPECIFIED',?)",
                        ['{"_provider_coverage":{"venue_scope":"unknown"},"_definition_variants":[{"type":"single"},{"type":"combo"}]}'])
            row = inventory(con, TODAY)[0]
        self.assertEqual(row['listing_scope'], 'unknown')
        self.assertEqual(row['definition_types'], 'combo,single')
        self.assertEqual(row['optionability'], 'optionability_unknown')

    def test_optional_tables_detect_attached_database_as_well_as_schema(self):
        with connection() as con:
            self.assertTrue(table_exists(con, 'mh.iv_history'))
            self.assertFalse(table_exists(con, 'mh.missing'))
            con.execute("ATTACH ':memory:' AS other")
            con.execute('CREATE TABLE other.present(x INT)')
            self.assertTrue(table_exists(con, 'other.present'))
