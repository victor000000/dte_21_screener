"""Conservative whole-book selection; preserve competing observations and clock gaps."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from data_providers.providers.option_quote import contract, quote


def clock_session(stamp):
    try:
        local = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if local.tzinfo is None:
            return 'unknown'
        local = local.astimezone(ZoneInfo('America/New_York'))
        minute = local.hour*60+local.minute
        return 'overnight' if minute < 240 or minute >= 1200 else 'pre-market' if minute < 570 else 'regular window' if minute < 960 else 'post-market'
    except (TypeError, ValueError, AttributeError):
        return 'unknown'


def select(symbols, results):
    rows = []
    statuses = [dict(source=name, quote_count=len(result.get('data', {}).get('rows', [])), note=result.get('data', {}).get('warning'), **{k:v for k,v in result.items() if k!='data'}) for name,result in results.items()]
    for symbol in symbols:
        candidates = []
        for name, result in results.items():
            for row in result.get('data', {}).get('rows', []):
                if row['symbol'] == symbol:
                    old = row['quote']
                    q = quote(symbol, old.get('bid'), old.get('ask'), old.get('bid_size'), old.get('ask_size'),
                              source=old['source'], feed=old['feed'], quote_time=old.get('quote_time'),
                              received_at=old.get('received_at'))
                    q.update(session=clock_session(q['quote_time']), timestamp_basis=old.get('timestamp_basis'),
                             snapshot_update_time=old.get('snapshot_update_time'), tick_received_at=old.get('tick_received_at'))
                    candidates.append(q)
        def rank(q):
            age = q['age_seconds']
            if q['state'] in ('future_timestamp', 'crossed'):
                return 5, 0
            tier = 0 if q['executable_reference'] else 1 if q['midpoint'] is not None and q['feed']=='live' and age is None else 2 if q['midpoint'] is not None and age is None else 3 if q['midpoint'] is not None else 4
            return tier, age if age is not None else float('inf')
        candidates.sort(key=rank)
        chosen = dict(candidates[0]) if candidates else quote(symbol, source='Unavailable', feed='missing')
        fresh = [q for q in candidates if q['executable_reference']]
        disputed = any(abs(a['midpoint']-b['midpoint']) > max(.05, 3*max(a['ask']-a['bid'], b['ask']-b['bid']))
                       for a in fresh for b in fresh if abs(a['age_seconds']-b['age_seconds']) <= 5)
        if disputed:
            chosen.update(state='source_disagreement', executable_reference=False)
        rows.append(dict(**contract(symbol), quote=chosen, alternatives=candidates, disputed=disputed))
    return dict(rows=rows, source='Multi-source', feed='per-contract', sources=statuses,
                received_at=datetime.now(timezone.utc).isoformat(),
                warning='Whole-source books only; session labels describe quote clock windows, not venue eligibility. Missing-time, indicative and stale prices require manual checking.')
