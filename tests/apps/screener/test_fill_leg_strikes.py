"""Import never requires live credentials or makes acquisition requests."""
import importlib
import unittest
from unittest.mock import patch
from apps.screener import fill_leg_strikes as m

class ImportSafety(unittest.TestCase):
    def test_no_credentials_or_network_on_import(self):
        with patch('pathlib.Path.read_text',side_effect=AssertionError('credential read')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            importlib.reload(m)
    def test_missing_credentials_fail_before_network(self):
        with patch('pathlib.Path.read_text',side_effect=FileNotFoundError('no credentials')), \
             patch('urllib.request.urlopen') as request:
            with self.assertRaises(FileNotFoundError):
                m.get('https://example.invalid')
            request.assert_not_called()
