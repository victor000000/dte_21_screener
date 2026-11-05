"""Paper-only execution connection. The live quote gateway is never an implicit fallback."""
import json
from pathlib import Path
import os
from ib_async import IB, StartupFetch
from .tickets import TicketError

EXPECTED_ACCOUNT = 'PRIVATE_ACCOUNT'
PAPER_CONFIG = Path(__file__).resolve().parents[2] / '.local/trading-web/ibkr-paper.json'


def ports():
    value = os.getenv('TRADING_IB_PORT')
    if value:
        return [int(value)]
    if PAPER_CONFIG.exists():
        config = json.loads(PAPER_CONFIG.read_text())
        port = config.get('port')
        if config.get('account') != EXPECTED_ACCOUNT or type(port) is not int or not 1 <= port <= 65535:
            raise TicketError('Invalid saved IBKR paper connection configuration')
        return [port]
    return [4002, 7497]


class IBKRConnection:
    async def _connect(self):
        if self.ib is None:
            self.ib = IB()
        if self.ib.isConnected():
            return self._check_account()
        failures = []
        for port in ports():
            try:
                await self.ib.connectAsync('127.0.0.1', port, clientId=71, timeout=4,
                                           readonly=False, fetchFields=StartupFetch.POSITIONS)
                self._check_account()
                self.connection_info = dict(connected=True, account=EXPECTED_ACCOUNT, port=port, role='paper execution')
                return
            except Exception as exc:
                self.ib.disconnect()
                failures.append(f'{port}: '+(str(exc) if isinstance(exc, TicketError) else 'unavailable'))
        detail = (f'Paper account {EXPECTED_ACCOUNT} is not connected. Log in to a separate paper TWS/Gateway '
                  f'and enable its API on {" or ".join(map(str, ports()))}. '
                  'Only the exact configured paper account is accepted for orders. '+ '; '.join(failures))
        self.connection_info = dict(connected=False, role='paper execution', detail=detail)
        error = TicketError(detail);error.safe_detail = detail
        raise error

    def _check_account(self):
        if self.ib.managedAccounts() != [EXPECTED_ACCOUNT]:
            self.ib.disconnect()
            raise TicketError(f'Paper execution refused: expected only {EXPECTED_ACCOUNT}; connected account differs.')

    def connection_status(self):
        return dict(getattr(self, 'connection_info', {}), connected=bool(self.ib and self.ib.isConnected()),
                    expected_account=EXPECTED_ACCOUNT, candidate_ports=ports(), role='paper execution')
