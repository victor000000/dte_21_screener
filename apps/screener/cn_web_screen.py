"""Same-source CN IV rank over bounded published history; no liquidity gate invented."""
from collections import defaultdict


def screen(history, products):
    venues = defaultdict(set)
    for p in products:
        venues[p['product']].add(p['venue'])
    series = defaultdict(dict)
    for r in history:
        # One observation per source/day. Conflicting same-day observations are excluded.
        key = r['underlying'],r['source']
        existing = series[key].get(str(r['day']))
        series[key][str(r['day'])] = r['atm_iv'] if existing is None or existing == r['atm_iv'] else float('nan')
    out=[]
    for (root,source), values in series.items():
        days=sorted((d,v) for d,v in values.items() if v>0)[-252:]
        if not days:
            continue
        vals=[v for d,v in days];current=vals[-1]
        rank=100*(current-min(vals))/(max(vals)-min(vals)) if len(vals)>=60 and max(vals)>min(vals) else None
        venue=next(iter(venues[root])) if len(venues[root])==1 else None
        out.append(dict(symbol=f'CN:{venue}:{root}' if venue else f'CN:UNKNOWN:{root}',venue=venue,product=root,source=source,
                        as_of=days[-1][0],iv=current,observations=len(vals),ivr=rank,
                        qualifies=rank is not None and rank>50,partial=len(vals)<252,
                        limitation='Product-level IV series; not a specific contract. Futures liquidity gate unconfigured.'))
    return sorted(out,key=lambda r: (r['ivr'] is None,-(r['ivr'] or 0),r['symbol']))
