"""Read saved, dated attribution evidence; never acquire data or manufacture daily P&L."""
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT/'reports/loss_attribution_2026-10-25'
TEXT = {'day','underlying','name','broker','contract','expiry','currency','price_source','flags'}
COMPONENTS = ['delta_usd','gamma_usd','vega_usd','theta_usd','flow_usd','residual_usd','unallocated_usd']


def rows(path):
    with path.open(newline='') as handle:
        result = []
        for raw in csv.DictReader(handle):
            row = {}
            for key, value in raw.items():
                if key in TEXT:
                    row[key] = value
                else:
                    try:
                        number = float(value)
                        row[key] = number if math.isfinite(number) else None
                    except (ValueError, TypeError):
                        row[key] = None
            result.append(row)
        return result


def grouped(legs):
    groups = defaultdict(list)
    for row in legs:
        groups[(row['broker'], row['underlying'])].append(row)
    output = []
    for (broker, underlying), items in sorted(groups.items()):
        def total(key):
            values = [r.get(key) for r in items]
            return sum(values) if all(v is not None for v in values) else None
        item = dict(broker=broker, underlying=underlying, legs=items,
                    delta_usd=total('delta_linear_usd'), vega_usd=total('vega_usd'),
                    theta_usd=total('theta_usd'), flow_usd=total('flow_pnl_native_usd'),
                    residual_usd=total('residual_usd'))
        spot = total('spot_usd')
        item['gamma_usd'] = spot-item['delta_usd'] if spot is not None and item['delta_usd'] is not None else None
        carried = total('carried_pnl_native_usd')
        item['pnl_usd'] = carried+item['flow_usd'] if carried is not None and item['flow_usd'] is not None else None
        output.append(item)
    return output


def report(day=None, folder=DEFAULT):
    folder = Path(folder)
    required = ['daily_attribution.csv','ticker_attribution.csv','leg_attribution.csv','rv_iv.csv','validation.json']
    if not all((folder/name).is_file() for name in required):
        return dict(available=False, message='No attribution report is available. Missing data is not zero P&L.', days=[])
    daily = rows(folder/'daily_attribution.csv')
    days = sorted({r['day'] for r in daily})
    selected = day or (days[-1] if days else None)
    if selected not in days:
        return dict(available=False, message='No saved attribution evidence for this date.', days=days, selected=selected)
    summary = next(r for r in daily if r['day']==selected)
    components = [summary.get(k) for k in COMPONENTS]
    summary['reconciliation_gap'] = (summary['combined_usd']-sum(components)
        if summary.get('combined_usd') is not None and all(v is not None for v in components) else None)
    legs = [r for r in rows(folder/'leg_attribution.csv') if r['day']==selected]
    rv = [r for r in rows(folder/'rv_iv.csv') if r['day']==selected]
    for r in rv:
        r['iv_minus_rv_points'] = 100*(r['iv_prev']-r['rv10']) if r['iv_prev'] is not None and r['rv10'] is not None else None
    validation = json.loads((folder/'validation.json').read_text())
    return dict(available=True, selected=selected, days=days, daily=daily, summary=summary,
                groups=grouped(legs), volatility=rv,
                tickers=[r for r in rows(folder/'ticker_attribution.csv') if r['day']==selected],
                generated_at=validation.get('generated_utc'), assumptions=validation.get('assumptions'),
                source_report=str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else folder.name,
                report_hashes={n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in required},
                basis='Historical account analysis: estimated Schwab/CN mark-to-market P&L plus IBKR NAV changes. These are not the current paper accounts.',
                method='Revaluation order: time → underlying → IV. Gamma+ is full spot revaluation minus linear Delta, including higher-order effects; it is not a pure second-order Greek.')
