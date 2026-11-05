import unittest
from unittest.mock import AsyncMock
from apps.trading_web.ibkr_execution import IBKRExecution
from apps.trading_web.tickets import normalize
from .support import ticket


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_combo_credit_routes_buy_with_negative_limit_and_exact_legs(self):
        client = IBKRExecution()
        client._connect = AsyncMock()
        class FakeIB:
            async def qualifyContractsAsync(self, c):
                c.conId = int(c.strike)
                c.localSymbol = f'{c.symbol}{c.lastTradeDateOrContractMonth[2:]}{c.right}{int(c.strike*1000):08d}'
                return [c]
        client.ib = FakeIB()
        raw = ticket(); raw['effect'] = 'credit'; raw['legs'][0]['intent'] = 'sell_to_open'
        second = raw['legs'][0].copy(); second.update(strike='545', intent='buy_to_open')
        raw['legs'].append(second)
        contract, order, _ = await client._build(normalize(raw), 'test-reference')
        self.assertEqual(contract.secType, 'BAG')
        self.assertEqual(order.action, 'BUY')
        self.assertEqual(order.lmtPrice, -1.25)
        self.assertEqual(order.account, 'PRIVATE_ACCOUNT')
        self.assertEqual([l.action for l in contract.comboLegs], ['SELL', 'BUY'])
        self.assertEqual([l.ratio for l in contract.comboLegs], [1, 1])
