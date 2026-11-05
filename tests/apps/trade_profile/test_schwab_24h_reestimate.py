from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.trade_profile import schwab_24h_reestimate as m

class SavedEvidenceRequired(unittest.TestCase):
    def test_missing_export_does_not_publish_a_new_estimate(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(m,'trading_logs_dir',return_value=root), \
                 patch.object(m.bs,'USING_QUANTLIB',True), \
                 patch('pathlib.Path.write_text') as write:
                with self.assertRaises(FileNotFoundError):
                    m.main()
                write.assert_not_called()
