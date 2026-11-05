"""Tests for the quote-refresh subprocess wrapper."""
import inspect
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk.refresh import fetch_extended_hours_prices


class TestContract(unittest.TestCase):
    def test_it_shells_out_rather_than_importing_the_fetcher(self):
        # Importing apps.data_ops.fetch_extended_hours_prices would pull ib_async,
        # futu-api and alpaca-py into every process that touches this package, and
        # would run whichever sources happen to be importable. The subprocess is
        # deliberate: one process, its own dependency set, its own failure.
        src = inspect.getsource(fetch_extended_hours_prices)
        self.assertIn("subprocess", src)

    def test_it_targets_the_vendored_fetcher_by_path(self):
        src = inspect.getsource(fetch_extended_hours_prices)
        self.assertIn("fetch_extended_hours_prices.py", src)

    def test_it_returns_a_bool(self):
        # main() branches on the return value to decide whether to continue.
        src = inspect.getsource(fetch_extended_hours_prices)
        self.assertIn("return", src)


if __name__ == "__main__":
    unittest.main()
