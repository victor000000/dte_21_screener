"""Market-data orchestration, bounded caches and strict public request validation."""
import re
import threading
import time
from datetime import date
from data_providers.providers import us_option_data, cn_workspace, cn_positions, cn_live_chain
from apps.screener.cn_web_screen import screen
from apps.trade_profile.cn_web_risk import summarize
from .tickets import TicketError
from .live_market import LiveMarket


class MarketService:
    def __init__(self, brokers, market_broker=None):
        self.execution=brokers.get('ibkr');self.brokers={**brokers, **({'ibkr':market_broker} if market_broker else {})};self.lock=threading.RLock();self.cache={};self.live=LiveMarket(self.brokers)

    def cached(self, key, ttl, fn):
        with self.lock:
            if key in self.cache and time.monotonic()-self.cache[key][0]<ttl:
                return self.cache[key][1]
            value=fn();self.cache[key]=(time.monotonic(),value)
            if len(self.cache)>100:
                self.cache.pop(next(iter(self.cache)))
            return value

    @staticmethod
    def params(q):
        source=q.get('source','alpaca');symbol=q.get('symbol','').strip().upper()
        if source not in ('alpaca','ibkr') or not re.fullmatch(r'[A-Z]{1,6}',symbol):
            raise TicketError('Choose IBKR/Alpaca and a US equity/ETF ticker.')
        return source,symbol

    def expiries(self,q):
        source,symbol=self.params(q)
        return self.cached(('expiries',source,symbol),300,lambda: us_option_data.expiries(symbol) if source=='alpaca'
                           else self.brokers['ibkr'].market('expiries',symbol))

    def chain(self,q):
        source,symbol=self.params(q)
        expiry=date.fromisoformat(q.get('expiry','')).isoformat();right=q.get('right','P')
        if right not in ('P','C'):
            raise TicketError('Choose calls or puts.')
        low=float(q['low']) if q.get('low') else None;high=float(q['high']) if q.get('high') else None
        if any(v is not None and not 0<v<100000 for v in (low,high)) or low is not None and high is not None and low>high:
            raise TicketError('Enter a valid positive strike range.')
        feed=q.get('feed','auto')
        if feed not in ('auto','opra','indicative'):
            raise TicketError('Invalid feed.')
        dtype=4 if q.get('delayed')=='true' else 2 if q.get('multi')=='true' else 1
        key=('chain',source,symbol,expiry,right,low,high,q.get('cursor'),feed,dtype)
        catalog_ttl=300 if q.get('multi')=='true' else 3
        try:
            result = self.cached(key,catalog_ttl,lambda: us_option_data.chain(symbol,expiry,right,low,high,q.get('cursor'),feed) if source=='alpaca'
                                else self.brokers['ibkr'].market('chain',symbol,expiry,right,low,high,dtype))
        except Exception:
            if q.get('multi')!='true' or q.get('cursor'):
                raise  # Pagination cursors cannot be transferred between catalogs.
            result = self.cached(('fallback',*key[1:]),catalog_ttl,lambda: us_option_data.chain(symbol,expiry,right,low,high,None,feed) if source=='ibkr'
                                 else self.brokers['ibkr'].market('chain',symbol,expiry,right,low,high,dtype))
            result = dict(result, warning='Selected catalog unavailable; alternate broker catalog first page used. Select that catalog for pagination.', next_page_token=None)
        if q.get('multi')=='true' and result['rows']:
            combined = self.live.quotes([r['symbol'] for r in result['rows'][:20]])
            quotes = {r['symbol']:r for r in combined['rows']}
            return dict(result, rows=[dict(r, **{k:v for k,v in quotes.get(r['symbol'], {}).items() if k not in r or k=='quote'}) for r in result['rows']], sources=combined['sources'], readiness=combined['readiness'], warning=(result.get('warning') or '')+' '+combined['warning'])
        return result

    def quotes(self,symbols,source='alpaca',feed='auto',delayed=False):
        if source not in ('auto','alpaca','ibkr') or feed not in ('auto','opra','indicative'):
            raise TicketError('Invalid quote source or feed.')
        if not 1<=len(symbols)<=20 or any(not re.fullmatch(r'[A-Z]{1,6}\d{6}[CP]\d{8}',s) for s in symbols):
            raise TicketError('Request one to twenty standard option contracts.')
        if source=='auto':
            return self.live.quotes(symbols)
        key=('quotes',source,tuple(symbols),feed,delayed)
        return self.cached(key,2,lambda:us_option_data.snapshots(symbols,feed) if source=='alpaca'
                           else self.brokers['ibkr'].market('snapshots',symbols,4 if delayed else 1))

    def cn(self,operation,q):
        if operation=='leg-risk':
            from apps.trade_profile.cn_leg_live import report
            if q.get('refresh')=='true':
                return report(update=True)  # owns single-flight and retry cooldown
            return report()
        if operation=='catalog':
            data=self.cached(('cn-catalog',),60,cn_workspace.catalog)
            return {k:v for k,v in data.items() if k!='iv_history'}
        if operation=='screen':
            data=self.cached(('cn-catalog',),60,cn_workspace.catalog)
            return dict(rows=screen(data['iv_history'],data['products']),release=data['release'])
        if operation=='positions':
            data=self.cached(('cn-positions',),30,cn_positions.positions)
            return dict(**data,risk=summarize(data['positions']))
        if operation=='chain':
            args=(q.get('venue',''),q.get('product',''),q.get('month',''),q.get('live')=='true')
            return self.cached(('cn-chain',*args),10,lambda:cn_live_chain.chain(*args))
        raise TicketError('Unknown CN operation.')
