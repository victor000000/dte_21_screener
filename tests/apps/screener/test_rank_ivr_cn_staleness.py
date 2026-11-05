"""test_rank_ivr_cn_staleness.py — the sentence above the table that explains the gap.

Split from test_rank_ivr_cn.py, which sits at the repo's 100-line cap.

Three states must not share a sentence: an exchange that was closed, a session that has not
opened yet, and a download that stopped. The version this replaced said "China's Golden Week
(Oct 1-8, 2026)" on ANY gap of two days or more -- wrong dates, and it explained away a dead
downloader as a holiday. The version after it counted today's session from local midnight, so
it cried "download gap" every morning before the market opened.
"""
import datetime as dt
import pathlib
import sys
import unittest
import unittest.mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from apps.screener import rank_ivr_cn as entry  # noqa: E402

DAY = dt.date(2026, 9, 30)
CAL = [dt.date(2026, 9, 30), dt.date(2026, 10, 8), dt.date(2026, 10, 9)]


class TestStaleness(unittest.TestCase):
    def _note(self, now_utc):
        with unittest.mock.patch("apps.screener.cn_iv.calendar.cn_calendar",
                                 return_value=CAL), \
             unittest.mock.patch.object(entry.clock, "now", return_value=now_utc):
            return entry.staleness(DAY)

    def test_a_holiday_is_not_reported_as_a_gap_in_our_data(self):
        # Golden Week 2026: data through Sep 30, no session until Oct 8, nothing missed between.
        note = self._note(dt.datetime(2026, 10, 7, 4, 0))            # 12:00 CN, market shut
        self.assertIn("No CN session is missing", note)
        self.assertIn("2026-10-08", note)

    def test_todays_session_before_it_opens_is_not_a_gap(self):
        # 00:41 UTC = 08:41 CN on the morning the exchanges REOPEN. Today is a session, it has
        # not opened, and it is not ours to have fetched yet.
        self.assertIn("No CN session is missing", self._note(dt.datetime(2026, 10, 8, 0, 41)))

    def test_a_session_that_closed_unstored_is_named_as_a_download_gap(self):
        self.assertIn("NOT stored", self._note(dt.datetime(2026, 10, 20, 3, 0)))

    def test_no_calendar_no_claim(self):
        # Offline, the note says nothing rather than guessing -- the whole point of the rewrite.
        with unittest.mock.patch("apps.screener.cn_iv.calendar.cn_calendar",
                                 side_effect=RuntimeError("offline")):
            self.assertIsNone(entry.staleness(DAY))


if __name__ == "__main__":
    unittest.main()
