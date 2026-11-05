"""Range-IVR and liquidity gates have different meanings for stocks and futures."""
import datetime as dt
import unittest
from apps.screener.us_screen_rules import assess
from tests.compute.test_iv_rank import rows


class TestRules(unittest.TestCase):
    def test_strict_fifty_excludes_equal_rank_but_inclusive_threshold_keeps_it(self):
        # Use exactly representable endpoints for an exact boundary check.
        ivs = rows([0.125] * 58 + [0.375, 0.25])
        strict = assess(self.item, ivs, self.metrics, self.day, 50, strict_ivr=True)
        inclusive = assess(self.item, ivs, self.metrics, self.day, 50)
        self.assertEqual(strict['ivr'], 50)
        self.assertIn('LOW_IVR', strict['status'])
        self.assertFalse(strict['high_ivr'])
        self.assertEqual(inclusive['status'], 'MATCH')

    def test_roundoff_at_fifty_does_not_become_a_strict_match(self):
        ivs = rows([0.1] * 58 + [0.3, 0.2])
        result = assess(self.item, ivs, self.metrics, self.day, 50, strict_ivr=True)
        self.assertAlmostEqual(result['ivr'], 50)
        self.assertFalse(result['high_ivr'])
        self.assertIn('LOW_IVR', result['status'])
        above = assess(self.item, rows([.125] * 58 + [.375, .2500001]),
                       self.metrics, self.day, 50, strict_ivr=True)
        self.assertTrue(above['high_ivr'])

    def setUp(self):
        self.iv = rows([0.1] * 59 + [0.2])
        self.day = self.iv[-1][1]
        self.item = dict(instrument='TLT', asset_class='equity_or_fund',
                         optionability='unexpired_contract_observed')
        self.metrics = dict(avg_price=80, avg_volume=10e6, liquidity_sessions=20,
                            price_asof=self.day, capitalization=20e9)

    def test_bond_fund_meets_equity_fund_rules(self):
        self.assertEqual(assess(self.item, self.iv, self.metrics, self.day)['status'], 'MATCH')

    def test_futures_never_fail_equity_price_capitalization_or_share_threshold(self):
        future = dict(self.item, instrument='FUT:ZN:CBOT', asset_class='future')
        metrics = dict(avg_price=1, avg_volume=10, liquidity_sessions=20)
        result = assess(future, self.iv, metrics, self.day)
        self.assertEqual(result['status'], 'LIQUIDITY_RULE_UNCONFIGURED')
        self.assertTrue(result['high_ivr'])

    def test_stale_iv_unknown_optionability_and_missing_data_do_not_pass(self):
        stale = assess(self.item, self.iv, self.metrics, self.day + dt.timedelta(days=1))
        self.assertIn('STALE_IV', stale['status'])
        unknown = assess(dict(self.item, optionability='optionability_unknown'), self.iv, self.metrics, self.day)
        self.assertIn('OPTIONABILITY_UNVERIFIED', unknown['status'])
        self.assertIn('UNRANKABLE', assess(self.item, [], self.metrics, self.day)['status'])

    def test_high_percentile_does_not_pass_low_range_rank(self):
        result = assess(self.item, rows([0.1] * 58 + [1.1, 0.2]), self.metrics, self.day)
        self.assertAlmostEqual(result['ivr'], 10)
        self.assertGreater(result['ivp'], 98)
        self.assertIn('LOW_IVR', result['status'])

    def test_unknown_cap_is_pending_not_confirmed(self):
        result = assess(self.item, self.iv, dict(self.metrics, capitalization=None), self.day)
        self.assertIn('MISSING_CAPITALIZATION', result['status'])
