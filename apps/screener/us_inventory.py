"""Observed US inventory, before strategy filters; identities separate futures from stocks."""
import json


def table_exists(con, table):
    schema, name = table.split('.')
    return bool(con.execute("SELECT count(*) FROM information_schema.tables "
                            "WHERE (table_schema=? OR table_catalog=?) AND table_name=?",
                            [schema, schema, name]).fetchone()[0])


def inventory(con, today):
    names = {r[0] for r in con.execute("SELECT symbol FROM yh.symbols").fetchall()}
    names |= {r[0] for r in con.execute("SELECT DISTINCT underlying FROM mh.iv_history").fetchall()}
    evidence, historical = {}, set()
    for table, day in [('ref.option_contracts', 'last_seen'), ('mh.option_bars', 'day'),
                       ('mh.option_contract_history', 'session_date')]:
        if not table_exists(con, table):
            continue
        historical |= {r[0] for r in con.execute(f"SELECT DISTINCT underlying FROM {table}").fetchall()}
        for name, observed in con.execute(f"SELECT underlying, max({day}) FROM {table} "
                                         "WHERE expiry>=? GROUP BY 1", [today]).fetchall():
            evidence[name] = max(filter(None, [observed, evidence.get(name)]), default=None)
    names |= historical
    out = []
    for name in sorted(filter(None, names)):
        if ':' in name and not name.endswith(':IDX'):
            continue
        index = name.endswith(':IDX')
        out.append(dict(instrument=name, asset_class='index' if index else 'equity_or_fund',
                        root=name.split(':')[0], venue='IDX' if index else 'US',
                        series_label=name, optionability=('unexpired_contract_observed' if name in evidence
                        else 'historical_options_only' if name in historical else 'optionability_unknown'),
                        option_asof=evidence.get(name), listing_scope='US_listed'))
    roots, observed, contracts, catalog = set(), {}, {}, {}
    if table_exists(con, 'mh.us_futures_products'):
        cols = {r[0] for r in con.execute('DESCRIBE mh.us_futures_products').fetchall()}
        detail = 'details' if 'details' in cols else 'NULL'
        order = ' ORDER BY day' if 'day' in cols else ''
        for root, venue, raw in con.execute(f'SELECT product_code,venue,{detail} FROM mh.us_futures_products{order}').fetchall():
            roots.add((root, venue))
            data = json.loads(raw or '{}')
            catalog[(root, venue)] = dict(product_name=data.get('name'),
                provider_asset_class=data.get('asset_class'), provider_sector=data.get('sector'),
                definition_types=','.join(sorted({v.get('type', 'unknown') for v in data.get('_definition_variants', [])})),
                catalog_scope=data.get('_provider_coverage', {}).get('venue_scope'))
    if table_exists(con, 'mh.us_futures_iv'):
        roots |= set(con.execute('SELECT DISTINCT root,venue FROM mh.us_futures_iv').fetchall())
    for table in ['us_futures_contracts', 'us_futures_option_daily', 'us_futures_option_settlements']:
        if not table_exists(con, f'mh.{table}'):
            continue
        roots |= set(con.execute(f"SELECT DISTINCT root,venue FROM mh.{table}").fetchall())
        if table == 'us_futures_contracts':
            query = "SELECT root,venue,max(CAST(captured_utc AS DATE)) FROM mh.us_futures_contracts WHERE sec_type='FOP' AND expiry>=? GROUP BY 1,2"
        else:
            query = f"SELECT root,venue,max(day) FROM mh.{table} WHERE expiry>=? GROUP BY 1,2"
        for root, venue, day in con.execute(query, [today]).fetchall():
            contracts[(root, venue)] = day
    if table_exists(con, 'mh.us_futures_option_chains'):
        for root, venue, day, expirations, strikes in con.execute(
                "SELECT root,venue,day,expirations,strikes FROM mh.us_futures_option_chains").fetchall():
            roots.add((root, venue))
            dates = [str(e).replace('-', '')[:8] for e in json.loads(expirations or '[]')]
            if json.loads(strikes or '[]') and any(e >= today.strftime('%Y%m%d') for e in dates):
                observed[(root, venue)] = max(day, observed.get((root, venue), day))
    for root, venue in sorted((r, v) for r, v in roots if r and v):
        key = (root, venue)
        metadata = catalog.get(key, {})
        scope = metadata.get('catalog_scope') or ('US_listed' if venue in
                {'CME', 'CBOT', 'NYMEX', 'COMEX', 'CFE'} else 'unknown')
        out.append(dict(instrument=f'FUT:{root}:{venue}', asset_class='future', root=root,
                        venue=venue, series_label=f'{root}:{venue}',
                        optionability=('unexpired_contract_observed' if key in contracts else
                                       'chain_metadata_only' if key in observed else 'optionability_unknown'),
                        option_asof=contracts.get(key) or observed.get(key), listing_scope=scope,
                        **metadata))
    return out
