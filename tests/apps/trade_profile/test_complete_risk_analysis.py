"""Tests for complete_risk_analysis.py — the entry point, mid-split.

This file is being split into apps/trade_profile/complete_risk/. What is left
here is the module itself plus four functions the splitter cannot move because
they need DECOMPOSING: calculate_risk_profile (265 lines), main (353),
fetch_massive_eod (96) and save_risk_snapshot (87).

So these tests pin the contract that must survive the rest of the split: the
script path, its --help guard, and the fact that the pieces it kept still reach
the pieces that moved.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

from apps.trade_profile import complete_risk_analysis as CRA

ROOT = bootstrap.ROOT


class TestEntryPointContract(unittest.TestCase):
    def test_it_exposes_main(self):
        # `make risk` runs this file by path, so main must stay importable and
        # stay the thing the __main__ guard calls.
        self.assertTrue(callable(CRA.main))

    def test_the_helpguard_description_is_the_first_string_literal(self):
        # helpguard reads the summary from the SOURCE (not __doc__), and --help
        # exits before any connection. If the description literal is dislodged by
        # the split, --help silently degrades to "(no module summary)".
        from shared.helpguard import module_summary
        summary = module_summary(ROOT / "apps/trade_profile/complete_risk_analysis.py")
        self.assertIsNotNone(summary, "the module summary is gone -- --help would degrade")
        self.assertIn("complete_risk_analysis", " ".join(summary))

    def test_the_helpguard_call_precedes_any_database_connection(self):
        import inspect
        src = inspect.getsource(CRA)
        self.assertLess(src.index("handle_help"), src.index("db.connect"))

    def test_it_is_still_a_script_not_a_package(self):
        # The split is incremental: this path is the entry point until the last
        # pass, and a shim replaces it only then.
        self.assertTrue((ROOT / "apps/trade_profile/complete_risk_analysis.py").is_file())


class TestTheMoveIsWired(unittest.TestCase):
    def test_the_symbols_it_kept_can_still_reach_the_ones_that_moved(self):
        # The moved functions are imported at the BOTTOM of this file (the splitter
        # inserts them after the kept definitions). That works because Python
        # resolves a global at CALL time, not at def time -- which is fine, and is
        # exactly the property worth pinning: a future reorder that put the
        # imports above a use would be harmless, but a use at module scope would
        # not be.
        for name in ("is_market_hours", "fetch_extended_hours_prices",
                     "get_latest_price", "canonical_snapshot_spots",
                     "fetch_theta_eod", "get_real_option_quotes"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(CRA, name),
                                f"{name} is not reachable from the source module")

    def test_the_disputed_flag_is_the_shared_singleton(self):
        # _DISPUTED_REPORTED is once-per-PROCESS: main() calls the profile twice
        # and relies on the flag persisting. The split moved it to a module; this
        # asserts the source imported THAT object and did not get a copy.
        from apps.trade_profile.complete_risk import _state
        self.assertIs(CRA._DISPUTED_REPORTED, _state._DISPUTED_REPORTED)


if __name__ == "__main__":
    unittest.main()
