import unittest
from apps.trading_web.quote_readiness import summarize


class ReadinessTests(unittest.TestCase):
    def test_transport_and_frozen_never_count_as_fresh(self):
        rows=[{'quote':dict(midpoint=1,feed=f,quote_time=None,executable_reference=False)} for f in ['live','frozen','indicative']]
        r=summarize(rows)
        self.assertEqual(r['fresh_verified'],0)
        self.assertEqual(r['live_clock_unknown'],1)
        self.assertEqual(r['frozen'],1)
        self.assertTrue(r['label'].startswith('No timestamp'))

    def test_disagreement_not_classified_as_live(self):
        r=summarize([dict(disputed=True,quote=dict(midpoint=1,feed='live',executable_reference=True))])
        self.assertEqual(r['fresh_verified'],0)
        self.assertEqual(r['disputed'],1)

    def test_verified_reference_is_counted_separately_from_other_books(self):
        r=summarize([dict(quote=dict(midpoint=1,feed='opra',executable_reference=True,quote_time='2026-10-26T14:00:00Z'))])
        self.assertEqual(r['fresh_verified'],1)
        self.assertTrue(r['label'].startswith('Timestamp-verified'))
