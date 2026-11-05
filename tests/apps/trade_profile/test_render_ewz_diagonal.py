import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.trade_profile import render_ewz_diagonal as m

class DiagonalValidation(unittest.TestCase):
    def test_wrong_ratio_rejected_before_rendering(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            inputs=root/'input.json';output=root/'output.html'
            inputs.write_text(json.dumps(dict(valuation_date='2026-10-19',legs=[
                dict(expiry='2026-10-30',qty=-7),dict(expiry='2026-11-20',qty=20)])))
            with patch.object(m.bs,'USING_QUANTLIB',True):
                with self.assertRaises(AssertionError):
                    m.render(inputs,output)
            self.assertFalse(output.exists())
