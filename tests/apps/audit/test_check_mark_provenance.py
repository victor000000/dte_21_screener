"""The report's claim about its own prices -- the cases where it must FAIL.

This check guards prose, which makes it easy to write one that only LOOKS like it
gates: a substring test for "live" passes on "every option mark is live, honestly".
The cases here separate an exact comparison from a keyword search; each was run
against the real report and seen to fail before the comparator was tightened.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.audit import check_mark_provenance as cmp_check
from apps.trade_profile import mark_provenance


def book(sources, sec_type="OPT"):
    """A book shaped like load_book's rows. Only indices 2 and 21 are read."""
    return [(None, "U", sec_type, None, None, None, None, None, None, None, None, None,
             None, None, None, None, None, None, None, None, None, src)
            for src in sources]


def report(clause):
    return (f"# Combined risk profile\n\n**Book as of 2026-10-06 13:51 UTC — greeks at "
            f"the current spot, {clause}.** Computed from the `positions` table.")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, group, check, ok, detail, warn=False):
        self.calls.append((group, check, ok, detail))

    @property
    def ok(self):
        return self.calls[-1][2] if self.calls else None


def run(clause, sources):
    rec = Recorder()
    cmp_check.check(report(clause), book(sources), rec, mark_provenance)
    return rec


class TestItFailsOnWrongSentences(unittest.TestCase):
    def test_the_old_hardcoded_sentence_fails_against_a_live_book(self):
        # THE regression: 'model prices (not live option quotes)' against 16 legs
        # priced off the broker's live two-sided book.
        rec = run("model prices (not live option quotes)", ["broker_book"] * 16)
        self.assertFalse(rec.ok)
        self.assertEqual(rec.calls[-1][0], "REPORT")

    def test_a_keyword_true_but_wrong_sentence_fails(self):
        # Any check looking for "live" passes this. It is still not what the
        # generator says, so it is not what the report should be allowed to say.
        rec = run("every option mark is live, honestly", ["broker_book"] * 16)
        self.assertFalse(rec.ok)

    def test_over_claiming_a_count_fails(self):
        rec = run("9 of 16 option marks are live two-sided quotes, the rest are not",
                  ["broker_book"] * 16)
        self.assertFalse(rec.ok)

    def test_calling_a_model_book_live_fails(self):
        rec = run("every option mark is a two-sided quote", ["model"] * 4)
        self.assertFalse(rec.ok)
