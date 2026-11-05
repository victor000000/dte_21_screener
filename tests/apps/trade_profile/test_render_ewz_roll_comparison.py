import unittest
from apps.trade_profile.render_ewz_roll_comparison import render_ewz_roll_comparison

class RollComparison(unittest.TestCase):
    def test_frozen_contract_count_and_cover_ratio(self):
        legs=[dict(underlying='CRWD',day=day,contract='CRWD261120C00270000',qty_carried=-2,
                   spot_usd=-100,previous_close=3,current_close=5,broker='IBKR')
              for day in ('2026-10-20','2026-10-21','2026-10-23')]
        legs += [dict(underlying='EWZ',day='2026-10-20',contract=code,spot_usd=pnl)
                 for code,pnl in [('EWZ261120C00043000',-100),('EWZ261120C00050000',25)]]
        lines=[]
        render_ewz_roll_comparison(lines.append,legs)
        text='\n'.join(lines)
        self.assertIn('**−400** on the calls',text)
        self.assertIn('25% cover',text)
