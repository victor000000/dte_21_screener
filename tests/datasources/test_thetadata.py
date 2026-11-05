"""Persistent terminal settings and stock symbology must survive a new client process."""
import os
import unittest
from unittest.mock import patch
from datasources import thetadata as app
from data.symbols import SymbolError


class ThetaConfigTests(unittest.TestCase):
    def test_endpoint_precedence(self):
        with patch.object(app,'_settings',return_value={'base_url':'http://configured/v3'}),patch.dict(os.environ,{},clear=True):
            self.assertEqual(app.ThetaDataClient('test').base_url,'http://configured/v3')
            with patch.dict(os.environ,{'THETADATA_BASE_URL':'http://env/v3/'}):
                self.assertEqual(app.ThetaDataClient('test').base_url,'http://env/v3')
                self.assertEqual(app.ThetaDataClient('test',base_url='http://explicit/v3/').base_url,'http://explicit/v3')

    def test_class_share_request_uses_provider_symbol_but_returns_requested_key(self):
        client=app.ThetaDataClient('test',base_url='http://localhost/v3')
        rows=[{'created':'2026-10-16T17:15:00','symbol':'BRK.B','close':'500','volume':'10'}]
        with patch('data.symbols.canonical_for',return_value='BRK B'),patch('data.symbols.for_source',return_value='BRK.B'),patch.object(client,'_request_csv',return_value=rows) as request:
            result=client.get_stock_eod('BRK-B','20261005','20261016')
        self.assertEqual(request.call_args.args[1]['symbol'],'BRK.B')
        self.assertEqual(result[0]['symbol'],'BRK-B')
        self.assertEqual(result[0]['date'],'2026-10-16')
        self.assertEqual(result[0]['close'],500.)

    def test_unmapped_explicit_symbol_is_retained(self):
        client=app.ThetaDataClient('test',base_url='http://localhost/v3')
        with patch('data.symbols.canonical_for',return_value=None),patch('data.symbols.for_source',side_effect=SymbolError()),patch.object(client,'_request_csv',return_value=[]) as request:
            self.assertEqual(client.get_stock_eod('DIRECT','20261005','20261016'),[])
        self.assertEqual(request.call_args.args[1]['symbol'],'DIRECT')


    def test_csv_request_keeps_terminal_key_out_of_url_parameters(self):
        from unittest.mock import Mock
        client=app.ThetaDataClient('private-test-key',base_url='http://localhost/v3')
        response=Mock(status_code=200,text='created,close\n2026-10-16T17:15:00,500\n')
        params={'symbol':'AAPL'}
        with patch.object(client,'_rate_limit'),patch.object(client.session,'get',return_value=response) as request:
            rows=client._request_csv('stock/history/eod',params)
        self.assertEqual(params,{'symbol':'AAPL'})
        self.assertNotIn('token',request.call_args.kwargs['params'])
        self.assertNotIn('private-test-key',str(request.call_args))
        self.assertEqual(rows[0]['close'],'500')
