"""Dispatch provider-owned market-data calls on the existing broker event loop."""
import asyncio
from data_providers.providers import ibkr_option_data


class IBKRMarket:
    async def _serialized(self, method, *args):
        if not hasattr(self, '_operation_lock'):
            self._operation_lock = asyncio.Lock()
        async with self._operation_lock:
            return await getattr(self, '_' + method)(*args)

    def market(self, operation, *args):
        return self.call('market', operation, *args)

    async def _market(self, operation, *args):
        await self._connect()
        if operation not in ('expiries', 'snapshots', 'chain', 'underlying'):
            raise ValueError('Unknown market operation')
        return await getattr(ibkr_option_data, operation)(self.ib, *args)
