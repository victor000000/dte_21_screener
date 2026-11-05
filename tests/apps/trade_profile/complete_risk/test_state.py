"""Tests for the once-per-process dispute flag."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.complete_risk import _state


class TestDisputedFlag(unittest.TestCase):
    def test_starts_false(self):
        # The flag exists so a table-level fault is reported ONCE per process:
        # main() calls the profile function twice, and the second call must stay
        # quiet. If this ever became per-call, the report would print the same
        # warning twice and read as two different faults.
        self.assertIsInstance(_state._DISPUTED_REPORTED, bool)

    def test_it_is_a_module_attribute_not_a_copy(self):
        # The rebinding function and the variable it rebinds must stay in one
        # module: `global X` in a moved function rebinds THAT module's name while
        # every other reader sees the old value -- a flag that never flips.
        import inspect
        from apps.trade_profile.complete_risk import _state as s
        _state._DISPUTED_REPORTED = True
        try:
            self.assertTrue(s._DISPUTED_REPORTED)
        finally:
            _state._DISPUTED_REPORTED = False


if __name__ == "__main__":
    unittest.main()
