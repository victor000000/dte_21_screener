"""Web operation routing and browser security; provider work is mocked."""
from unittest.mock import patch
from .support import *
from apps.trading_web import data_routes


class DataRouteTests(unittest.TestCase):
    def test_unknown_endpoint_and_action_fail_closed(self):
        with self.assertRaises(ValueError):
            data_routes.get('/api/data/delete', {})
        with self.assertRaises(ValueError):
            data_routes.get('/api/data/plan', {'action':['shell']})

    def test_http_controls_require_local_origin_and_token(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder)/'orders.sqlite',{'alpaca':FakeBroker()})
            server=create_server(0,service)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
            base=f'http://127.0.0.1:{server.server_port}'
            client=requests.Session();client.trust_env=False
            with patch.object(data_routes,'post',return_value={'status':'queued'}) as start:
                self.assertEqual(client.post(base+'/api/data/start',json={}).status_code,403)
                self.assertEqual(client.post(base+'/api/data/start',json={},headers={
                    'Origin':'https://evil.example','X-Workspace-Token':server.token}).status_code,403)
                start.assert_not_called()
                response=client.post(base+'/api/data/start',json={},headers={
                    'Origin':base,'X-Workspace-Token':server.token})
                self.assertEqual(response.status_code,200)
                start.assert_called_once_with({})
            with patch.object(data_routes,'status',return_value={'sources':[]}) as status:
                self.assertEqual(client.get(base+'/api/data/status').json(),{'sources':[]})
                status.assert_called_once()
            self.assertEqual(client.get(base+'/data-ui.js').status_code,200)
