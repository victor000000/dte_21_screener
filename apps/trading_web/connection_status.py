"""Public role-separated connection evidence; no credentials or connectivity claims by port alone."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def status(market):
    reader = market.brokers.get('ibkr')
    executor = getattr(market, 'execution', None)
    quotes = market.live.last_options or {}
    return dict(market_data=reader.status() if hasattr(reader, 'status') else {'connected':False},
                paper_execution=executor.connection_status() if executor else {'connected':False},
                quote_sources=quotes.get('sources', []), quote_readiness=quotes.get('readiness'),
                quote_symbols=[r['symbol'] for r in quotes.get('rows', [])], quote_received_at=quotes.get('received_at'),
                checked_at=datetime.now(timezone.utc).isoformat(),
                new_york_clock=datetime.now(ZoneInfo('America/New_York')).isoformat(),
                note='Market data and paper orders use separate connections. A connected gateway or recent receipt does not prove a fresh exchange quote.')
