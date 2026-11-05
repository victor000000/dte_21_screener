"""Conditional historical portfolio ES; signed cash P&L, aligned scenario dates."""
from datetime import date, timedelta
import math
import numpy as np
import QuantLib as ql
from data_providers.compute.bs import bs_price

HORIZONS = (1, 5, 10, 15, 20, 21)
LABELS = ('1 day', '1 week', '2 weeks', '3 weeks', '4 weeks', '21 days · primary')


def tail_risk(pnl, equity):
    """Exact empirical 5% tail mass, including a fractional boundary observation."""
    values = np.asarray(pnl, dtype=float)
    if values.ndim != 1 or len(values) < 20 or not np.isfinite(values).all():
        raise ValueError('At least twenty finite scenarios are required.')
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Positive net liquidation value is required.')
    losses = np.sort(-values)[::-1]
    mass = len(losses) * .05
    whole = int(math.floor(mass))
    fraction = mass - whole
    es = (float(losses[:whole].sum()) + (fraction * losses[whole] if fraction else 0)) / mass
    var = float(losses[math.ceil(mass) - 1])
    pct = es / equity * 100
    return dict(cvar=es, var=var, pct=pct, worst=float(losses[0]), scenarios=len(losses),
                tail_mass=mass, band='over limit' if pct >= 10 else 'warning' if pct >= 5 else 'below warning',
                headroom_5=equity * .05 - es, headroom_10=equity * .10 - es)


def horizon_date(today, sessions):
    calendar = ql.UnitedStates(ql.UnitedStates.NYSE)
    d = calendar.advance(ql.Date(today.day, today.month, today.year), sessions, ql.Days)
    return date(d.year(), d.month(), d.dayOfMonth())


def leg_pnl(leg, ratios, end, iv_scale=1):
    spot = leg['spot'] * ratios
    if leg['kind'] == 'stock':
        value = spot
    else:
        if leg['expiry'] <= end:
            # Physical settlement creates new stock exposure; do not substitute terminal payoff.
            raise ValueError(f"{leg['symbol']}: expiry/assignment falls within this horizon")
        years = (leg['expiry'] - end).days / 365
        value = np.array([bs_price(float(s), leg['strike'], years, 0., leg['iv'] * iv_scale,
                                  leg['right'] == 'C') for s in spot])
    return leg['qty'] * leg['multiplier'] * (value - leg['mark'])


def calculate(positions, draft, histories, equity, today, cashflow=0.):
    """Revalue each leg once; draft premium is cashflow, never added to equity."""
    all_legs = positions + draft
    roots = sorted({p['underlying'] for p in all_legs})
    if not roots:
        return []
    dates = sorted(set.intersection(*(set(histories[root]) for root in roots)))
    # A missing ticker session cannot silently turn a 5-session return into 6 sessions.
    calendar = ql.UnitedStates(ql.UnitedStates.NYSE)
    available = sorted(set.union(*(set(histories[root]) for root in roots)))
    if not available:
        raise ValueError('Daily history is empty')
    sessions = [available[0] + timedelta(days=i) for i in range((available[-1]-available[0]).days+1)]
    sessions = [d for d in sessions if calendar.isBusinessDay(ql.Date(d.day, d.month, d.year))]
    prices = {r: np.array([histories[r].get(d, float('nan')) for d in sessions]) for r in roots}
    results = []
    for h, label in zip(HORIZONS, LABELS):
        row = dict(days=h, label=label, end=horizon_date(today, h).isoformat())
        try:
            if len(dates) < 252:
                raise ValueError('Fewer than 252 common daily observations')
            # Check every session in each window, not just its endpoints.
            valid = np.ones(max(0, len(sessions)-h), dtype=bool)
            for p in prices.values():
                finite = np.isfinite(p) & (p > 0)
                valid &= np.convolve(finite.astype(int), np.ones(h+1, dtype=int), 'valid') == h+1
            if valid.sum() < 200:
                raise ValueError('Fewer than 200 complete historical windows')
            ratios = {r:(p[h:]/p[:-h])[valid] for r,p in prices.items()}
            current = np.zeros(int(valid.sum()))
            proposed = np.zeros_like(current)
            end = date.fromisoformat(row['end'])
            for leg in positions:
                current += leg_pnl(leg, ratios[leg['underlying']], end)
            for leg in draft:
                # Draft terminal value plus signed premium, instead of double-counting marks.
                proposed += leg_pnl(leg, ratios[leg['underlying']], end) + leg['qty']*leg['multiplier']*leg['mark']
            after = current + proposed + cashflow
            row.update(current=tail_risk(current,equity), after=tail_risk(after,equity) if draft else None,
                       incremental_cvar=tail_risk(after,equity)['cvar']-tail_risk(current,equity)['cvar'] if draft else None,
                       status='conditional estimate')
        except ValueError as exc:
            row.update(status='unavailable', reason=str(exc), current=None, after=None)
        results.append(row)
    return results
