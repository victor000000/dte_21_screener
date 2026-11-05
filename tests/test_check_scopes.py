"""Code checks stay offline; explicit data audits still propagate failures."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tests import test_line_limit as size

class CheckScopes(unittest.TestCase):
    def test_reports_are_receipts_but_app_and_test_code_remain_checked(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('reports/receipt.py','apps/example.py','tests/test_example.py'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('pass\n'*101)
            with patch.object(size,'ROOT',root):
                self.assertEqual(set(size.offenders()),{'apps/example.py','tests/test_example.py'})

    def test_full_runtime_audit_failure_is_not_hidden(self):
        script=Path(__file__).resolve().parents[1]/'scripts/check_all.sh'
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir();(root/'bin').mkdir()
            (root/'scripts/check_all.sh').write_text(script.read_text())
            stub=root/'bin/uv'
            stub.write_text('#!/bin/sh\ncase "$*" in *risk_profile_check.py*) exit 7;; esac\ncat >/dev/null\nexit 0\n')
            stub.chmod(0o755)
            env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH'])
            for mode,expected in [('--fast',0),('--full',1)]:
                result=subprocess.run(['bash',str(root/'scripts/check_all.sh'),mode],
                                      env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
