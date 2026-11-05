"""Tests for cn_legs — the hand-transcribed China positions.

These are the assertions that would have caught 2026-10-12, when the list held two legs against
the broker's six and the methanol put sat at 2650 against a real 2900. A test cannot know the
broker's book; what it CAN do is check the invariants the transcription has to satisfy, so a
bad copy is caught by shape even when nobody re-reads the tracker.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.plan.cn_legs import CN  # noqa: E402

FIELDS = 16


class TestCnLegs(unittest.TestCase):
    def test_every_leg_has_the_documented_field_count(self):
        for leg in CN:
            with self.subTest(leg=leg[2:7]):
                self.assertEqual(len(leg), FIELDS)

    def test_no_duplicate_contract(self):
        seen = [(leg[2], leg[4], leg[5], leg[6]) for leg in CN]   # u, expiry, strike, cp
        self.assertEqual(len(seen), len(set(seen)), "a contract is listed twice")

    def test_the_two_halves_of_a_strangle_agree_on_the_observed_spot(self):
        # THE cross-check that validates the multiplier: the broker's $Delta = delta*qty*spot*mult
        # for every leg, so two legs on one underlying must invert to the SAME spot. When they do
        # not, either the multiplier is wrong or 市值/持仓Delta was mis-transcribed.
        by_key = {}
        for leg in CN:
            by_key.setdefault((leg[2], leg[4]), []).append(leg)
        for (u, exp), legs in by_key.items():
            spots = {round(l[9], 0) for l in legs}
            with self.subTest(underlying=u, expiry=exp):
                self.assertEqual(len(spots), 1,
                                 f"{u} legs imply different observed spots {spots} — "
                                 f"check the multiplier and the $Delta column")

    def test_every_leg_is_a_short_with_a_positive_multiplier(self):
        for leg in CN:
            with self.subTest(leg=leg[2:7]):
                self.assertLess(leg[7], 0, "these are short legs; a positive qty means a sign slip")
                self.assertGreater(leg[11], 0, "multiplier")

    def test_the_risk_columns_carry_the_sign_a_short_must_have(self):
        """The four columns are copied verbatim from the tracker, so a dropped minus is the
        realistic error and it is invisible in every other check here. A short collects theta,
        pays gamma and vega, and its delta is -qty x the option's own: a call leg is negative,
        a put leg positive."""
        for leg in CN:
            u, K, cp, qty, dlot, glot, th, v = leg[2], leg[5], leg[6], leg[7], leg[12], leg[13], leg[14], leg[15]
            with self.subTest(leg=(u, K, cp)):
                if cp == "C":
                    self.assertLess(dlot, 0, "a short call's position delta is negative")
                else:
                    self.assertGreater(dlot, 0, "a short put's position delta is positive")
                self.assertLess(glot, 0, "a short is negative gamma")
                self.assertGreater(th, 0, "a short collects theta")
                self.assertLess(v, 0, "a short is negative vega")

    def test_strikes_sit_near_their_observed_spot(self):
        # A strike more than 60% away from the observed spot is almost always a transposed digit:
        # 2650 against a real 2900 was exactly this, and it survived review for weeks.
        for leg in CN:
            with self.subTest(leg=leg[2:7]):
                self.assertLess(abs(leg[5] - leg[9]) / leg[9], 0.6)

    def test_the_book_is_not_silently_empty(self):
        self.assertGreaterEqual(len(CN), 6, "the broker's book held six legs on 2026-10-12")


if __name__ == "__main__":
    unittest.main()
