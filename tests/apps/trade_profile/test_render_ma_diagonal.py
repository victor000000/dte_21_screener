from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.trade_profile import render_ma_diagonal as m

class HeldLegValidation(unittest.TestCase):
    def test_missing_required_leg_does_not_publish(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'reports').mkdir()
            (root/'reports/position_delta_gamma_2026-10-19.csv').write_text('symbol\nMA612C3400\n')
            output=root/'output.html'
            with patch.multiple(m,ROOT=root,OUT=output),patch.object(m.bs,'USING_QUANTLIB',True):
                with self.assertRaises(AssertionError):
                    m.main()
            self.assertFalse(output.exists())
