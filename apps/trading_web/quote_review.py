"""Order-sized quote comparison. All net prices use positive debit / negative credit."""
from datetime import datetime, timezone


def review_quotes(market, ticket, source, feed='auto', delayed=False):
    try:
        data=market.quotes([l['symbol'] for l in ticket['legs']],source,feed,delayed)
    except Exception as exc:
        data={'rows':[], 'warning':f'Quotes unavailable ({type(exc).__name__}).', 'source':source}
    quotes={r['symbol']:r['quote'] for r in data['rows']}
    natural=midpoint=0.0;complete=True;warnings=[]
    for leg in ticket['legs']:
        q=quotes.get(leg['symbol'],{})
        if q.get('midpoint') is None:
            complete=False
        else:
            sign=1 if leg['side']=='buy' else -1
            natural+=(q['ask'] if sign==1 else -q['bid'])*leg['ratio']
            midpoint+=q['midpoint']*sign*leg['ratio']
        age=None
        # Recompute age: a cached quote must not inherit its earlier freshness classification.
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(q['quote_time'].replace('Z','+00:00'))).total_seconds()
        except (KeyError,TypeError,ValueError,AttributeError):
            age=None
        if not q.get('executable_reference') or age is None or age>30 or age < -2:
            warnings.append(leg['symbol']+': '+q.get('state','missing')+'; quote freshness/quality is not confirmed')
        size=q.get('ask_size' if leg['side']=='buy' else 'bid_size')
        if size is None or size<leg['qty']:
            warnings.append(leg['symbol']+': displayed size is missing or below your order quantity')
    if data.get('warning'):
        warnings.append(data['warning'])
    return dict(rows=data['rows'],source=source,feed=feed,delayed=delayed,
                natural_debit=round(natural,4) if complete else None,
                midpoint_debit=round(midpoint,4) if complete else None,
                warnings=warnings,requires_ack=bool(warnings),received_at=datetime.now(timezone.utc).isoformat(),
                note='Leg quote sum, not a guaranteed complex-order fill; USD per combination before multiplier and fees.')
