"""Universe selection gates on IV range rank while preserving cache-only operation."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import duckdb
from apps.screener import build_screen_universe as universe
from tests.compute.test_iv_rank import rows


class TestUniverseIVRank(unittest.TestCase):
    def test_high_percentile_low_rank_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with duckdb.connect(str(root / "market_history.duckdb")) as history:
                history.execute("CREATE TABLE iv_history (underlying TEXT, source TEXT, day DATE, atm_iv DOUBLE)")
                for symbol, values in (("META", [0.1] * 58 + [1.1, 0.2]),
                                       ("SPY", [0.1] * 59 + [0.2])):
                    for source, day, value in rows(values):
                        history.execute("INSERT INTO iv_history VALUES (?, ?, ?, ?)", [symbol, source, day, value])
            cache = root / "caps.json"
            cache.write_text(json.dumps({"META": 2e12, "SPY": 1e12}))
            out = root / "universe.txt"
            con = duckdb.connect(":memory:")
            with mock.patch.object(universe.db, "connect", return_value=con), \
                 mock.patch.object(universe, "liquidity", return_value={"META": (1e7, 100), "SPY": (1e7, 100)}), \
                 mock.patch.object(universe.bootstrap, "DATA_ROOT", root), \
                 mock.patch.object(universe, "market_caps", side_effect=AssertionError("vendor refresh")), \
                 mock.patch("sys.argv", ["universe", "--cached-caps-only", "--cache", str(cache), "--out", str(out)]):
                universe.main()
            names = [s for s in out.read_text().splitlines() if s and not s.startswith("#")]
            self.assertEqual(names, ["SPY"])
            self.assertIn("IVR uses min/max range", out.read_text())


if __name__ == "__main__":
    unittest.main()
