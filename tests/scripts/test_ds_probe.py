"""Tests for the local-service probes.

No network and no live services: these assert the CONTRACT the rest of the health report
depends on — that a failed probe records a failure, and that `tcp` reports the failure
reason rather than raising. The prober's whole value is that it distinguishes "port open"
from "usable", so a probe that swallowed an error and recorded OK would make the report
actively misleading.
"""
import pathlib
import socket
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import ds_probe as DP


class TestRecord(unittest.TestCase):
    def setUp(self):
        DP.RESULTS.clear()

    def test_records_and_returns_the_verdict(self):
        self.assertTrue(DP.record("x", True, "fine"))
        self.assertFalse(DP.record("y", False, "bad"))
        self.assertEqual([r["source"] for r in DP.RESULTS], ["x", "y"])

    def test_failures_are_recorded_as_failures(self):
        DP.record("down", False, "refused")
        self.assertFalse(DP.RESULTS[0]["ok"])

    def test_required_defaults_true_so_a_new_probe_is_not_silently_optional(self):
        DP.record("p", True)
        self.assertTrue(DP.RESULTS[0]["required"])

    def test_optional_sources_can_be_marked_not_required(self):
        DP.record("tiingo", True, required=False)
        self.assertFalse(DP.RESULTS[0]["required"])

    def test_secs_is_rounded_for_a_stable_report(self):
        DP.record("x", True, secs=1.23456789)
        self.assertEqual(DP.RESULTS[0]["secs"], 1.235)


class TestTcp(unittest.TestCase):
    def test_reports_a_closed_port_as_failure_with_a_reason(self):
        # Port 1 on loopback is not going to be listening.
        ok, _, err = DP.tcp("127.0.0.1", 1, timeout=2)
        self.assertFalse(ok)
        self.assertTrue(err, "a failure with no reason is not diagnosable")

    def test_never_raises_and_always_returns_a_well_formed_triple(self):
        # Deliberately NOT asserting "unreachable" for 192.0.2.1 (TEST-NET-1) or for a bogus
        # hostname: on this box BOTH connected. The network answers even for .invalid and
        # something accepts TEST-NET-1, so an "unreachable" assertion here tests the network,
        # not the code. What the caller depends on is the shape and that it never throws.
        for host, port in (("192.0.2.1", 443), ("no-such-host.invalid", 443), ("127.0.0.1", 1)):
            res = DP.tcp(host, port, timeout=2)
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3)
            ok, secs, err = res
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(secs, float)
            self.assertIsInstance(err, str)
            if not ok:
                self.assertTrue(err, "a failure with no reason is not diagnosable")

    def test_succeeds_against_a_socket_we_open_ourselves(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        try:
            ok, _, err = DP.tcp("127.0.0.1", port, timeout=2)
            self.assertTrue(ok, err)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
