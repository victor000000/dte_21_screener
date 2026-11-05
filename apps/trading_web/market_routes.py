"""Allowlisted GET market-data endpoints; callers already validate the HTTP Host."""
from .tickets import TicketError
from .connection_status import status


def route(market, path, query):
    q={k:v[0] for k,v in query.items()}
    if path=='/api/market/connections':
        return status(market)
    if path=='/api/market/underlying':
        _, symbol = market.params(dict(q, source='alpaca'))
        return market.live.underlying(symbol)
    if path=='/api/market/expiries':
        return market.expiries(q)
    if path=='/api/market/chain':
        return market.chain(q)
    if path=='/api/market/quotes':
        return market.quotes(q.get('symbols','').split(','),q.get('source','alpaca'),q.get('feed','auto'),q.get('delayed')=='true')
    if path.startswith('/api/cn/'):
        return market.cn(path.removeprefix('/api/cn/'),q)
    raise TicketError('Unknown market endpoint.')
