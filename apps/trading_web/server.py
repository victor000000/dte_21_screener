"""Loopback-only web server. Run: uv run --locked python -m apps.trading_web.server."""
import argparse, json, secrets
from http.server import ThreadingHTTPServer
from .http_base import LocalHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from . import VERSION
from .market_routes import route
from . import data_routes
from .service import Service
from .tickets import TicketError
STATIC = Path(__file__).parent / 'static'
ASSETS = {'/risk-ui.js': ('risk-ui.js', 'text/javascript'), '/quote-clock.js': ('quote-clock.js', 'text/javascript'), '/table-ui.js': ('table-ui.js', 'text/javascript'), '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css'), '/market-ui.js': ('market-ui.js','text/javascript'),
          '/cn-ui.js': ('cn-ui.js','text/javascript'), '/data-ui.js': ('data-ui.js','text/javascript'),
          '/attribution-ui.js': ('attribution-ui.js','text/javascript'),
          '/cn-risk-ui.js': ('cn-risk-ui.js','text/javascript'),
          '/live-ui.js': ('live-ui.js','text/javascript'), '/navigation.js': ('navigation.js','text/javascript'), '/screen-ui.js': ('screen-ui.js','text/javascript')}
class Handler(LocalHandler):
    def do_GET(self):
        if not self.trusted_host():
            return self.send(403, {'error': 'Invalid host'})
        url = urlsplit(self.path)
        if url.path in ASSETS:
            file, mime = ASSETS[url.path]
            return self.send(200, (STATIC / file).read_bytes().replace(b'__WORKSPACE_VERSION__', VERSION.encode()), mime)
        try:
            if url.path == '/api/screening':
                from apps.screener.web_report import read_report
                return self.send(200, read_report(parse_qs(url.query)))
            if url.path == '/api/attribution':
                from apps.trade_profile.web_attribution import report
                return self.send(200, report(parse_qs(url.query).get('day', [None])[0]))
            if url.path.startswith('/api/data/'):
                return self.send(200, data_routes.get(url.path, parse_qs(url.query)))
            if url.path.startswith(('/api/market/','/api/cn/')):
                return self.send(200, route(self.server.service.market,url.path,parse_qs(url.query)))
            if url.path == '/api/session':
                return self.send(200, dict(version=VERSION, token=self.server.token, mode='paper'))
            name = parse_qs(url.query).get('broker', ['alpaca'])[0]
            if url.path == '/api/snapshot':
                return self.send(200, self.server.service.snapshot(name))
            if url.path == '/api/receipts':
                return self.send(200, self.server.service.receipts(name))
            self.send(404, {'error': 'Not found'})
        except (TicketError, ValueError) as exc:
            self.send(400, {'error': str(exc)})
        except Exception:
            self.send(502, {'error': 'Broker unavailable or request failed. No automatic retries were made.'})
    def do_POST(self):
        if (not self.trusted_host() or self.headers.get('Origin') not in self.server.origins
                or not secrets.compare_digest(self.headers.get('X-Workspace-Token', ''), self.server.token)):
            return self.send(403, {'error': 'Use this webpage on localhost to operate the paper account.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 20000 or self.headers.get('Content-Type') != 'application/json':
                return self.send(400, {'error': 'Expected bounded JSON request.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise TicketError('Expected an object.')
            if self.path == '/api/risk':
                from .portfolio_risk import report
                result = report(self.server.service, body)
            elif self.path == '/api/data/start':
                result = data_routes.post(body)
            elif self.path == '/api/review':
                result = self.server.service.review(body)
            elif self.path == '/api/submit':
                result = self.server.service.submit(body.get('token'), body.get('account'), body.get('quote_ack') is True)
            elif self.path == '/api/cancel':
                result = self.server.service.cancel(body.get('broker'), body.get('id'))
            else:
                return self.send(404, {'error': 'Not found'})
            self.send(200, result)
        except (TicketError, ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})
        except Exception:
            self.send(502, {'error': 'Request failed. For submission failures, inspect Orders and submission receipts before retrying.'})
def create_server(port=8765, service=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    actual = server.server_address[1]
    server.hosts = {f'127.0.0.1:{actual}', f'localhost:{actual}'}
    server.origins = {'http://' + host for host in server.hosts}
    server.token = secrets.token_urlsafe(32)
    server.service = service or Service()
    return server
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = create_server(args.port)
    print(f'Options workspace {VERSION}: http://localhost:{server.server_address[1]} (real paper trading only)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
if __name__ == '__main__':
    main()
