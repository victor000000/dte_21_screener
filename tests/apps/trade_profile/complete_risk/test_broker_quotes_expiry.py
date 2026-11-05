"""Both legs of a calendar must reach the risk loop under their own keys."""
import datetime as dt
import unittest
from unittest.mock import patch

from apps.trade_profile.complete_risk.broker_quotes import get_real_option_quotes
from datasources import tws


class TestQuoteExpiry(unittest.TestCase):
    def test_same_strike_in_different_months_has_two_risk_quotes(self):
        nov, dec = dt.date(2026, 11, 20), dt.date(2026, 12, 18)
        positions = [("XYZ", 100., "P", "a", "IBKR", -1, 10., 2., 100., e)
                     for e in (nov, dec)]
        quotes = {("XYZ", nov, 100., "P"): {"mid": 2.},
                  ("XYZ", dec, 100., "P"): {"mid": 8.}}
        with patch.object(tws, "option_marks", return_value=quotes):
            got = get_real_option_quotes(None, positions)
        self.assertEqual(got["XYZ_100.0_P_2026-11-20"]["mark"], 2.)
        self.assertEqual(got["XYZ_100.0_P_2026-12-18"]["mark"], 8.)
