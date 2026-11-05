"""The writer and the reader of the risk report must ask the SAME clock for its name.

`risk_profile` writes `reports/risk_profile_<date>.md` with `clock.today()`;
`risk_profile_check` looks for it by name. Both used to reach for the date differently --
one `clock.today()`, one `dt.date.today()` -- and they agreed only because `bootstrap`
pins TZ=UTC at import. That is correct today and invisible at the call site: on this box
the system zone is Asia/Shanghai, so a process that did NOT import bootstrap first would
ask for tomorrow's file after 16:00 UTC, find nothing, and fail the gate with "today's
risk profile report exists: missing".

This asserts the rule rather than the current agreement. `clock.py` states it: use
`clock.now()`/`clock.today()` for anything STORED, COMPARED against a stored stamp, or
used to NAME an artifact.
"""
import ast
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import bootstrap  # noqa: F401

ROOT = bootstrap.ROOT

#: Files that name or look for the artifact, and so must use the repo's clock.
ARTIFACT_FILES = ("apps/trade_profile/risk_profile.py",
                  "apps/audit/risk_profile_check.py",
                  "apps/plan/build_positions.py")


def date_today_calls(path):
    """Every real `<something>.date.today()` call, found in the AST, not the text.

    The AST matters: a regex also matches the comments that explain why not to call it,
    which is how an earlier version of this test failed on its own documentation.
    """
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "today"):
            continue
        base = node.func.value
        # `clock.today()` is the one we want; `date.today()` and `dt.date.today()` are not.
        if isinstance(base, ast.Name) and base.id == "clock":
            continue
        out.append(ast.unparse(node.func))
    return out


class TestNoBareLocalDate(unittest.TestCase):
    def test_they_do_not_call_date_today(self):
        # `dt.date.today()` reads the SYSTEM zone. bootstrap happens to pin it to UTC,
        # which is why this passed for months -- the point is that the correctness must
        # not depend on an import that is not visible at the call site.
        offenders = {rel: date_today_calls(ROOT / rel) for rel in ARTIFACT_FILES
                     if date_today_calls(ROOT / rel)}
        self.assertEqual(offenders, {},
                         "use clock.today(): these read the system zone, and the report "
                         "filename would roll over eight hours early")

    def test_the_writer_and_the_reader_name_it_the_same_way(self):
        writer = (ROOT / "apps/trade_profile/risk_profile.py").read_text()
        reader = (ROOT / "apps/audit/risk_profile_check.py").read_text()
        self.assertIn("clock.today()", writer)
        self.assertIn("clock.today()", reader)
        for text, label in ((writer, "writer"), (reader, "reader")):
            self.assertIn("risk_profile_", text,
                          f"{label} no longer names the artifact -- update this test")


if __name__ == "__main__":
    unittest.main()
