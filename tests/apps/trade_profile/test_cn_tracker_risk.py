import unittest
from apps.trade_profile.cn_tracker_risk import calculate


def leg(symbol, qty, delta, gamma, future='MA2701'):
    return dict(symbol=symbol, venue='CZCE', root='MA', future=future,
                qty=qty, multiplier=10, underlying_price=3200,
                position_delta_futures_equivalent=delta, position_gamma=gamma)


class TrackerRiskTest(unittest.TestCase):
    def test_ma_snapshot_netting_and_unknown_gamma(self):
        rows = [leg('MA701P2900', -31, 7.047, -.021),
                leg('MA701C3750', 35, 5.269, .017),
                leg('MA701C3350', -31, -11.741, -.028),
                leg('MA612C3400', -15, -5.225, -.017, 'MA2612')]
        out = calculate(rows, cny_per_usd=6.7, fx_as_of='2026-10-16')
        self.assertAlmostEqual(out['futures'][0]['position_delta_futures_equivalent'], .575)
        self.assertAlmostEqual(out['futures'][1]['position_delta_futures_equivalent'], -5.225)
        self.assertAlmostEqual(out['legs'][2]['dollar_delta_usd'], -11.741 * 10 * 3200 / 6.7)
        self.assertIsNone(out['ticker_ranking'][0]['gamma_pnl_1pct_usd'])

    def test_explicit_gamma_units_long_and_short_profit(self):
        short = leg('MA701C3350', -31, -11.741, -.028)
        short.update(gamma_basis='position_gamma', entry=80, option_ask=40)
        long = leg('MA701C3750', 35, 5.269, .017)
        long.update(gamma_basis='position_gamma', entry=40, option_bid=60)
        out = calculate([short, long], cny_per_usd=6.7, fx_as_of='2026-10-16')
        self.assertEqual([r['premium_profit_pct'] for r in out['legs']], [50, 50])
        self.assertAlmostEqual(out['legs'][0]['gamma_pnl_1pct_usd'], .5 * -.028 * 10 * 32**2 / 6.7)
        old_style = dict(short, position_gamma=-.028 * 10 * 3200, gamma_basis='cash_gamma_over_spot')
        other = calculate([old_style], cny_per_usd=6.7, fx_as_of='2026-10-16')
        self.assertEqual(out['legs'][0]['gamma_pnl_1pct_usd'], other['legs'][0]['gamma_pnl_1pct_usd'])

    def test_invalid_prices_and_gamma_basis_fail_closed(self):
        for change in ({'underlying_price': float('nan')}, {'gamma_basis': 'guessed'}):
            with self.assertRaises(ValueError):
                calculate([dict(leg('MA701C3350', -31, -11.741, -.028), **change)], cny_per_usd=6.7, fx_as_of='2026-10-16')
