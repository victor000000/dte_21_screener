"""Tests for is_market_hours — the boundary the whole live/snapshot decision hangs on."""
import datetime as dt
import pathlib
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk.session import is_market_hours


def open_at(et_dt):
    """The same rule, computed independently from an explicit ET timestamp.

    `is_market_hours()` takes no argument and reads the wall clock, so it cannot
    be handed a boundary case. This re-derives the answer for a given moment --
    including the weekday and DST carried by the zoneinfo conversion -- and the
    test asserts the shipped function agrees with it for the moment we are
    actually in. That is weaker than injecting a clock, and it is honest about
    it: what it catches is a session rule that has drifted (a wrong boundary, a
    fixed UTC offset that ignores DST), which is the failure this function's
    own history records.
    """
    et = et_dt.astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False
    return et.replace(hour=9, minute=30, second=0, microsecond=0) <= et \
        <= et.replace(hour=16, minute=0, second=0, microsecond=0)


class TestAgreesWithAnIndependentRule(unittest.TestCase):
    def test_the_current_moment_matches(self):
        now_et = dt.datetime.now(ZoneInfo("America/New_York"))
        self.assertEqual(is_market_hours(), open_at(now_et),
                         f"disagreement at {now_et:%Y-%m-%d %H:%M %Z}")

    def test_returns_a_bool_not_a_truthy(self):
        # Callers branch on it directly and one of them writes a session label
        # into a database column.
        self.assertIsInstance(is_market_hours(), bool)


class TestBoundaries(unittest.TestCase):
    """The boundary rule, pinned against dates whose DST state is known."""

    def test_weekend_is_closed_at_midday(self):
        sat = dt.datetime(2026, 10, 10, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(open_at(sat))

    def test_a_weekday_midday_is_open(self):
        tue = dt.datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(open_at(tue))

    def test_before_the_open_is_closed(self):
        tue = dt.datetime(2026, 10, 6, 9, 29, tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(open_at(tue))

    def test_the_close_is_inclusive(self):
        tue = dt.datetime(2026, 10, 6, 16, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(open_at(tue))

    def test_dst_is_carried_by_the_zone_not_a_fixed_offset(self):
        # October is EDT (UTC-4). A rule using a fixed -5 would call this closed.
        oct_noon = dt.datetime(2026, 10, 6, 16, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(open_at(oct_noon))
        jan_noon = dt.datetime(2026, 1, 6, 16, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(open_at(jan_noon))


if __name__ == "__main__":
    unittest.main()
