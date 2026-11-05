import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.trade_profile import ewz_diagonal_inputs as m

class QuoteValidation(unittest.TestCase):
    def test_stale_native_book_rejected_before_model(self):
        ids=(923031156,836892026,10753244)
        data=dict(snapshots=[],requested_utc='2026-10-19T14:01:00+00:00',
                  historical_bid_ask=[dict(contract={'conId':cid},ticks=[dict(
                      priceBid=1,priceAsk=2,sizeBid=100,sizeAsk=100,
                      time='2026-10-19T14:00:00+00:00')]) for cid in ids])
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'capture.json'
            path.write_text(json.dumps(data))
            with patch.object(m.bs,'USING_QUANTLIB',True),patch.object(m.bs,'implied_vol') as solve:
                with self.assertRaises(AssertionError):
                    m.build(path)
                solve.assert_not_called()
