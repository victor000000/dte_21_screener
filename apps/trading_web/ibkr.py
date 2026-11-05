"""IBKR paper execution on a dedicated asyncio thread; exact account allowlist."""
import asyncio
import os
import threading
from decimal import Decimal
from ib_async import IB, StartupFetch
from .ibkr_execution import IBKRExecution
from .ibkr_market import IBKRMarket
from .ibkr_connection import IBKRConnection
from .tickets import TicketError
EXPECTED_ACCOUNT = 'PRIVATE_ACCOUNT'

def occ(c):
    return f'{c.symbol}{c.lastTradeDateOrContractMonth[2:8]}{c.right}{int(Decimal(str(c.strike)) * 1000):08d}'


class IBKR(IBKRConnection, IBKRExecution, IBKRMarket):
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.ib = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, method, *args):
        task = asyncio.run_coroutine_threadsafe(self._serialized(method, *args), self.loop)
        try:
            return task.result(timeout=45)
        except TimeoutError as exc:
            task.cancel()
            raise TicketError('IBKR timed out. A submission may be pending; reconcile Orders before retrying.') from exc

    def account(self):
        return self.call('account')

    async def _account(self):
        await self._connect()
        rows = await asyncio.wait_for(self.ib.accountSummaryAsync(EXPECTED_ACCOUNT), 8)
        net = next((v for v in rows if v.tag == 'NetLiquidation' and v.account == EXPECTED_ACCOUNT), None)
        currency = net.currency if net and net.currency != 'BASE' else None
        def value(tag):
            return next((v.value for v in rows if v.tag == tag and v.account == EXPECTED_ACCOUNT
                         and v.currency == currency), None)
        return dict(id=EXPECTED_ACCOUNT, equity=value('NetLiquidation'), buying_power=value('BuyingPower'),
                    currency=currency, source='IBKR Paper')

    def positions(self):
        return self.call('positions')

    async def _positions(self):
        await self._connect()
        rows = await asyncio.wait_for(self.ib.reqPositionsAsync(), 8)
        return [dict(symbol=occ(p.contract) if p.contract.secType == 'OPT' else p.contract.localSymbol,
                     qty=p.position, average=p.avgCost / float(p.contract.multiplier or 1), mark=None, pnl=None,
                     asset_class='us_option' if p.contract.secType == 'OPT' else p.contract.secType,
                     source='IBKR holdings; mark not requested', multiplier=p.contract.multiplier,
                     currency=p.contract.currency, underlying=p.contract.symbol, con_id=p.contract.conId)
                for p in rows if p.account == EXPECTED_ACCOUNT and p.position]

    def orders(self):
        return self.call('orders')

    async def _orders(self):
        await self._connect()
        active = await asyncio.wait_for(self.ib.reqAllOpenOrdersAsync(), 8)
        completed = await asyncio.wait_for(self.ib.reqCompletedOrdersAsync(apiOnly=False), 8)
        trades = {str(t.order.permId or t.order.orderId): t for t in [*completed, *self.ib.trades(), *active]}
        return [self._row(t) for t in trades.values() if t.order.account == EXPECTED_ACCOUNT]

    def _row(self, trade):
        c, o, s = trade.contract, trade.order, trade.orderStatus
        symbols = [occ(c)] if c.secType == 'OPT' else []
        return dict(id=str(o.orderId), reference=o.orderRef, status=s.status, active=not trade.isDone(),
                    symbols=symbols, underlying=c.symbol, combo=c.secType == 'BAG', qty=float(o.totalQuantity),
                    filled=float(s.filled), price=o.lmtPrice, updated=None,
                    cancellable=not trade.isDone() and o.clientId == 71,
                    messages=[l.message for l in trade.log if l.message][-3:])

    def fills(self):
        return self.call('fills')

    async def _fills(self):
        await self._connect()
        rows = await self.ib.reqExecutionsAsync()
        return [dict(id=f.execution.execId, symbol=occ(f.contract) if f.contract.secType == 'OPT' else f.contract.localSymbol,
                     qty=f.execution.shares, side=f.execution.side, price=f.execution.price, time=f.time.isoformat())
                for f in rows if f.execution.acctNumber == EXPECTED_ACCOUNT]

