"""Execution guard tests use fakes only; never submit to a broker."""
import tempfile
import threading
import unittest
from pathlib import Path
import requests
from apps.trading_web.tickets import normalize, check_holdings, alpaca_order, TicketError
from apps.trading_web.service import Service
from apps.trading_web.server import create_server


def ticket(intent='buy_to_open'):
    return dict(broker='alpaca', limit='1.25', effect='debit', legs=[
        dict(underlying='SPY', expiry='2099-12-18', strike='550', right='P', qty=2, intent=intent)])


class FakeBroker:
    def __init__(self):
        self.count = 0
        self.held = []
        self.working = []
        self.fail = False

    def account(self):
        return {'id': 'TEST_PAPER'}

    def positions(self):
        return self.held

    def orders(self):
        return self.working

    def fills(self):
        return []

    def prepare(self, draft):
        return {'account': self.account(), 'contracts': [], 'margin': 'unavailable'}

    def submit(self, draft, reference):
        self.count += 1
        if self.fail:
            raise TimeoutError('lost acknowledgement')
        return {'id': 'paper-order', 'reference': reference, 'status': 'new'}


