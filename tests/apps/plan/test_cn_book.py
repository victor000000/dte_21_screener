"""test_cn_book.py — the China legs are repriced at a LIVE underlying, not a frozen literal.
On 2026-10-08 MA701 sat at 2936 while MA2701 traded 3268, so a short 3350C read 0.26 delta and
14% out of the money when it was at the money, down ~-$5,200."""
import datetime as dt
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import duckdb

from apps.plan import cn_book
from compute.bs import bs_greeks, implied_vol, T_years
from shared.rates import R_CN

# field order and the four greek columns' scales: apps/plan/cn_legs.py, which documents and
# tests them. These two are tracker-shaped (glot carries spot, theta is per trading day).
CALL = ("CN_ACCOUNT", "浙商期货", "MA701", "FUT_OPT", "2026-12-11", 3350.0, "C", -31, 70.31,
        2936.0, 70.0, 10, -7.8379, -578.99, 563.09, -1189.45)
PUT = ("CN_ACCOUNT", "浙商期货", "MA701", "FUT_OPT", "2026-12-11", 2650.0, "P", -31, 81.98,
       2936.0, 83.0, 10, 7.6256, -552.59, 539.06, -1172.22)
SCHEMA = """CREATE TABLE positions (account TEXT, broker TEXT, underlying TEXT, sec_type TEXT, expiry DATE, strike DOUBLE, call_put TEXT, qty DOUBLE, avg_price DOUBLE, spot DOUBLE, multiplier DOUBLE, mark DOUBLE, delta_units DOUBLE, gamma_units DOUBLE, theta_day DOUBLE, vega_pt DOUBLE, delta_notional_usd DOUBLE, asset_class TEXT, sector TEXT, industry TEXT, subindustry TEXT, spot_source TEXT, spot_class TEXT, spot_is_realtime BOOLEAN, mark_obs DOUBLE, mark_source TEXT, bid DOUBLE, ask DOUBLE)"""


def live(spot, session=True):
    """One leg repriced as if Sina had answered `spot`. session_open is mocked because it
    reads the CLOCK: left real, these assertions pass in session and fail out of hours."""
    with mock.patch.object(cn_book.cn_ticks, "fetch", return_value={"nf_MA2701": spot}), \
         mock.patch.object(cn_book, "session_open", return_value=session):
        return cn_book.reprice(CALL, cn_book.live_spot("MA701", 2936.0))


class TestReprice(unittest.TestCase):
    def test_mark_moves_from_the_observation_to_the_live_spot(self):
        spot, src, cls, rt, mark, du, gu, th, v = live(3268.0)
        self.assertEqual((spot, src, rt), (3268.0, "Sina", True))
        self.assertTrue(150 < mark < 230)     # 70.0 at 2936 reprices to ~191 at 3268
        self.assertLess(du, -140)             # delta moved from the literal's -79.45

    def test_outside_a_session_the_spot_says_last_only(self):
        """Out of hours the quote is the last close, and must not pass as real-time."""
        spot, src, cls, rt, *_ = live(3268.0, session=False)
        self.assertEqual((src, cls, rt), ("Sina", "last_only", False))

    def test_observation_spot_is_kept_when_sina_is_down(self):
        with mock.patch.object(cn_book.cn_ticks, "fetch", side_effect=TimeoutError):
            out = cn_book.reprice(CALL, cn_book.live_spot("MA701", 2936.0))
        self.assertEqual(out[:4], (2936.0, "快期", "broker_snapshot", False))
        self.assertEqual(out[4], 70.0)               # the mark, unrepriceable, left alone
        # all four, each converted from its own scale: `x mult` alone was 10x low on theta and
        # vega and 2936x high on gamma, and only delta was ever asserted
        self.assertEqual([round(x, 4) for x in out[5:9]], [-78.379, -0.1972, 419.6178, -1189.45])

    def test_the_snapshot_lands_on_black_scholes_at_the_same_spot(self):
        """The conversion table, pinned. Each tracker column is on its own scale, so each needs
        its own factor; the evidence they are right is the six real CZCE legs, where all four
        come out within 8% of BS at our own mark."""
        # `today` is PINNED to the date the tuple's greeks were struck (2026-10-12): with the
        # wall clock driving T, theta grows ~2.5%/day and the 2% tolerance expired on
        # 2026-10-15 -- a time bomb, not a bad conversion. The factors are what is pinned
        # here, so the reference date must be too.
        T = T_years(dt.date(2026, 12, 11), today=dt.date(2026, 10, 12))
        bs = bs_greeks(2936.0, 3350.0, T, R_CN, implied_vol(70.0, 2936.0, 3350.0, T, R_CN, True), True)
        out = cn_book.reprice(CALL, (2936.0, "快期", "broker_snapshot", False))
        for got, want in zip(out[5:9], (-31 * g * 10 for g in bs[:4])):
            self.assertAlmostEqual(got, want, delta=abs(want) * 0.02)

    def test_no_iv_keeps_the_snapshot_whole(self):
        """A price and a spot that disagree cannot be half-updated."""
        bad = CALL[:9] + (1.0,) + CALL[10:]          # mark 1.0 at a 2936 observation
        with mock.patch.object(cn_book.cn_ticks, "fetch", return_value={"nf_MA2701": 3268.0}):
            out = cn_book.reprice(bad, cn_book.live_spot("MA701", 1.0))
        self.assertEqual(out[0], 1.0)                # falls back to the observation spot


class TestStore(unittest.TestCase):
    def test_both_legs_of_a_strangle_share_one_spot(self):
        """A per-leg fetch left one side live and the other on the snapshot (2026-10-08)."""
        calls = []

        def counting_fetch(codes):
            calls.append(codes)
            return {"nf_MA2701": 3268.0}

        con = duckdb.connect(":memory:")
        con.execute(SCHEMA)
        with mock.patch.object(cn_book, "CN", [CALL, PUT]), \
             mock.patch.object(cn_book, "session_open", return_value=True), \
             mock.patch.object(cn_book.cn_ticks, "fetch", side_effect=counting_fetch):
            self.assertEqual(cn_book.store(con, {}), 2)
        self.assertEqual(len(calls), 1, "one fetch per UNDERLYING, not per leg")
        got = con.execute("SELECT DISTINCT spot, spot_is_realtime FROM positions").fetchall()
        self.assertEqual(got, [(3268.0, True)])
