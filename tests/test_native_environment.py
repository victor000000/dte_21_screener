"""Broker defaults respect native WSL, container isolation, and explicit hosts."""
import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class NativeEnvironmentTests(unittest.TestCase):
    def inspect_bootstrap(self, container=False, overrides=None):
        env = dict(os.environ)
        for name in ("IB_HOST", "FUTU_HOST"):
            env.pop(name, None)
        env.update(overrides or {})
        code = f"""
import json, os, pathlib, platform
platform.release = lambda: '6.6-microsoft-standard-WSL2'
original_exists = pathlib.Path.exists
pathlib.Path.exists = lambda p: {container!r} if str(p) == '/.dockerenv' else original_exists(p)
import bootstrap
print(json.dumps([os.environ.get('IB_HOST'), os.environ.get('FUTU_HOST')]))
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_native_wsl_defaults_to_windows_localhost(self):
        self.assertEqual(self.inspect_bootstrap(), ["127.0.0.1", "127.0.0.1"])

    def test_explicit_hosts_win(self):
        self.assertEqual(self.inspect_bootstrap(overrides={"IB_HOST": "gateway.test",
                                                          "FUTU_HOST": "opend.test"}),
                         ["gateway.test", "opend.test"])

    def test_container_leaves_provider_defaults_intact(self):
        self.assertEqual(self.inspect_bootstrap(container=True), [None, None])
