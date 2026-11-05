import unittest
from unittest.mock import patch, Mock
from datetime import date
from apps.trade_profile.cvar_inputs import read_inputs

class CVaRInputTests(unittest.TestCase):
    @patch('apps.trade_profile.cvar_inputs.current',return_value=None)
    def test_missing_release_fails_without_acquisition(self,_):
        with self.assertRaises(ValueError):read_inputs(['SPY'],date(2026,11,5))

    @patch('apps.trade_profile.cvar_inputs.configured_connection')
    @patch('apps.trade_profile.cvar_inputs.current')
    def test_duplicate_dates_rejected_and_connection_closed(self,current,connection):
        current.return_value=Mock(id='immutable-test-release')
        c=connection.return_value
        c.execute.return_value.fetchall.return_value=[(date(2026,11,4),100,100)]*2
        with self.assertRaises(ValueError):read_inputs(['SPY'],date(2026,11,5))
        c.close.assert_called_once()
