"""Exact CN contract identities and archived broker multiplier evidence."""
import math
import re
import json
from datetime import datetime
from data_providers.providers import cn_workspace

def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def native_ids(p):
    match = re.fullmatch(r'([A-Za-z]+)(\d{3,4})-?([CP])-?(\d+)', p['symbol'])
    if not match:
        raise ValueError('Unsupported held contract identity')
    root, month, right, strike = match.groups()
    expiry = datetime.strptime(p['expiry'], '%Y%m%d')
    # Resolve CZCE's single year digit against the explicit broker expiry year.
    if len(month) == 3:
        years = [y for y in range(expiry.year, expiry.year + 2) if y % 10 == int(month[0])]
        if len(years) != 1:
            raise ValueError('Ambiguous CZCE delivery year')
        month = str(years[0])[2:] + month[1:]
    return f'P_OP_{root.lower()}{month}{right}{strike}', f'nf_{root.upper()}{month}'


def multiplier_evidence(snapshot):
    """Infer units from archived broker evidence, including older nonzero LC marks."""
    with cn_workspace.connection('trades', snapshot['release']) as c:
        rows = cn_workspace.records(c, '''SELECT r.payload,e.modified_utc,e.sha256
            FROM broker_export_rows r JOIN broker_exports e ON r.sha256=e.sha256 AND r.kind=e.kind
            WHERE r.kind='cn_tracker_positions' ORDER BY e.modified_utc DESC''')
    found = {}
    for row in rows:
        raw = json.loads(row['payload'])
        symbol = raw.get('持仓合约', '')
        if symbol in found:
            continue
        qty, mark, value = (number(raw.get(k)) for k in ('总仓', '最新价', '持仓市值'))
        side = raw.get('买卖', '').strip()
        if not qty or not mark or value is None or side not in ('买', '卖'):
            continue
        units = value / (qty * mark * (1 if side == '买' else -1))
        rounded = round(units)
        if rounded > 0 and math.isclose(units, rounded, rel_tol=.002):
            found[symbol] = dict(multiplier=rounded, multiplier_basis='Inferred from archived broker position value / signed quantity / mark; not exchange verified',
                                 multiplier_evidence_time=str(row['modified_utc']), multiplier_receipt=row['sha256'])
    return found


