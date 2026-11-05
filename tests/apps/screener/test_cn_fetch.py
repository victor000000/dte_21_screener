"""test_cn_fetch.py — three ways the CN backfill lost data quietly, all measured 2026-10-08.

  * akshare passes no timeout, so a rate-limiting SYN drop parked a worker on the kernel's
    connect timeout before `retry()` could see anything. `socket.setdefaulttimeout` does NOT
    reach requests (it passes timeout=None explicitly) -- hence the patch at Session.request,
    and a test that drives a real local silent server rather than mocking the socket.
  * a dead connection and an unlisted month landed in one bare `except`, so a hole in the
    series was logged as "unlisted" and never retried.
  * a DNS blip on one product's underlying path ended a four-product run 70 minutes in.
"""
import contextlib, io, pathlib, socket, sys, threading, time, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

import requests

from apps.screener.cn_iv import fetch


class TestBounded(unittest.TestCase):
    def setUp(self):
        self._orig = requests.Session.request

    def tearDown(self):
        requests.Session.request = self._orig      # never leak a 1s limit into other tests

    def test_fills_only_a_missing_timeout(self):
        seen = []
        with mock.patch.object(requests.Session, "request",
                               lambda self, m, u, **kw: seen.append(kw)):
            fetch.bounded(7)
            requests.get("http://x.invalid/")
            requests.get("http://x.invalid/", timeout=1)
        self.assertEqual([k.get("timeout") for k in seen], [7, 1])

    def test_a_silent_server_times_out(self):
        """The read timeout, which nothing else bounds: the remote accepts then says nothing."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        threading.Thread(target=lambda: (srv.accept(), time.sleep(5)), daemon=True).start()
        fetch.bounded(1)
        t0 = time.time()
        with self.assertRaises(requests.exceptions.RequestException):
            requests.get(f"http://127.0.0.1:{port}/")
        self.assertLess(time.time() - t0, 3.0, "the injected timeout did not bite")


class TestTable(unittest.TestCase):
    def test_keyerror_is_unlisted(self):
        with self.assertRaises(fetch.Unlisted):
            fetch.table(lambda: (_ for _ in ()).throw(KeyError("乙二醇")), "eg2307")

    def test_a_real_failure_retries_then_raises(self):
        calls = []

        def boom():
            calls.append(1)
            raise ValueError("connection reset")

        with self.assertRaises(ValueError):
            fetch.table(boom, "eg2308", tries=3)
        self.assertEqual(len(calls), 3, "a non-Unlisted failure must be retried")

    def test_success_is_returned_without_retrying(self):
        calls = []

        def ok():
            calls.append(1)
            return "grid"

        self.assertEqual(fetch.table(ok, "x"), "grid")
        self.assertEqual(len(calls), 1)


class TestPathOrNone(unittest.TestCase):
    def test_a_failure_skips_the_product_and_a_success_passes_through(self):
        """2026-10-09: a DNS blip on this call ended a four-product leg 70 minutes in."""
        self.assertIsNone(fetch.path_or_none(lambda: 1 / 0, "DCE:M"))
        self.assertEqual(fetch.path_or_none(lambda: {"d": 1}, "DCE:M"), {"d": 1})


class TestReport(unittest.TestCase):
    def test_the_two_fates_are_named_separately(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fetch.report(["eg1902", "eg1903"], ["eg2308"])
        out = buf.getvalue()
        self.assertIn("2 month(s) unlisted", out)
        self.assertIn("WARN 1 month(s) NOT ANSWERED", out)
        self.assertIn("HOLES", out)

    def test_clean_run_prints_nothing(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fetch.report([], [])
        self.assertEqual(buf.getvalue(), "")
