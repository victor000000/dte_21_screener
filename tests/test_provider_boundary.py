"""The old import paths must resolve to the shared implementation, including private state."""
import unittest
import os
import pathlib
import subprocess
import sys
import tempfile

import data_providers.data.db
import data_providers.providers.source_rank
import data_providers.jobs.history.option_universe
from data import db
from datasources import source_rank
from apps.screener import option_universe


class ProviderBoundaryTests(unittest.TestCase):
    def test_legacy_modules_share_the_actual_module_object(self):
        self.assertIs(db, data_providers.data.db)
        self.assertIs(source_rank, data_providers.providers.source_rank)
        self.assertIs(option_universe, data_providers.jobs.history.option_universe)

    def test_storage_uses_the_shared_provider_runtime(self):
        import bootstrap
        self.assertEqual(db.ROOT, bootstrap.DATA_ROOT)
        self.assertNotEqual(db.ROOT, bootstrap.ROOT)

    def test_legacy_scripts_run_from_outside_the_application_without_credentials(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            for relative in ["apps/screener/download_atm_iv.py", "data/schema/cn.py",
                             "market_data/scripts/35_refresh_tail.py"]:
                result = subprocess.run([sys.executable, str(root / relative), "--help"],
                                        cwd=tmp, env=dict(os.environ, DATA_PROVIDERS_HOME=tmp),
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])
