"""Every numbered script in market_data must refuse to run on --help.

The invariant, checked over the folder rather than argued about. None of these scripts
takes an argument, so `--help` is not a question -- it is a full run: it downloaded six
symbols before this was fixed, and 39/45/60 rewrite or delete price data and the
warehouse.

Seven of them guard themselves inline with `print(__doc__)`. That is correct ONLY when
the file really opens with a docstring, which is asked of the AST below -- asked of the
first line, a shebang makes all seven look unguarded.
"""
import ast
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401


class TestEveryNumberedScriptIsGuarded(unittest.TestCase):
    def test_none_of_them_would_run_on_help(self):
        # The real invariant, checked over the folder rather than argued about.
        import data_providers.warehouse
        d = pathlib.Path(data_providers.warehouse.__file__).parent
        unguarded = []
        for p in sorted(d.glob("[0-9]*.py")):
            s = p.read_text()
            if "helpguard.handle_help" in s:
                continue
            if '"--help" in sys.argv' in s and "__doc__" in s:
                # Their inline form prints `__doc__`, which is correct ONLY IF the file
                # really opens with a docstring. Asked of the AST, not of the first
                # line -- these files start with a shebang, so a `startswith('"""')`
                # test called all seven of them unguarded.
                first = ast.parse(s).body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    continue
            unguarded.append(p.name)
        self.assertEqual(unguarded, [], "these run their whole job on --help")


if __name__ == "__main__":
    unittest.main()
