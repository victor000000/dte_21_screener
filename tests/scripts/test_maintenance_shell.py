"""Regression checks for background maintenance supervision."""
import pathlib
import os
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class MaintenanceShellTests(unittest.TestCase):
    def test_shared_maintenance_delegation_preserves_flags_and_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'scripts').mkdir()
            (root / '.venv/bin').mkdir(parents=True)
            script = root / 'scripts/update_all.sh'
            script.write_text((ROOT / 'scripts/update_all.sh').read_text())
            python = root / '.venv/bin/python'
            python.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit 2\n')
            python.chmod(0o755)
            result = subprocess.run(['bash', str(script), '--us-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(result.stdout.splitlines(),
                             ['-m', 'data_providers.cli', 'maintain', '--execute', '--us-only'])
            python.write_text('#!/bin/bash\nexit 0\n')
            result = subprocess.run(['bash', str(script), '--us-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_env_exec_identity(self):
        source = (ROOT.parent / 'data_providers/scripts/job.sh').read_text()
        alive = source[source.index('alive() {'):source.index('\nstatus() {')]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            child = subprocess.Popen(['env', 'MAINTENANCE_TEST=1', 'sleep', '30'])
            try:
                for _ in range(100):
                    if pathlib.Path(f'/proc/{child.pid}/cmdline').read_bytes().startswith(b'sleep\0'):
                        break
                    time.sleep(0.01)
                marker = root / 'job.pid'
                marker.write_text(f'{child.pid}\nenv MAINTENANCE_TEST=1 sleep 30\n')
                command = ['bash', '-c', f'RUN="$1"\n{alive}\nalive job', 'bash', tmp]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(child.pid))
                marker.write_text(f'{child.pid}\nenv MAINTENANCE_TEST=1 sleep 31\n')
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
            finally:
                child.terminate()
                child.wait()


    def test_fast_job_reports_its_actual_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'scripts').mkdir()
            script = root / 'scripts/job.sh'
            # Shorten only the launch observation window for this subprocess test.
            script.write_text((ROOT.parent / 'data_providers/scripts/job.sh').read_text().replace('sleep 20', 'sleep 0.1'))
            for command, expected in [('true', 0), ('false', 3)]:
                result = subprocess.run(['bash', str(script), command, command],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if expected == 0:
                    self.assertIn('completed successfully', result.stdout)
                else:
                    self.assertIn('rc=1', result.stdout)


    def test_env_wrapped_bash_with_semicolons_is_recognized(self):
        source = (ROOT.parent / 'data_providers/scripts/job.sh').read_text()
        alive = source[source.index('alive() {'):source.index('\nstatus() {')]
        with tempfile.TemporaryDirectory() as tmp:
            command = 'sleep 30 & wait; :'
            child = subprocess.Popen(['env', 'MAINTENANCE_TEST=1', 'bash', '-c', command],
                                     start_new_session=True)
            try:
                for _ in range(100):
                    if pathlib.Path(f'/proc/{child.pid}/cmdline').read_bytes().startswith(b'bash\0'):
                        break
                    time.sleep(.01)
                pathlib.Path(tmp, 'job.pid').write_text(
                    f'{child.pid}\nenv MAINTENANCE_TEST=1 bash -c {command}\n')
                result = subprocess.run(['bash','-c',f'RUN="$1"\n{alive}\nalive job','bash',tmp],
                                        capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),str(child.pid))
            finally:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait()
