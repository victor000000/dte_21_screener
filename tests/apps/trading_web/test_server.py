from .support import *

class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.broker = FakeBroker()
        self.service = Service(Path(self.directory.name) / 'receipts.sqlite', {'alpaca': self.broker})

    def test_http_local_origin_csrf_and_no_file_escape(self):
        server = create_server(0, self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_address[1]}'
        client = requests.Session()
        client.trust_env = False
        self.assertEqual(client.get(base + '/.local/trading-web/orders.sqlite').status_code, 404)
        self.assertEqual(client.get(base, headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(client.post(base + '/api/review', json=ticket()).status_code, 403)
        headers = {'Origin': base, 'X-Workspace-Token': server.token}
        result = client.post(base + '/api/review', json=ticket(), headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertIn('token', result.json())

    def test_page_and_session_share_one_version(self):
        from apps.trading_web import VERSION
        server=create_server(0,self.service)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        client=requests.Session();client.trust_env=False
        base=f'http://127.0.0.1:{server.server_address[1]}'
        body=client.get(base+'/').text
        self.assertNotIn('__WORKSPACE_VERSION__',body)
        self.assertIn('Options workspace · '+VERSION,body)
        self.assertIn('YOUR TRADING DESK · v'+VERSION,body)
        self.assertIn('Local · v'+VERSION,body)
        self.assertEqual(client.get(base+'/api/session').json()['version'],VERSION)
