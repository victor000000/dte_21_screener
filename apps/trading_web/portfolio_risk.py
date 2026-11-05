"""Account-scoped risk orchestration; unavailable inputs never imply zero risk."""
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from apps.trade_profile.portfolio_cvar import HORIZONS, LABELS, calculate
from apps.trade_profile.cvar_inputs import read_inputs, finite
from data_providers.providers.option_quote import contract
from data_providers.compute.bs import implied_vol
from .tickets import normalize, check_holdings, TicketError

from apps.trade_profile.cvar_inputs import LIMITATIONS


def report(service, raw=None):
    raw = raw or {}
    name = raw.get('broker', 'ibkr')
    if name != 'ibkr':
        raise TicketError('Portfolio CVaR currently supports the IBKR paper account only.')
    ticket = normalize(raw['ticket']) if raw.get('ticket') else None
    if ticket and ticket['broker'] != name:
        raise TicketError('Risk ticket and account must use the same broker.')
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    out = dict(broker=name, mode='paper', account=None, received_at=now.isoformat(), confidence=.95,
               primary_days=21, warning_pct=5, limit_pct=10, status='unavailable',
               limitations=LIMITATIONS, inputs=[], issues=[], horizons=[], draft=ticket,
               decision='Risk assessment unavailable; no risk clearance.', model_version='historical-constant-iv-v1')
    try:
        with service.lock:
            b = service.broker(name)
            account, positions, orders = b.account(), b.positions(), b.orders()
        out['account'] = account
        equity = finite(account.get('equity'), True)
        if account.get('currency') != 'USD':
            raise ValueError('USD account net liquidation value required; FX risk is not modeled')
        if ticket:
            check_holdings(ticket, positions, orders)
        out['working_orders'] = sum(bool(o.get('active')) for o in orders)
        current, draft = [], []
        for p in positions:
            if p.get('currency') != 'USD':
                raise ValueError(f"{p['symbol']}: unsupported or unverified contract currency")
            qty = finite(p['qty'])
            if qty == 0:
                continue
            if p['asset_class'] == 'STK':
                current.append(dict(symbol=p['symbol'], underlying=p.get('underlying') or p['symbol'], kind='stock', qty=qty, multiplier=1))
            elif p['asset_class'] == 'us_option':
                spec = contract(p['symbol'])
                multiplier = finite(p.get('multiplier'),True)
                if multiplier != 100:
                    raise ValueError(f"{p['symbol']}: adjusted option multiplier is unsupported")
                current.append(dict(**spec,kind='option',qty=qty,multiplier=multiplier))
            else:
                raise ValueError(f"{p['symbol']}: {p['asset_class']} is not modeled; whole-account CVaR unavailable")
        if ticket:
            draft = [dict(**contract(l['symbol']), kind='option', qty=l['qty']*(1 if l['side']=='buy' else -1), multiplier=100) for l in ticket['legs']]
        all_legs = current + draft
        if not all_legs:
            raise ValueError('No security holdings. Currency cash balances are not yet verified; zero whole-account risk is not assumed.')
        if len(all_legs) > 60:
            raise ValueError('More than sixty legs; bounded interactive analysis unavailable')
        data = read_inputs(sorted({p['underlying'] for p in all_legs}),today)
        out['inputs'] = [dict(symbol=r,asof=v['asof'].isoformat(),source=v['source'],release=v['release'],observations=len(v['history'])) for r,v in data.items()]
        stale = [r for r,v in data.items() if (today-v['asof']).days>4 or v['asof']>today]
        if stale:
            raise ValueError('Stale daily price history: '+', '.join(stale)+'. Refresh through Data & maintenance before relying on CVaR.')
        symbols = sorted({p['symbol'] for p in all_legs if p['kind']=='option'})
        quotes = {}
        for i in range(0,len(symbols),20):
            if service.market is None:
                raise ValueError('Option market-data service unavailable')
            result = service.market.quotes(symbols[i:i+20], source='ibkr', delayed=False)
            quotes.update({r['symbol']:r for r in result['rows']})
        for p in all_legs:
            p['spot'] = data[p['underlying']]['spot']
            if p['kind']=='stock':
                p['mark'] = p['spot']
                continue
            q = quotes.get(p['symbol'],{}).get('quote',{})
            p['mark'] = finite(q.get('midpoint'),True)
            p['expiry'] = date.fromisoformat(p['expiry'])
            years = (p['expiry']-today).days/365
            p['iv'] = finite(implied_vol(p['mark'],p['spot'],p['strike'],years,0.,p['right']=='C'),True)
            if not q.get('executable_reference'):
                out['issues'].append(p['symbol']+': quote freshness/feed not verified; diagnostic estimate only')
        cashflow = float(ticket['cash'])*(1 if ticket['effect']=='credit' else -1) if ticket else 0.
        out['horizons'] = calculate(current,draft,{r:v['history'] for r,v in data.items()},equity,today,cashflow)
        out['status'] = 'conditional estimate' if any(r['current'] for r in out['horizons']) else 'unavailable'
        out['decision'] = 'Diagnostic model only; not a trade approval. Check all horizon limits and broker margin separately.'
        out['issues'].append('Underlying reference is the published daily close; option marks and account equity are later observations.')
        out['positions_count'] = len(current)
    except (ValueError, TypeError, KeyError) as exc:
        out['issues'].append(str(exc))
    except Exception:
        out['issues'].append('Broker or published risk inputs unavailable. No automatic acquisition or retry was performed.')
    if not out['horizons']:
        out['horizons'] = [dict(days=h,label=l,current=None,after=None,status='unavailable') for h,l in zip(HORIZONS,LABELS)]
    return out
