"""`--help` must not be a write.

Measured 2026-10-06: `market_data/scripts/30_download_missing.py --help` DOWNLOADED SIX
SYMBOLS. None of the twenty numbered scripts in that folder takes an argument, so
`--help` is not a question -- it is a full run. The parent repo has the same guard after
a 2026-10-05 sweep ran every app with `--help` and rewrote `fills`.

The summary is read from the SOURCE, not `__doc__`: a docstring must be the first
statement, and these scripts open with a sys.path bootstrap, so the string a reader sees
as the description is not bound to `__doc__`.
"""
import ast
import contextlib
import io
import pathlib
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

sys.path.insert(0, str(pathlib.Path(bootstrap.ROOT / "market_data" / "scripts")))
import helpguard as H  # noqa: E402


def write(tmp, body):
    p = pathlib.Path(tmp) / "script.py"
    p.write_text(textwrap.dedent(body))
    return p


class TestItOnlyFiresOnHelp(unittest.TestCase):
    def test_a_normal_run_is_not_intercepted(self):
        self.assertFalse(H.handle_help("x.py", argv=["--retry"]))

    def test_no_arguments_is_a_normal_run(self):
        # The empty argv is the DANGEROUS case -- it is the real run -- so it must not
        # be caught by a guard that meant to catch only --help.
        self.assertFalse(H.handle_help("x.py", argv=[]))

    def test_help_exits(self):
        # stdout suppressed: these call the REAL handler, which prints a summary, and
        # the gate pipes this run's output. Uncaptured, every test run announces
        # "(no module summary in x.py)" as though the gate had something to say.
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                H.handle_help("x.py", argv=["--help"])
            self.assertEqual(e.exception.code, 0)

    def test_dash_h_also_exits(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                H.handle_help("x.py", argv=["-h"])


class TestTheSummaryComesFromTheSource(unittest.TestCase):
    def test_it_finds_a_description_the_bootstrap_pushed_down(self):
        # THE bug: the string sits AFTER `import config`, so `__doc__` is None for it.
        with tempfile.TemporaryDirectory() as d:
            p = write(d, '''
                import sys
                sys.path.insert(0, "x")
                import config as C

                """A description that is not __doc__."""
            ''')
            self.assertEqual(H.module_summary(p), ["A description that is not __doc__."])

    def test_a_real_docstring_is_found_too(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, '''
                """Up top, where a docstring belongs."""
                import sys
            ''')
            self.assertEqual(H.module_summary(p), ["Up top, where a docstring belongs."])

    def test_a_file_with_no_description_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(H.module_summary(write(d, "import sys\n")))

    def test_a_broken_file_does_not_raise(self):
        # The guard runs before anything else; a syntax error in the script it guards
        # must not become a crash in the guard.
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(H.module_summary(write(d, "def (:\n")))


if __name__ == "__main__":
    unittest.main()
