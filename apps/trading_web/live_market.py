"""Multi-source interactive dispatch. Acquisition remains in provider adapters."""
from data_providers.providers import us_option_data, interactive_options, interactive_underlying, interactive_massive, interactive_reference
from apps.trade_profile.rolling_underlying import compare
from .source_pool import SourcePool
from .quote_selection import select
from .quote_readiness import summarize


class LiveMarket:
    def __init__(self, brokers):
        self.brokers = brokers
        self.options = SourcePool()
        self.spots = SourcePool()
        self.last_options = None

    def quotes(self, symbols):
        calls = {'Alpaca': lambda: us_option_data.snapshots(symbols),
                 'IBKR': lambda: self.brokers['ibkr'].market('snapshots', symbols, 2),
                 'Futu': lambda: interactive_options.futu(symbols),
                 'ThetaData': lambda: interactive_options.theta(symbols),
                 'Massive': lambda: interactive_massive.snapshots(symbols)}
        results = self.options.collect(tuple(symbols), calls)
        result = select(symbols, results)
        result['sources'].extend([dict(source='Yahoo / Tiingo / Nasdaq', status='not an option-book fallback', detail='Underlying/reference adapters; not verified live option NBBO')])
        result['readiness'] = summarize(result['rows'])
        self.last_options = result
        return result

    def underlying(self, symbol):
        calls = {f'Alpaca {feed}': lambda f=feed: interactive_underlying.alpaca(symbol, f)
                 for feed in ('sip', 'iex', 'boats', 'overnight')}
        calls['Futu'] = lambda: interactive_underlying.futu(symbol)
        calls['IBKR'] = lambda: self.brokers['ibkr'].market('underlying', symbol)
        calls['ThetaData'] = lambda: interactive_underlying.theta(symbol)
        calls['Tiingo'] = lambda: interactive_reference.tiingo(symbol)
        calls['Yahoo'] = lambda: interactive_reference.yahoo(symbol)
        results = self.spots.collect(symbol, calls)
        rows = [dict(compare(r['data']), provider=name) for name, r in results.items() if r['status']=='responded']
        rows.sort(key=lambda r:(r.get('freshness')!='fresh observation', r.get('age_seconds', float('inf'))))
        return dict(symbol=symbol, observations=rows,
                    sources=[dict(source=n, **{k:v for k,v in r.items() if k!='data'}) for n,r in results.items()],
                    note='24×5 where entitled. Trade-to-prior-minute-close return, raw prices; not total return. Stale observations retain their own 24h window. Weekends/holidays and missing reference bars remain gaps.',
                    account_pnl_24h=None, account_pnl_note='Rolling account P&L unavailable: comparable equity history and cash-flow reconciliation are not connected.')
