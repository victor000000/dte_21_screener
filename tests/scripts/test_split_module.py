"""Tests for the splitter's validation, not its output."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

from scripts import split_module as SM


def spec_file(obj):
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "spec.json"
    p.write_text(json.dumps(obj))
    return p


SOURCE = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        (self.d / "src.py").write_text(SOURCE)
        self._root = SM.ROOT
        SM.ROOT = self.d
        (self.d / "src.py").write_text(SOURCE)

    def tearDown(self):
        SM.ROOT = self._root

    @staticmethod
    def quiet(spec):
        """Run the splitter with its report captured -- it prints on purpose."""
        with contextlib.redirect_stdout(io.StringIO()):
            return SM.build(str(spec))

    def spec(self, **kw):
        base = {"source": "src.py", "package": "pkg", "modules": {}, "drop": [], "keep": []}
        base.update(kw)
        return spec_file(base)

    def test_a_symbol_that_is_not_in_the_source_fails(self):
        rc = self.quiet(str(self.spec(modules={"m": ["nope"]})))
        self.assertEqual(rc, 1)

    def test_a_symbol_assigned_twice_fails(self):
        rc = self.quiet(str(self.spec(modules={"a": ["alpha"], "b": ["alpha"]})))
        self.assertEqual(rc, 1)

    def test_a_forgotten_symbol_fails(self):
        # alpha is neither assigned, dropped nor kept. Without this the function
        # stays in the source, the module that should hold it is short one, and
        # nothing says so until a caller fails.
        rc = self.quiet(str(self.spec(modules={"m": ["beta"]})))
        self.assertEqual(rc, 1)

    def test_an_explicitly_kept_symbol_is_allowed(self):
        rc = self.quiet(str(self.spec(modules={"m": ["beta"]}, keep=["alpha"])))
        self.assertEqual(rc, 0)

    def test_nothing_is_written_on_a_dry_run(self):
        self.quiet(str(self.spec(modules={"m": ["alpha", "beta"]})))
        self.assertFalse((self.d / "pkg").exists())


if __name__ == "__main__":
    unittest.main()
