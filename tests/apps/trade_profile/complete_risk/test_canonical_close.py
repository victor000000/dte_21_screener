"""Today's daily close becomes usable after the vendor's actual session end."""
import datetime as dt
import unittest
from unittest.mock import patch
import pandas as pd
from zoneinfo import ZoneInfo
from apps.trade_profile.complete_risk import canonical as app


class CompletedCloseTests(unittest.TestCase):
    def value(self, hour, minute, close_hour=16):
        now = dt.datetime(2026,10,16,hour,minute,tzinfo=ZoneInfo('America/New_York'))
        end = dt.datetime(2026,10,16,close_hour,tzinfo=ZoneInfo('America/New_York')).timestamp()
        frame = pd.DataFrame({'Close':[100.,110.]},index=pd.to_datetime(['2026-10-15','2026-10-16']))
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        with patch.object(app.dt,'datetime',Clock), patch('yfinance.Ticker') as ticker:
            ticker.return_value.history.return_value=frame
            ticker.return_value.history_metadata={'currentTradingPeriod':{'regular':{'end':end}}}
            result=app.canonical_snapshot_spots(['XYZ','XYZ'])
            self.assertEqual(ticker.call_count,1)
            return result['XYZ']

    def test_intraday_excludes_the_incomplete_bar(self):
        self.assertEqual(self.value(15,59),100.)

    def test_after_close_includes_today(self):
        self.assertEqual(self.value(16,1),110.)

    def test_early_close_uses_the_vendor_time(self):
        self.assertEqual(self.value(13,1,13),110.)
