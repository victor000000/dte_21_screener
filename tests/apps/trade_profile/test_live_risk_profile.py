from types import SimpleNamespace
import unittest
from unittest.mock import patch
from apps.trade_profile import live_risk_profile as m

class RefreshOrdering(unittest.TestCase):
    def test_failed_book_build_never_renders_report(self):
        with patch.object(m.subprocess,'run',side_effect=[SimpleNamespace(returncode=0),
                                                        SimpleNamespace(returncode=2)]) as run:
            with self.assertRaises(SystemExit) as error:
                m.main()
        self.assertEqual(error.exception.code,1)
        self.assertEqual(run.call_count,2)
        self.assertIn('fetch_extended_hours_prices.py',' '.join(run.call_args_list[0].args[0]))
        self.assertIn('build_positions.py',' '.join(run.call_args_list[1].args[0]))
