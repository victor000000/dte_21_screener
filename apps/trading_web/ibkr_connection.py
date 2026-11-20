"""Paper-only execution connection. The live quote gateway is never an implicit fallback."""
import json
import os
from pathlib import Path
import re

from ib_async import IB, StartupFetch

from .tickets import TicketError

PAPER_CONFIG = Path(__file__).resolve().parents[2] / '.local/trading-web/ibkr-paper.json'


def _paper_settings():
    try:
        config = json.loads(PAPER_CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise TicketError('Configure the IBKR paper account in .local/trading-web/ibkr-paper.json.') from exc
    account = config.get('account') if isinstance(config, dict) else None
    if not isinstance(account, str) or re.fullmatch(r'DU[0-9]+', account) is None:
        raise TicketError('IBKR execution requires a paper account ID beginning with DU.')

    override = os.getenv('TRADING_IB_PORT')
    try:
        port = int(override) if override else config.get('port')
    except ValueError as exc:
        raise TicketError('Invalid IBKR paper execution port.') from exc
    if port is None:
        return account, (4002, 7497)
    if type(port) is not int or not 1 <= port <= 65535:
        raise TicketError('Invalid IBKR paper execution port.')
    return account, (port,)


class IBKRConnection:
    def __init__(self):
        self.ib = None
        self._paper_account = None
        self._candidate_ports = ()
        self.connection_info = {}
        try:
            self._paper_account, self._candidate_ports = _paper_settings()
        except TicketError as exc:
            self.connection_info['detail'] = str(exc)

    async def _connect(self):
        if self._paper_account is None:
            raise TicketError(self.connection_info['detail'])
        if self.ib is None:
            self.ib = IB()
        if self.ib.isConnected():
            self._check_account()
            return self._paper_account

        failures = []
        for port in self._candidate_ports:
            try:
                await self.ib.connectAsync('127.0.0.1', port, clientId=71, timeout=4,
                                           readonly=False, fetchFields=StartupFetch.POSITIONS)
                self._check_account()
                self.connection_info = dict(connected=True, port=port)
                return self._paper_account
            except Exception as exc:
                self.ib.disconnect()
                failures.append(f'{port}: ' + (str(exc) if isinstance(exc, TicketError) else 'unavailable'))

        ports = ' or '.join(map(str, self._candidate_ports))
        detail = (f'Paper execution is disconnected. Enable the paper API on {ports}. '
                  'Only the exact configured account is accepted. ' + '; '.join(failures))
        self.connection_info = dict(connected=False, detail=detail)
        error = TicketError(detail)
        error.safe_detail = detail
        raise error

    def _check_account(self):
        if self.ib.managedAccounts() != [self._paper_account]:
            self.ib.disconnect()
            raise TicketError('IBKR execution refused: the connected accounts differ from the configured paper account.')

    def connection_status(self):
        configured = self._paper_account is not None
        connected = bool(configured and self.ib and self.ib.isConnected()
                         and self.ib.managedAccounts() == [self._paper_account])
        return dict(self.connection_info, connected=connected, configured=configured,
                    candidate_ports=list(self._candidate_ports), role='paper execution')
