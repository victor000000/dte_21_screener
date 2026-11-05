"""IBKR contract qualification, margin preview and explicit order actions."""
import asyncio
from ib_async import Option, Contract, ComboLeg, LimitOrder
from .tickets import TicketError

EXPECTED_ACCOUNT = "PRIVATE_ACCOUNT"


class IBKRExecution:
    async def _build(self, ticket, reference):
        await self._connect()
        contracts = []
        for leg in ticket['legs']:
            c = Option(leg['underlying'], leg['expiry'].replace('-', ''), float(leg['strike']), leg['right'],
                       exchange='SMART', currency='USD', multiplier='100')
            matches = await self.ib.qualifyContractsAsync(c)
            if len(matches) != 1 or matches[0].multiplier != '100' or matches[0].localSymbol.replace(' ', '') != leg['symbol']:
                raise TicketError('Contract qualification failed or contract is not a standard 100-share option.')
            contracts.append(matches[0])
        price = float(ticket['limit'])
        if len(contracts) == 1:
            contract = contracts[0]
            action = ticket['legs'][0]['side'].upper()
        else:
            contract = Contract(secType='BAG', symbol=contracts[0].symbol, currency='USD', exchange='SMART',
                                comboLegs=[ComboLeg(conId=c.conId, ratio=l['ratio'], action=l['side'].upper(), exchange='SMART')
                                           for c, l in zip(contracts, ticket['legs'])])
            action = 'BUY'
            if ticket['effect'] == 'credit':
                price = -price
        order = LimitOrder(action, ticket['units'], price, tif='DAY', account=EXPECTED_ACCOUNT, orderRef=reference,
                           outsideRth=False)
        return contract, order, contracts

    def prepare(self, ticket):
        return self.call('prepare', ticket)

    async def _prepare(self, ticket):
        contract, order, legs = await self._build(ticket, 'preview-only')
        margin = 'Margin preview unavailable.'
        try:
            result = await asyncio.wait_for(self.ib.whatIfOrderAsync(contract, order), timeout=8)
            margin = {k: getattr(result, k) for k in ('initMarginChange', 'maintMarginChange', 'equityWithLoanChange', 'warningText')}
        except Exception:
            margin = 'IBKR did not return a margin preview; inspect broker margin before submitting.'
        return dict(account=await self._account(), contracts=[{'symbol': c.localSymbol.replace(' ', ''), 'conId': c.conId, 'size': c.multiplier} for c in legs],
                    margin=margin, quote_note='No executable option quote loaded. Verify your limit in TWS.')

    def submit(self, ticket, reference):
        return self.call('submit', ticket, reference)

    async def _submit(self, ticket, reference):
        contract, order, _ = await self._build(ticket, reference)
        trade = self.ib.placeOrder(contract, order)
        await asyncio.sleep(1)
        return self._row(trade)

    def cancel(self, order_id):
        return self.call('cancel', order_id)

    async def _cancel(self, order_id):
        await self._connect()
        await self.ib.reqOpenOrdersAsync()
        trade = next((t for t in self.ib.openTrades() if str(t.order.orderId) == str(order_id)
                      and t.order.account == EXPECTED_ACCOUNT and t.order.clientId == 71), None)
        if trade is None:
            raise TicketError('Only open orders owned by this application client can be cancelled here.')
        self.ib.cancelOrder(trade.order)
        return {'status': 'Cancel requested; refresh for broker confirmation.'}
