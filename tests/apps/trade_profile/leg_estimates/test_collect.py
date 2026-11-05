"""Tests for collect() — one dict per leg.

Tier 2 for the parts that need a book; the shape assertions are tier 1.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

import duckdb

# The FUNCTION, not the submodule: the package __init__ re-exports it under the
# same name, so `from ... import collect` resolves to the function.
from apps.trade_profile.leg_estimates.collect import collect

DB = bootstrap.DATA_ROOT / "trades.duckdb"

REQUIRED_KEYS = {"account", "broker", "underlying", "expiry", "sec_type", "qty",
                 "entry", "mark", "mark_model", "rt_spot", "pnl_mark", "target_50",
                 "strike", "call_put", "theta", "vega", "leg", "iv", "est", "pnl_est",
                 "delta"}


@unittest.skipUnless(DB.exists(), "trades.duckdb not present")
class TestCollect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(DB), read_only=True)
        cls.rows = collect(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_returns_rows(self):
        self.assertTrue(self.rows)

    def test_every_row_carries_the_full_key_set(self):
        # The renderers index these by name; a missing key is a KeyError deep in
        # report generation rather than a clear failure here.
        for r in self.rows:
            missing = REQUIRED_KEYS - set(r)
            self.assertFalse(missing, f"{r.get('underlying')}: missing {missing}")

    def test_delta_is_the_gap_between_the_two_percentages(self):
        for r in self.rows:
            self.assertAlmostEqual(r["delta"], r["pnl_est"] - r["pnl_mark"], places=6)

    def test_sorted_broker_first(self):
        # An order goes to one broker and a margin call is one broker's problem,
        # so the table is read in broker blocks.
        brokers = [r["broker"] for r in self.rows]
        self.assertEqual(brokers, sorted(brokers))

    def test_the_estimate_round_trips_to_the_model_price(self):
        # est must equal mark_model: the IV is solved from the MODEL price at the live spot
        # and re-priced there. The 2026-10-06 bug was this failing -- EWZ's 43 call came back
        # 77.4% IV against a model price of 2.47, the IV having been solved from a STALE
        # price against a LIVE spot. `mark` is the last price given; that gap is the point.
        opts = [r for r in self.rows if r["sec_type"] != "STOCK" and r["mark_model"]]
        self.assertTrue(opts)
        for r in opts:
            if r["est"] is None:
                continue
            self.assertAlmostEqual(r["est"], r["mark_model"], places=3,
                                   msg=f"{r['underlying']} {r['leg']}")

    def test_mark_is_the_observation_and_not_the_model(self):
        # The regression: collect() read positions.mark, which build_positions writes as a
        # price at TODAY'S live spot -- so every delta was 0.0pp and the narrative section
        # about the two disagreeing could never fire (six CRWD legs sat 7.5pp apart on
        # 2026-10-07). Asserted against the COLUMN, not "the two differ": a live-quoted book
        # has them equal legitimately, and a test written that way would pass on the bug.
        obs = {(u, k, c): mo for u, k, c, mo in self.con.execute(
            "SELECT underlying, strike, call_put, mark_obs FROM positions").fetchall()}
        checked = 0
        for r in self.rows:
            key = (r["underlying"], r["strike"], r["call_put"])
            if obs.get(key) is None:
                continue
            self.assertAlmostEqual(r["mark"], obs[key], places=6,
                                   msg=f"{r['underlying']} {r['leg']} is not the observed price")
            checked += 1
        self.assertTrue(checked, "no leg had an observation to check against")

    def test_account_filter_narrows_the_book(self):
        acct = self.rows[0]["account"]
        subset = collect(self.con, account=acct)
        self.assertTrue(subset)
        self.assertEqual({r["account"] for r in subset}, {acct})
        self.assertLessEqual(len(subset), len(self.rows))


if __name__ == "__main__":
    unittest.main()
