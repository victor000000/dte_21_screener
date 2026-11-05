"""Pure CN tracker calculations; acquisition and canonical stores stay provider-owned.

Input Greeks are signed POSITION values (quantity already applied). Gamma basis
must be explicit: raw `position_gamma` is not the older tracker's `$Gamma`.
Output preserves per-leg provenance via the input fields and nets exact futures
before optionally showing root-level parallel-move scenarios.
"""
from collections import defaultdict
from math import isfinite


def _finite(value, name):
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def calculate(positions, *, cny_per_usd, fx_as_of):
    """Return leg, exact-future and ticker risk without fetching or writing data.

    Required input: symbol, venue, root, future, qty, multiplier,
    position_delta_futures_equivalent, underlying_price. Optional: entry,
    option_bid/option_ask and position_gamma with gamma_basis equal to
    position_gamma (qty*gamma), cash_gamma_over_spot (qty*gamma*spot*mult),
    or unknown. Unknown gamma remains native only.
    """
    fx = _finite(cny_per_usd, 'cny_per_usd')
    if fx <= 0 or not fx_as_of:
        raise ValueError('Positive FX and its reference date are required')
    legs = []
    futures = defaultdict(list)
    roots = defaultdict(list)
    for original in positions:
        row = dict(original)
        for key in ('symbol', 'venue', 'root', 'future'):
            if not row.get(key):
                raise ValueError(f'{key} is required')
        qty = _finite(row['qty'], 'qty')
        mult = _finite(row['multiplier'], 'multiplier')
        spot = _finite(row['underlying_price'], 'underlying_price')
        delta = _finite(row['position_delta_futures_equivalent'], 'position delta')
        if mult <= 0 or spot <= 0 or qty == 0:
            raise ValueError('Positive multiplier/spot and nonzero quantity required')
        # Do not multiply by qty again: the broker already sized this delta.
        row['dollar_delta_usd'] = delta * mult * spot / fx
        row['gamma_units_cny'] = None
        row['gamma_pnl_1pct_usd'] = None
        if row.get('position_gamma') is not None:
            gamma = _finite(row['position_gamma'], 'position gamma')
            basis = row.get('gamma_basis', 'unknown')
            if basis == 'position_gamma':
                units = gamma * mult
            elif basis == 'cash_gamma_over_spot':
                units = gamma / spot
            elif basis == 'unknown':
                units = None
            else:
                raise ValueError(f'Unrecognized gamma basis: {basis}')
            row['gamma_units_cny'] = units
            if units is not None:
                row['gamma_pnl_1pct_usd'] = .5 * units * (.01 * spot) ** 2 / fx
        row['premium_profit_pct'] = None
        mark = row.get('option_ask' if qty < 0 else 'option_bid')
        if row.get('entry') is not None and mark is not None:
            entry = _finite(row['entry'], 'entry')
            mark = _finite(mark, 'exit quote')
            if entry > 0 and mark >= 0:
                row['premium_profit_pct'] = 100 * (mark - entry) / entry * (1 if qty > 0 else -1)
        row['delta_pnl_up_1pct_usd'] = .01 * row['dollar_delta_usd']
        row['delta_pnl_down_1pct_usd'] = -.01 * row['dollar_delta_usd']
        legs.append(row)
        futures[(row['venue'], row['root'], row['future'])].append(row)
        roots[(row['venue'], row['root'])].append(row)

    def aggregate(key, rows, ticker=False):
        net = sum(r['dollar_delta_usd'] for r in rows)
        gammas = [r['gamma_pnl_1pct_usd'] for r in rows]
        result = dict(venue=key[0], root=key[1], net_dollar_delta_usd=net,
                      gross_dollar_delta_usd=sum(abs(r['dollar_delta_usd']) for r in rows),
                      delta_loss_adverse_1pct_usd=abs(net) * .01,
                      gamma_pnl_1pct_usd=sum(gammas) if all(g is not None for g in gammas) else None)
        if not ticker:
            result['future'] = key[2]
            result['position_delta_futures_equivalent'] = sum(r['position_delta_futures_equivalent'] for r in rows)
        return result

    tickers = [aggregate(k, v, True) for k, v in roots.items()]
    tickers.sort(key=lambda r: abs(r['net_dollar_delta_usd']), reverse=True)
    return dict(legs=legs, futures=[aggregate(k, v) for k, v in futures.items()],
                ticker_ranking=tickers, cny_per_usd=fx, fx_as_of=fx_as_of,
                limitations=['Cross-month ticker net assumes parallel percentage moves; basis risk remains.',
                             'Delta and gamma are local approximations, not full repricing or margin forecasts.',
                             'Unknown gamma units stay native; missing gamma is not zero.',
                             'Input Greek, quote and FX dates may differ; source timestamps remain in each leg.'])
