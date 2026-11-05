import unittest
from datetime import date,timedelta
from apps.screener.cn_web_screen import screen


class CNScreenTests(unittest.TestCase):
    def test_same_source_distinct_days_and_strict_gate(self):
        rows=[{'underlying':'MA','source':'one','day':date(2026,1,1)+timedelta(days=i),'atm_iv':.1+i*.001} for i in range(60)]
        rows+=rows[:5]
        result=screen(rows,[{'product':'MA','venue':'CZCE'}])[0]
        self.assertEqual(result['observations'],60);self.assertEqual(result['ivr'],100)
        self.assertEqual(result['symbol'],'CN:CZCE:MA');self.assertTrue(result['qualifies'])

    def test_short_history_not_ranked(self):
        result=screen([{'underlying':'MA','source':'one','day':'2026-01-01','atm_iv':.2}],[])[0]
        self.assertIsNone(result['ivr']);self.assertFalse(result['qualifies'])
