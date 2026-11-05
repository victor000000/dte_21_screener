"""A launched process retains its identity across exec and rejects reused/corrupt PIDs."""
import os
import pathlib
import signal
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]


class JobProcessIdentityTests(unittest.TestCase):
    def test_exec_remains_running_and_mismatched_birth_cannot_match_by_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'scripts').mkdir()
            script=root/'scripts/job.sh'
            script.write_text((ROOT.parent/'data_providers/scripts/job.sh').read_text().replace('sleep 20','sleep .2'))
            wrapper=root/'wrapper.sh';wrapper.write_text('#!/bin/bash\nexec sleep 30\n')
            start=subprocess.run(['bash',str(script),'exec_case','bash',str(wrapper)],
                                 capture_output=True,text=True)
            marker=root/'var/run/exec_case.pid';lines=marker.read_text().splitlines()
            pid=int(lines[0])
            try:
                self.assertEqual(start.returncode,0,start.stdout+start.stderr)
                self.assertEqual(len(lines),3)
                self.assertIn(':',lines[2])
                self.assertTrue(pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().startswith(b'sleep\0'))
                status=subprocess.run(['bash',str(script),'--status'],capture_output=True,text=True)
                self.assertIn('RUNNING',status.stdout)
                repeat=subprocess.run(['bash',str(script),'exec_case','bash',str(wrapper)],
                                      capture_output=True,text=True)
                self.assertIn('already running',repeat.stdout)
                self.assertEqual(marker.read_text().splitlines()[0],str(pid))
                # Even an exact argv match cannot override a mismatched birth identity.
                marker.write_text(f'{pid}\nsleep 30\n{lines[2]}0\n')
                status=subprocess.run(['bash',str(script),'--status'],capture_output=True,text=True)
                self.assertIn('STOPPED',status.stdout)
            finally:
                marker.write_text('\n'.join(lines)+'\n')
                os.killpg(pid,signal.SIGTERM)
