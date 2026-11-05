import unittest
from unittest.mock import AsyncMock,patch
from apps.trading_web.ibkr_market import IBKRMarket


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_market_reads_dispatched(self):
        m=IBKRMarket();m._connect=AsyncMock();m.ib=object()
        with self.assertRaises(ValueError):await m._market('submit')
        with patch('apps.trading_web.ibkr_market.ibkr_option_data.expiries',new_callable=AsyncMock) as fn:
            await m._market('expiries','SPY')
            fn.assert_awaited_once_with(m.ib,'SPY')


import asyncio
import unittest
from apps.trading_web.ibkr_market import IBKRMarket


class SerialTests(unittest.IsolatedAsyncioTestCase):
    async def test_broker_operations_do_not_interleave(self):
        events=[]
        class Broker(IBKRMarket):
            async def _operation(self, name):
                events.append(name+' start')
                await asyncio.sleep(.01)
                events.append(name+' end')
        b=Broker()
        await asyncio.gather(b._serialized('operation','quote'),b._serialized('operation','account'))
        self.assertEqual(events,['quote start','quote end','account start','account end'])
