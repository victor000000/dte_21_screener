import unittest
from unittest.mock import Mock, patch
from datetime import date, datetime, timezone, timedelta
from contextlib import nullcontext
from apps.trading_web.portfolio_risk import report
from apps.trading_web.tickets import TicketError
from .support import ticket


class PortfolioRiskTests(unittest.TestCase):
    def service(self):
        broker=Mock()
        broker.account.return_value=dict(id='TEST',equity='100000',currency='USD')
        broker.positions.return_value=[dict(symbol='SPY',underlying='SPY',qty=10,asset_class='STK',currency='USD')]
        broker.orders.return_value=[]
        service=Mock(lock=nullcontext())
        service.broker.return_value=broker
        return service

    def test_wrong_broker_or_ticket_rejected(self):
        for raw in (dict(broker='alpaca'),dict(broker='ibkr',ticket=ticket())):
            with self.assertRaises(TicketError):report(self.service(),raw)

    def test_no_equity_is_not_zero_risk(self):
        s=self.service();s.broker.return_value.account.return_value['equity']=None
        r=report(s)
        self.assertEqual(r['status'],'unavailable')
        self.assertTrue(all(h['current'] is None for h in r['horizons']))

    def test_unsupported_position_blocks_entire_book(self):
        s=self.service();s.broker.return_value.positions.return_value[0]['asset_class']='FUT'
        r=report(s)
        self.assertIn('not modeled',r['issues'][0])
        self.assertEqual(r['status'],'unavailable')

    @patch('apps.trading_web.portfolio_risk.read_inputs')
    def test_stale_history_retains_provenance_and_no_numbers(self,read):
        read.return_value={'SPY':dict(asof=date(2020,1,1),history={},source='fixture',release='test',spot=100)}
        r=report(self.service())
        self.assertEqual(r['inputs'][0]['asof'],'2020-01-01')
        self.assertIn('Stale',r['issues'][0])
        self.assertTrue(all(h['current'] is None for h in r['horizons']))

    @patch('apps.trading_web.portfolio_risk.read_inputs')
    def test_fresh_stock_estimate_is_not_clearance(self,read):
        from tests.apps.trade_profile.test_portfolio_cvar import PortfolioCVaRTests
        _,history,_=PortfolioCVaRTests().fixture()
        read.return_value={'SPY':dict(asof=datetime.now(timezone.utc).date()-timedelta(days=1),history=history,source='fixture',release='test',spot=100)}
        r=report(self.service())
        self.assertEqual(r['status'],'conditional estimate')
        self.assertIn('not a trade approval',r['decision'])
        self.assertEqual(len(r['horizons']),6)

    def test_risk_endpoint_requires_local_origin_and_token(self):
        import threading
        import requests
        from apps.trading_web.server import create_server
        server=create_server(0,self.service())
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        client=requests.Session();client.trust_env=False
        base='http://127.0.0.1:'+str(server.server_address[1])
        self.assertEqual(client.post(base+'/api/risk',json={}).status_code,403)
        with patch('apps.trading_web.portfolio_risk.read_inputs',side_effect=ValueError('No published history')):
            r=client.post(base+'/api/risk',json={'broker':'ibkr'},headers={'Origin':base,'X-Workspace-Token':server.token})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['status'],'unavailable')
