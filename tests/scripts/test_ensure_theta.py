"""A configured remote terminal must not trigger a second local Java process."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]


class RemoteThetaStartupTests(unittest.TestCase):
    def test_remote_health_controls_exit_without_local_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'scripts').mkdir();(root/'.venv/bin').mkdir(parents=True)
            script=root/'scripts/ensure_thetadata.sh'
            script.write_text((ROOT.parent/'data_providers/scripts/ensure_thetadata.sh').read_text())
            python=root/'.venv/bin/python'
            python.write_text('#!/bin/bash\nexit "$THETA_HEALTH_TEST_RC"\n');python.chmod(0o755)
            for health,expected,message in [('0',0,'configured endpoint is serving'),
                                             ('2',1,'configured remote endpoint unavailable')]:
                env=dict(os.environ,THETA_HEALTH_TEST_RC=health,DATA_PROVIDERS_HOME=tmp)
                result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
                self.assertIn(message,result.stdout)
                self.assertFalse((root/'logs/thetadata_terminal.log').exists())
