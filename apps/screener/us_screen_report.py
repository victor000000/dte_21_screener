"""Export every observed candidate and summarize verified versus unknown listing scope."""
import bootstrap
import csv
import json
from collections import Counter
from data import clock


def write_reports(rows, expected_day, min_ivr, gaps, release=None, strict_ivr=False):
    directory = bootstrap.ROOT / 'reports'
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / f'ivr_all_us_{clock.today()}'
    columns = sorted({k for r in rows for k in r})
    with stem.with_suffix('.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(asof=str(expected_day), release=release, candidates=len(rows),
                   ivr_threshold=min_ivr, ivr_operator='>' if strict_ivr else '>=',
                   asset_classes=dict(Counter(r['asset_class'] for r in rows)),
                   listing_scopes=dict(Counter(r.get('listing_scope', 'unknown') for r in rows)),
                   futures_with_iv=sum(r['asset_class'] == 'future' and r['ivr'] is not None for r in rows),
                   matches=sum(r['status'] == 'MATCH' for r in rows),
                   high_ivr=sum(r['high_ivr'] for r in rows), coverage_gaps=gaps)
    stem.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    text = [f'# All-US optionable-instrument IVR screen — {clock.today()}', '',
            f'Provider release: {release or "live read-only stores; no published release"}.',
            f'Underlying market data through {expected_day}. Read-only provider observations; no live quotes.',
            'IVR = 100*(latest IV-min IV)/(max IV-min IV); 252 daily observations, minimum 60.',
            'IV percentile is separate. Partial histories and each source/as-of are in the CSV.',
            'All provider-observed candidates are assessed before strategy filtering; unknown optionability remains visible.',
            f'Stock/fund MATCH: IVR {">" if strict_ivr else ">="} {min_ivr}, 20-session average volume >5M shares/day,',
            'average price >$30, capitalization/AUM >$1B, observed unexpired options and non-stale inputs.',
            'Capitalization may be cached. MATCH is an IVR/liquidity screen, not an option-leg or earnings approval.',
            'Futures/index liquidity rules are unconfigured; stock price/capitalization/share-volume gates do not apply.',
            'Futures IV is isolated by source, series, tenor, roll/model and method version; delivery details are in the CSV.',
            'Legacy IBKR continuous-future reported IV is not independently validated contract-specific ATM IV.',
            f"Listing scopes: {summary['listing_scopes']}; unspecified venues are not confirmed US listings.", '',
            f"Inventory: {summary['asset_classes']}; {summary['matches']} stock/fund matches.", '',
            '## Futures and indices: IVR and coverage', '', '| Instrument | IVR | IV date | n | Status |',
            '|---|---:|---|---:|---|']
    derivatives = [r for r in rows if r['asset_class'] != 'equity_or_fund']
    displayed = [r for r in derivatives if r['ivr'] is not None]
    unranked = [r for r in derivatives if r['ivr'] is None]
    unranked.sort(key=lambda r: (r['optionability'] not in
                  ('unexpired_contract_observed', 'chain_metadata_only'), r['instrument']))
    displayed += unranked[:40]
    for r in displayed:
        ivr = '-' if r['ivr'] is None else f"{r['ivr']:.1f}"
        text.append(f"| {r['instrument']} | {ivr} | {r['iv_asof']} | {r['iv_sessions']} | {r['status']} |")
    text += ['', f'{len(derivatives)} derivatives candidates; all ranked readings and the first 40 unrankable cases shown. Full catalog coverage is in the CSV.']
    text += ['', '## Top stock/fund matches', '', '| Ticker | IVR | 20-session volume | Average price |',
             '|---|---:|---:|---:|']
    for r in [r for r in rows if r['status'] == 'MATCH'][:30]:
        text.append(f"| {r['instrument']} | {r['ivr']:.1f} | {r['avg_volume']/1e6:.2f}M | ${r['avg_price']:.2f} |")
    text += ['', '## Coverage gaps', ''] + [f'- {g}' for g in gaps]
    text += ['', f'Full inventory and all failed/pending rules: {stem.name}.csv', '']
    stem.with_suffix('.md').write_text('\n'.join(text))
    print(json.dumps(summary))
    print(f'wrote {stem}.md and .csv/.json')
    return summary
