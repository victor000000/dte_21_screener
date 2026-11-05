"""Response policy applies to maintenance as well as broker operations."""
from .support import *
from apps.trading_web.http_base import LocalHandler


class ResponsePolicyTests(unittest.TestCase):
    def test_sensitive_responses_cannot_be_cached_or_framed(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Path(directory)/'orders.sqlite',{'alpaca':FakeBroker()})
            server=create_server(0,service)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            client=requests.Session();client.trust_env=False
            response=client.get(f'http://127.0.0.1:{server.server_port}/api/session')
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
