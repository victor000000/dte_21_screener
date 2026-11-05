"""Pin provider delivery and isolate futures IV by source, series and full methodology."""
import hashlib
import json
from data import db
from data_providers import MarketData
from data_providers.lake import configured_connection
from apps.screener.us_inventory import table_exists


def open_snapshot(home):
    client = MarketData(home=home)
    if client.release is None:
        return db.connect(log=None, history='ro', reference='ro', universe=True), None
    con = configured_connection()
    try:
        for store, alias in [('history', 'mh'), ('reference', 'ref'), ('universe', 'yh')]:
            client.release.attach(con, store, alias)
    except Exception:
        con.close()
        raise
    return con, client.release.id


def futures_iv(con):
    by_label, methods = {}, {}
    if not table_exists(con, 'mh.us_futures_iv'):
        return by_label, methods
    columns = ['source', 'venue', 'root', 'series_id', 'tenor_days', 'moneyness_method',
               'roll_method', 'model', 'method_version']
    for values in con.execute('SELECT ' + ','.join(columns) + ',day,atm_iv FROM mh.us_futures_iv').fetchall():
        metadata = dict(zip(columns, values))
        source, venue, root, series = values[:4]
        if not source or not series or not series.startswith(f'{venue}:{root}:'):
            raise ValueError('Invalid typed futures IV identity')
        signature = hashlib.sha256(json.dumps(values[:-2], default=str).encode()).hexdigest()
        key = f'{source}@{series}#{signature}'
        methods[key] = {'iv_source': source, 'iv_series_id': series,
                        **{f'iv_{name}': metadata[name] for name in columns[4:]},
                        'iv_delivery': 'us_futures_iv'}
        by_label.setdefault(f'{root}:{venue}', []).append((key, values[-2], values[-1]))
    return by_label, methods
