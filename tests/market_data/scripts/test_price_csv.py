"""A legitimate price restatement can still replace every retained date."""
import pathlib
import tempfile
import unittest
import pandas as pd
from market_data.scripts.price_csv import rewrite_validated


class AtomicPriceCsvTests(unittest.TestCase):
    def test_valid_adjustment_is_published_without_losing_dates(self):
        frame=pd.DataFrame({'Open':[100.,110.],'High':[110.,120.],
                            'Low':[90.,100.],'Close':[100.,110.],'Volume':[100,200]},
                           index=pd.to_datetime(['2026-10-14','2026-10-15']))
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'saved.csv'
            path.write_text('14102026,100,110,90,100,100\n15102026,110,120,100,110,200\n')
            original_mode=path.stat().st_mode & 0o777
            rewrite_validated(str(path),frame,pd.Series([.9,1.],index=frame.index),.0001)
            self.assertEqual(path.read_text().splitlines(),[
                '14102026,90.0000,99.0000,81.0000,90.0000,100',
                '15102026,110.0000,120.0000,100.0000,110.0000,200'])
            self.assertEqual(list(pathlib.Path(tmp).iterdir()),[path])
            self.assertEqual(path.stat().st_mode & 0o777,original_mode)
