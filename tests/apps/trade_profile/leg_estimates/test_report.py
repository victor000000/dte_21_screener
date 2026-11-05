"""Tests for the two renderers over the same rows."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
import bootstrap  # noqa: F401

from apps.trade_profile.leg_estimates import report


def row(**kw):
    r = {"underlying": "EWZ", "leg": "43C", "broker": "Schwab", "qty": -50,
         "account": "40342049SCHW", "sec_type": "OPT", "entry": 0.666, "mark": 2.38,
         "est": 2.451, "iv": 0.363, "delta": -10.6, "pnl_mark": -257.3,
         "pnl_est": -267.9, "target_50": 0.333, "expiry": None, "strike": 43.0,
         "call_put": "C", "theta": 70.6, "vega": -299.4, "est_mark_spot": 43.09,
         "rt_spot": 43.09}
    r.update(kw)
    return r


class TestTotals(unittest.TestCase):
    def test_theta_and_vega_sum_within_a_broker(self):
        th, vg = report._totals([row(), row(theta=10.0, vega=-5.0)], "Schwab")
        self.assertAlmostEqual(th, 80.6)
        self.assertAlmostEqual(vg, -304.4)

    def test_cn_figures_are_converted_to_usd(self):
        # The China account's theta and vega are stored in CNY. Summing them into
        # a "$/day" column without converting adds CNY to USD -- the bug the
        # original file carried a comment about.
        th_us, _ = report._totals([row(theta=713.0)], "Schwab")
        th_cn, _ = report._totals([row(theta=713.0)], "浙商期货")
        self.assertAlmostEqual(th_us, 713.0)
        self.assertAlmostEqual(th_cn, 100.0)

    def test_an_empty_group_does_not_divide_by_zero(self):
        th, vg = report._totals([], "Schwab")
        self.assertEqual((th, vg), (0.0, 0.0))


class TestMarkdown(unittest.TestCase):
    def test_writes_a_report_and_names_every_leg(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "reports").mkdir()
            path = report.markdown([row()], {}, root)
            text = path.read_text()
        self.assertIn("EWZ", text)
        self.assertIn("43C", text)
        self.assertIn("P/L% est", text)

    def test_stock_legs_render_a_dash_for_the_target(self):
        # A stock has no strike and no 50% credit; printing a number there would
        # invent one.
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "reports").mkdir()
            text = report.markdown([row(sec_type="STOCK", leg="STOCK")], {}, root).read_text()
        self.assertIn("—", text)

    def test_the_caveat_survives_into_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "reports").mkdir()
            text = report.markdown([row()], {}, root).read_text()
        self.assertIn("holds IV fixed", text)


class TestConsole(unittest.TestCase):
    def test_prints_and_names_the_broker(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            report.console([row()], {})
        out = buf.getvalue()
        self.assertIn("Schwab", out)
        self.assertIn("the read", out)


if __name__ == "__main__":
    unittest.main()
