"""Tests for shard_control.progress — the stall signal.

Split from test_shard_control.py, which is at the 100-line cap. This guards the failure that
cost six hours on 2026-10-10: TWS went down, two shards retried forever BY DESIGN (the
downloader's breaker pauses and resets its counter), and the supervisor reported
`processed=0 errors=0 ratio=0.0%` — a number that reads as headroom. Nothing raised and
nothing stopped, so the only way to learn the sweep was dead was to read the log by hand.
"""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import shard_control as SC


def run(denoms, limit, start=0):
    """Feed interval progress deltas (0 = nothing happened) -> (idle, stopped, warnings)."""
    buf, idle, stopped = io.StringIO(), start, False
    with contextlib.redirect_stdout(buf):
        for denom in denoms:
            idle, stopped = SC.progress(idle, denom, limit)
            if stopped:
                break
    return idle, stopped, buf.getvalue().count("STALLED")


class TestProgress(unittest.TestCase):
    def test_progress_resets_the_stall_count(self):
        self.assertEqual(run([5], limit=10)[0], 0)

    def test_idle_accumulates(self):
        self.assertEqual(run([0, 0, 0], limit=10)[0], 3)

    def test_one_quiet_interval_is_not_a_stall(self):
        # A quiet minute between symbols is ordinary. Warning on it trains people to ignore
        # the warning, which is worse than not having one.
        self.assertEqual(run([0], limit=10)[2], 0)

    def test_zero_idle_never_warns(self):
        # The trap: `idle % limit == 0` is TRUE at idle=0, so a naive modulo would fire on a
        # perfectly healthy loop and call it stalled.
        self.assertEqual(run([1, 1, 1], limit=10)[2], 0)

    def test_warns_at_each_multiple_of_the_limit(self):
        idle, stopped, warns = run([0] * 30, limit=10)
        self.assertEqual(idle, 30)
        self.assertEqual(warns, 3, "should warn at 10, 20 and 30")
        self.assertFalse(stopped, "30 is below 6 x 10, so the sweep must still be running")

    def test_stops_at_six_times_the_limit(self):
        # The bound that makes a dead source exit rather than hang for days -- while still
        # giving a gateway restart an hour (at the default interval) to be picked up.
        idle, stopped, _ = run([0] * 200, limit=10)
        self.assertTrue(stopped)
        self.assertEqual(idle, 60)

    def test_real_progress_breaks_a_stall(self):
        idle, stopped, warns = run([0] * 9 + [4] + [0] * 5, limit=10)
        self.assertEqual(idle, 5, "the count restarts after progress, it does not pause")
        self.assertFalse(stopped)
        self.assertEqual(warns, 0, "9 idle intervals never reached the limit")


class TestCountsSinceTheLastStart(unittest.TestCase):
    """Here rather than in test_shard_control.py, which is at the 100-line cap.

    A stale count is what HID the stall: `counts` summed whole append-mode logs, so a restarted
    sweep opened on `processed=7253 errors=70 ratio=1.0%` — a number that reads as headroom —
    and a shard restarted by the controller had its earlier lines counted twice.
    """

    def _log(self, text):
        p = pathlib.Path(tempfile.mkdtemp()) / "shard0.log"
        p.write_text(text)
        return p

    def test_earlier_runs_are_not_counted(self):
        log = self._log("=== shard 0 start 2026-10-10T01:00:00Z ===\nA: +3 rows\nB: no bars\n"
                        "=== shard 0 start 2026-10-10T13:17:00Z ===\nC: +4 rows\n")
        self.assertEqual(SC.counts(log), (1, 0, 0), "only C, from the LATEST start")

    def test_a_log_with_no_marker_counts_nothing(self):
        # Not "counts everything": an unmarked log is not a shard log, and treating it as
        # progress is exactly the stale-count bug this replaced.
        self.assertEqual(SC.counts(self._log("A: +3 rows\nB: +4 rows\n")), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
