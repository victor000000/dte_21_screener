import datetime as dt
import duckdb
import unittest
from unittest.mock import patch

from apps.data_ops import download_minute_bars as app


class MinuteReuseTests(unittest.TestCase):
    def test_fill_session_reuses_staging_and_merged_minutes(self):
        for held_schema in ("mh", "mhro"):
            with self.subTest(held_schema=held_schema):
                con = duckdb.connect(":memory:")
                for schema in ("tr", "mh", "mhro"):
                    con.execute(f"CREATE SCHEMA {schema}")
                con.execute("CREATE TABLE tr.fills(underlying TEXT,expiry DATE,strike DOUBLE,"
                            "call_put TEXT,ts_utc TIMESTAMP,broker TEXT)")
                con.execute("INSERT INTO tr.fills VALUES "
                            "('SPY','2026-11-20',500,'P','2026-10-15 14:00:00','IBKR')")
                for schema in ("mh", "mhro"):
                    con.execute(f"CREATE TABLE {schema}.option_minutes(source TEXT,symbol TEXT,ts_utc TIMESTAMP)")
                con.execute(f"INSERT INTO {held_schema}.option_minutes VALUES "
                            "('alpaca_1min','SPY261120P00500000','2026-10-15 13:50:00')")
                try:
                    with patch.object(app, "fetch_bars", return_value=[]) as fetch:
                        app.mode_fills(con)
                        fetch.assert_not_called()
                    con.execute(f"UPDATE {held_schema}.option_minutes "
                                "SET source='ibkr_trade_window_1min'")
                    with patch.object(app, "fetch_bars", return_value=[]) as fetch, \
                            patch.object(app, "status"):
                        app.mode_fills(con)
                        fetch.assert_called_once()
                finally:
                    con.close()


class MinuteFailureTests(unittest.TestCase):
    def test_unavailable_feed_preserves_history_and_reports_failure(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE SCHEMA mhro")
        con.execute("CREATE TABLE mhro.underlying_minutes(symbol TEXT,ts_utc TIMESTAMP,source TEXT)")
        con.execute("INSERT INTO mhro.underlying_minutes VALUES ('SPY','2026-10-14 14:00:00','alpaca_1min')")
        try:
            with patch.object(app, "fetch_range", side_effect=RuntimeError("feed unavailable")), patch.object(app, "status"):
                failures = app.mode_under(con, ['SPY'], dt.date(2026,10,15), dt.date(2026,10,16))
            self.assertEqual(failures, 1)
            self.assertEqual(con.execute("SELECT count(*) FROM mhro.underlying_minutes").fetchone()[0], 1)
        finally:
            con.close()


class MinuteBoundaryTests(unittest.TestCase):
    def test_single_session_requests_the_whole_utc_day(self):
        from urllib.parse import urlparse, parse_qs
        with patch.object(app,'get',return_value={'bars':{'SPY':[]}}) as get:
            app.fetch_bars('https://data.alpaca.markets/options','SPY',dt.date(2026,10,15))
        args=parse_qs(urlparse(get.call_args.args[0]).query)
        self.assertEqual(args['start'],['2026-10-15T00:00:00Z'])
        self.assertEqual(args['end'],['2026-10-15T23:59:59Z'])

    def test_range_includes_the_final_sessions_afternoon(self):
        from urllib.parse import urlparse, parse_qs
        with patch.object(app,'get',return_value={'bars':{'SPY':[]}}) as get:
            app.fetch_range('SPY',dt.date(2026,10,8),dt.date(2026,10,16))
        args=parse_qs(urlparse(get.call_args.args[0]).query)
        self.assertEqual(args['end'],['2026-10-16T23:59:59Z'])
