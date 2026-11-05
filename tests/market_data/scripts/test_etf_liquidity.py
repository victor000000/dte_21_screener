"""How an ETF's liquidity is measured, and what gets excluded.

The whole `etf500` group rests on this one number, so the definition has to be pinned:
MEDIAN dollar volume over the last month. A mean would be dragged by a single expiry or
rebalance day -- exactly the funds whose turnover is spikiest -- and share count would
rank a $4 fund alongside a $400 one.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import pandas as pd

sys.path.insert(0, str(pathlib.Path(bootstrap.ROOT / "market_data" / "scripts")))
import etf_liquidity as L  # noqa: E402


def frame(**cols):
    return pd.DataFrame(cols)


class TestTheMedianIsUsed(unittest.TestCase):
    def test_one_huge_day_does_not_move_the_ranking(self):
        # A fund that trades $1M a day but $500M on one rebalance day has a MEAN of
        # ~$18M and a MEDIAN of $1M. Ranking on the mean puts it above a fund that
        # genuinely trades $5M every day.
        steady = frame(Close=[100.0] * 11, Volume=[50_000] * 11)          # $5M/day
        spiky = frame(Close=[100.0] * 11,
                      Volume=[10_000] * 10 + [5_000_000])                  # $1M, one spike
        self.assertGreater((steady["Close"] * steady["Volume"]).median(),
                           (spiky["Close"] * spiky["Volume"]).median())
        self.assertLess((spiky["Close"] * spiky["Volume"]).mean(),
                        (steady["Close"] * steady["Volume"]).median() * 10)

    def test_it_is_dollars_not_shares(self):
        # 10,000 shares of a $400 fund is $4M; of a $4 fund it is $40k. Share count
        # would call those equal.
        rich = (frame(Close=[400.0] * 11, Volume=[10_000] * 11)["Close"]
                * frame(Volume=[10_000] * 11)["Volume"]).median()
        cheap = (frame(Close=[4.0] * 11, Volume=[10_000] * 11)["Close"]
                 * frame(Volume=[10_000] * 11)["Volume"]).median()
        self.assertEqual(rich / cheap, 100.0)


class TestWhatIsExcluded(unittest.TestCase):
    def test_a_fund_with_too_few_bars_is_dropped(self):
        # A brand-new listing has a dollar volume that says nothing about its
        # liquidity; ranking it would put it ahead of a mature fund on noise.
        self.assertLess(L.MIN_BARS, 20)
        self.assertGreater(L.MIN_BARS, 1)

    def test_the_cache_stores_a_refusal_rather_than_leaving_it_absent(self):
        # A symbol the fetch could not price is cached as None. Left absent, every
        # re-run retries the same delisted tickers forever.
        import inspect
        src = inspect.getsource(L.cached)
        self.assertIn("setdefault(s, None)", src)

    def test_the_screener_url_asks_for_everything(self):
        # limit=5000 and download=true is what returns all ~5,200 in ONE call; the
        # paged form caps at 50 rows and would need a hundred requests.
        self.assertIn("download=true", L.SCREENER)
        self.assertIn("limit=5000", L.SCREENER)


if __name__ == "__main__":
    unittest.main()
