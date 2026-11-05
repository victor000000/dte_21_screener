"""Tests for the HTTP probes — especially the Alpaca entitlement distinction.

This is the code that was supposed to stop the confusion that cost an hour, so it is tested
rather than trusted. `data.alpaca.markets` can be perfectly REACHABLE while every recent
option request is refused with 403 "OPRA agreement is not signed". A prober that collapses
those two into one verdict reports a broken entitlement as a healthy source, and the pipeline
then runs for hours fetching nothing.
"""
import json
import pathlib
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import ds_probe as DP
from scripts import ds_probe_http as PH


def http_error(code, body=b'{"message":"nope"}'):
    return urllib.error.HTTPError("https://x/", code, "err", {}, mock.Mock(read=lambda n: body))


class TestAlpacaEntitlement(unittest.TestCase):
    def setUp(self):
        DP.RESULTS.clear()

    def _patched(self, stock=None, option=None):
        import contextlib

        @contextlib.contextmanager
        def cm():
            yield None
        return stock, option

    def _run(self, stock_exc=None, option_exc=None):
        import urllib.request

        class FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "v2/stocks" in url:
                if stock_exc: raise stock_exc
                return FakeResp()
            if option_exc: raise option_exc
            return FakeResp()

        secrets = pathlib.Path(PH.ROOT) / "secrets" / "alpaca.json"
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
             mock.patch.object(pathlib.Path, "read_text",
                               lambda self: json.dumps({"key_id": "k", "secret": "s"})):
            return PH.probe_alpaca()

    def test_reachable_but_opra_unsigned_is_not_reported_as_entitled(self):
        _, ent = self._run(option_exc=http_error(403, b'{"message":"OPRA agreement is not signed"}'))
        self.assertFalse(ent, "a 403 must not read as entitled")
        self.assertTrue(DP.RESULTS[0]["ok"], "reachability itself is still fine")

    def test_the_detail_names_the_opra_problem(self):
        self._run(option_exc=http_error(403, b'{"message":"OPRA agreement is not signed"}'))
        self.assertIn("403", DP.RESULTS[0]["detail"])

    def test_a_working_option_call_is_entitled(self):
        _, ent = self._run()
        self.assertTrue(ent)
        self.assertIn("options OK", DP.RESULTS[0]["detail"])

    def test_unreachable_short_circuits(self):
        _, ent = self._run(stock_exc=urllib.error.URLError("no route"))
        self.assertIsNone(ent)
        self.assertFalse(DP.RESULTS[0]["ok"])

    def test_non_403_option_error_still_counts_as_entitled(self):
        # 5xx/timeouts are transport, not entitlement — they must not be read as "unsigned".
        _, ent = self._run(option_exc=http_error(500))
        self.assertTrue(ent)


if __name__ == "__main__":
    unittest.main()
