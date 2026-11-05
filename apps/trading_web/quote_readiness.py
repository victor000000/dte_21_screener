"""Contract-level evidence counts; transport success is never a live-quote badge."""
from datetime import datetime, timezone


def summarize(rows):
    counts = dict(disputed=0, fresh_verified=0, live_clock_unknown=0, frozen=0, delayed=0, indicative=0, stale=0, missing=0)
    for row in rows:
        q = row['quote']
        if row.get('disputed'):
            key = 'disputed'
        elif q.get('midpoint') is None:
            key = 'missing'
        elif q.get('executable_reference') and not row.get('disputed'):
            key = 'fresh_verified'
        elif q.get('feed') == 'indicative':
            key = 'indicative'
        elif 'frozen' in q.get('feed', ''):
            key = 'frozen'
        elif 'delayed' in q.get('feed', ''):
            key = 'delayed'
        elif q.get('feed') == 'live' and q.get('quote_time') is None:
            key = 'live_clock_unknown'
        else:
            key = 'stale'
        counts[key] += 1
    return dict(**counts, contracts=len(rows), checked_at=datetime.now(timezone.utc).isoformat(),
                label='Timestamp-verified live quotes available' if counts['fresh_verified'] else 'No timestamp-verified live quotes in this response')
