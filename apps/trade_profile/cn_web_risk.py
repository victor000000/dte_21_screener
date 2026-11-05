"""CN broker-position Greek summaries; all scenarios labelled approximations in CNY."""
from collections import defaultdict


def summarize(rows):
    groups=defaultdict(list)
    legs=[]
    for p in rows:
        r=dict(p)
        qty,entry,mark=r.get('qty'),r.get('entry'),r.get('mark')
        r['profit_pct'] = ((mark-entry)/entry*100*(1 if qty>0 else -1)) if entry and qty and mark is not None and mark>0 else None
        d,m,s=r.get('position_delta'),r.get('multiplier'),r.get('underlying_price')
        r['delta_pnl_up_1pct_cny'] = d*m*s*.01 if all(v is not None for v in (d,m,s)) else None
        r['scenario_basis']='Estimated: signed broker position delta × multiplier × 1% futures close. Quantity is not applied again.'
        r['multiplier_verified'] = bool(r.get('multiplier_source')) and 'unverified' not in r['multiplier_source']
        legs.append(r);groups[(r['account'],r['venue'],r['root'],r['future'])].append(r)
    totals=[]
    for (account,venue,root,future), items in groups.items():
        complete=all(i['delta_pnl_up_1pct_cny'] is not None for i in items)
        delta_complete=all(i.get('position_delta') is not None for i in items)
        totals.append(dict(account=account,venue=venue,root=root,future=future,
            position_delta=sum(i['position_delta'] for i in items) if delta_complete else None,
            up_1pct_cny=sum(i['delta_pnl_up_1pct_cny'] for i in items) if complete else None,
            scenario_complete=complete,multiplier_verified=all(i['multiplier_verified'] for i in items)))
    legs.sort(key=lambda r:(r['account'],r['root'],r['profit_pct'] is None,r['profit_pct'] or 0))
    return dict(legs=legs,futures=totals,limitations=['Stored exports, prices and multipliers have different as-of dates.',
        'Unverified reference multipliers remain explicitly flagged; scenarios are estimates.',
        'Gamma/theta/vega remain native position values: their cash units are not established.',
        'No cross-month netting, FX conversion or broker margin forecast.'])
