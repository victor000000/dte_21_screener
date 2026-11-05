"""Rolling 24h observed trade return; no future/zero-volume/incomplete reference bars."""
from datetime import datetime, timedelta, timezone
import math


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def compare(observation, now=None):
    row = dict(observation, return_24h_pct=None, reference=None, reference_gap_seconds=None)
    now = now or datetime.now(timezone.utc)
    try:
        event = stamp(row['event_time'])
    except (ValueError, TypeError, KeyError, AttributeError):
        row.setdefault('reference_status', '24h comparison unavailable: current event time is unknown')
        return dict(row, freshness='event time unknown')
    age = (now-event).total_seconds()
    row.update(age_seconds=age, freshness='future clock' if age < -2 else 'fresh observation' if age <= 30 else 'stale observation')
    target = event-timedelta(hours=24)
    row['target_24h_utc'] = target.isoformat()
    valid = []
    for bar in row.get('bars', []):
        try:
            end = stamp(bar['start'])+timedelta(minutes=1)
            if end <= target and positive(bar.get('volume')) and positive(bar.get('close')):
                valid.append((end, bar))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    if valid and positive(row.get('price')) and age >= -2 and row.get('adjustment') == 'raw':
        end, reference = max(valid, key=lambda item:item[0])
        gap = (target-end).total_seconds()
        row.update(reference=reference, reference_gap_seconds=gap)
        if gap <= 900:
            row['return_24h_pct'] = (row['price']/reference['close']-1)*100
        else:
            row['reference_status'] = 'Reference too old: weekend, holiday or coverage gap'
    if row['return_24h_pct'] is None:
        row.setdefault('reference_status', 'No completed positive-volume bar within 15 minutes before the 24h target')
    row.pop('bars', None)
    return row
