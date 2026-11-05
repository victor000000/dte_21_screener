"""The provenance sentence that used to be a hardcoded lie.

The regression this covers is not a crash. `risk_profile` printed "model prices
(not live option quotes)" for as long as every mark was a chain snapshot, and kept
printing it after 2026-10-06 put the US legs on the broker's live book. The report
contradicted itself -- `P&L %` equal to `Est. P&L %` on every row is the signature
of a mark observed at the current spot -- and the wrong half was the sentence.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.trade_profile import mark_provenance as mp


class TestTheSentenceSaysWhichItIs(unittest.TestCase):
    def test_an_all_broker_book_is_called_live(self):
        s = mp.sentence(["broker_book"] * 16)
        self.assertIn("every option mark is a two-sided quote", s)
        self.assertNotIn("model", s)

    def test_an_all_chain_book_is_also_live(self):
        # A two-sided chain quote is an observation too. The distinction the header
        # draws is observation-vs-model, not broker-vs-not.
        self.assertIn("two-sided", mp.sentence(["chain_book"] * 3))

    def test_an_all_model_book_claims_no_quote(self):
        # The intent is "no mark here is a quote", not the absence of a substring -- the
        # all-model sentence contains the words "a two-sided quote" while denying it.
        s = mp.sentence(["model"] * 4)
        self.assertTrue(s.startswith("no option mark"), s)
        self.assertIn("model", s)

    def test_a_mixed_book_gives_the_count_not_a_verdict(self):
        # THE case that must not round. Nine live of ten is neither "live quotes"
        # nor "models", and picking either is how the header came to be wrong.
        s = mp.sentence(["broker_book"] * 9 + ["model"])
        self.assertIn("9 of 10", s)
        self.assertIn("the rest are not", s)

    def test_a_snapshot_is_not_live(self):
        # A chain_snapshots row is a real observation at a spot that is NOT current,
        # which is the whole reason spot_source exists. It must not read as live.
        self.assertTrue(mp.sentence(["snapshot"]).startswith("no option mark"))

    def test_an_empty_book_does_not_claim_anything(self):
        self.assertIn("no option marks", mp.sentence([]))

    def test_an_unknown_source_is_not_assumed_live(self):
        # A NULL mark_source (a row written before the column existed) must fail
        # closed: unknown provenance is not evidence of a live quote.
        self.assertTrue(mp.sentence([None]).startswith("no option mark"))


class TestTheBreakdown(unittest.TestCase):
    def test_it_labels_every_source_it_knows(self):
        for src in mp.LIVE + ("model", "snapshot", "fill", "cn_snapshot"):
            self.assertIn(src, mp._LABEL, f"{src} has no human label")

    def test_it_counts_rather_than_lists(self):
        # No trailing period: risk_profile wraps this in its own *...* italics and
        # supplies the stop. Asserted here so the two do not both add one.
        self.assertEqual(mp.detail(["broker_book"] * 11),
                         "Option marks: 11× two-sided broker quote")

    def test_counts_groups_by_source(self):
        self.assertEqual(mp.counts(["model", None, None]),
                         {"model": 1, "unknown": 2})

    def test_detail_is_none_for_an_empty_book(self):
        # The caller does `if detail:` -- None and "" both skip, but None is the
        # contract, and a book with no options should not print an empty bullet.
        self.assertIsNone(mp.detail([]))

    def test_n_live_counts_only_the_live_sources(self):
        self.assertEqual(mp.n_live(["broker_book", "chain_book", "model", "fill"]), 2)


if __name__ == "__main__":
    unittest.main()
