"""Tests for the health report's rendering and its exit contract.

The exit status is the part that matters: `ds_health.py` is meant to GATE a run, so a required
source being down must produce exit 1. A report that printed "REQUIRED DOWN: tws" and still
exited 0 would let a pipeline start against a dead gateway — which is precisely the failure
that made a whole sweep run for 90 minutes fetching nothing.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import ds_health as DH


def rows(*specs):
    return [{"source": s, "ok": ok, "detail": d, "secs": 0.0, "required": req}
            for s, ok, d, req in specs]


class TestRender(unittest.TestCase):
    def test_ok_and_down_are_distinguishable(self):
        out = DH.render(rows(("tws", False, "refused", True),
                             ("sina", True, "HTTP 200", False)), ["tws"])
        self.assertIn("[DOWN] tws", out)
        self.assertIn("[OK  ] sina", out)

    def test_an_optional_source_failing_is_not_labelled_down(self):
        # tiingo/czce/shfe/sina are best-effort; calling them DOWN would cry wolf every run.
        out = DH.render(rows(("tiingo", False, "timeout", False)), [])
        self.assertIn("[warn]", out)
        self.assertNotIn("[DOWN]", out)

    def test_required_down_is_stated_explicitly(self):
        out = DH.render(rows(("tws", False, "refused", True)), ["tws"])
        self.assertIn("REQUIRED DOWN: tws", out)

    def test_no_required_down_prints_no_alarm(self):
        out = DH.render(rows(("sina", True, "HTTP 200", False)), [])
        self.assertNotIn("REQUIRED DOWN", out)

    def test_json_carries_the_same_verdict(self):
        import json
        out = json.loads(DH.render(rows(("tws", False, "refused", True)), ["tws"], as_json=True))
        self.assertEqual(out["required_down"], ["tws"])
        self.assertFalse(out["results"][0]["ok"])
        self.assertIn("when", out)


class TestExitContract(unittest.TestCase):
    """The gate itself, with the probes replaced so no network is touched."""

    def _run_all_with(self, ok):
        from unittest import mock
        def fake(name, required=True):
            return lambda *a, **k: DH.RESULTS.append(
                {"source": name, "ok": ok, "detail": "", "secs": 0.0, "required": required})
        with mock.patch.object(DH, "probe_ibkr", lambda quick: fake("tws")(True) if ok
                               else fake("tws", required=True)(False)), \
             mock.patch.object(DH, "probe_futu", lambda quick: fake("futu_opend")(True)), \
             mock.patch.object(DH, "probe_thetadata", lambda quick: fake("thetadata")(True)), \
             mock.patch.object(DH, "probe_alpaca", lambda: (None, True)), \
             mock.patch.object(DH, "probe_http", lambda: fake("sina", required=False)(True)):
            return DH.run_all(quick=True)

    def test_a_down_required_source_makes_run_all_report_it(self):
        _, down = self._run_all_with(ok=False)
        self.assertIn("tws", down)

    def test_a_healthy_run_reports_nothing_down(self):
        _, down = self._run_all_with(ok=True)
        self.assertEqual(down, [])


if __name__ == "__main__":
    unittest.main()
