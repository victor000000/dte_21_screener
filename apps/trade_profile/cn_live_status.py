"""Re-age saved CN evidence without relabelling request time as quote time."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def age(value, now):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        seconds = (now-stamp).total_seconds()
        return seconds if seconds >= -5 else None
    except (TypeError, ValueError):
        return None


def status(report, now=None):
    now = now or datetime.now(timezone.utc)
    result = deepcopy(report)
    counts = dict(recent=0, stale=0, missing=0, model=0, insufficient_depth=0)
    for leg in result.get('legs', []):
        quote = leg.get('quote')
        if quote:
            seconds = age(quote.get('quote_time'), now)
            quote['age_seconds'] = seconds
            recent = seconds is not None and seconds <= 30
            quote['status'] = 'Recent vendor timestamp; feed delay unknown' if recent else 'Dated / stale'
            counts['recent' if recent else 'stale'] += 1
            counts['insufficient_depth'] += not quote.get('depth_covers_qty', False)
        else:
            counts['missing'] += 1
        future = leg.get('future_quote')
        if future:
            future['age_seconds'] = age(future.get('quote_time'), now)
        counts['model'] += leg.get('model') is not None
        leg['holdings_age_seconds'] = age(leg.get('as_of'), now)
        try:
            leg['dte'] = (datetime.strptime(leg['expiry'], '%Y%m%d').date()-now.astimezone(ZoneInfo('Asia/Shanghai')).date()).days
        except (KeyError, TypeError, ValueError):
            leg['dte'] = None
    result['holdings_as_of'] = sorted({str(r['as_of']) for r in result.get('legs',[]) if r.get('as_of')})
    result['holdings_warning'] = ('Positions are exported snapshots, not a live account. Confirm no later trades before relying on this profile.'
        if result.get('legs') else 'No published positions are available.')
    result['freshness'] = dict(**counts, checked_at=now.isoformat(), threshold_seconds=30,
        verified_live=0, label='Recent vendor data; live entitlement unverified' if counts['recent'] else 'No recent option books',
        receipt_age_seconds=age(result.get('generated_utc'), now))
    result['refresh_interval_seconds'] = 10
    result['morning_note'] = ('08:00–09:00 Shanghai preparation: quotes can remain at the prior session. '
        'Polling continues throughout the day; venue sessions and holidays determine when new prices exist. '
        'Holdings are published exports, not a live broker account; no live margin/buying power is available.')
    return result
