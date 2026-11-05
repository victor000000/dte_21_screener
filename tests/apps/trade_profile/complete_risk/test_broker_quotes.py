"""Tests for get_real_option_quotes — the TWS leg quotes."""
import inspect
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk.broker_quotes import get_real_option_quotes


class TestContract(unittest.TestCase):
    def test_takes_a_connection_and_positions(self):
        params = list(inspect.signature(get_real_option_quotes).parameters)
        self.assertEqual(params[:2], ["con", "positions"])

    def test_it_does_not_import_a_broker_session_at_module_level(self):
        # The function opens its own TWS connection inside the call. A module-level
        # connect would make importing this package need a running gateway -- and
        # the gate imports every module on a box that has none.
        import apps.trade_profile.complete_risk.broker_quotes as m
        self.assertFalse(getattr(m, "ib", None), "a session is bound at module scope")

    def test_an_empty_book_returns_empty_without_connecting(self):
        # Nothing to ask about means no connection attempt, which is what keeps
        # this safe to call when the gateway is down.
        self.assertEqual(get_real_option_quotes(None, []), {})


if __name__ == "__main__":
    unittest.main()
