"""Bounded views of saved screener reports; no new acquisition or trade decisions."""
import csv
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]/'reports'


def read_report(query, root=ROOT):
    root = Path(root)
    candidates = sorted(root.glob('ivr_all_us_????-??-??.json'), reverse=True)
    path = next((p for p in candidates if p.with_suffix('.csv').is_file()), None)
    if path is None:
        return dict(available=False, rows=[], message='No saved all-US screen is available.')
    mode = query.get('mode', ['matches'])[0]
    if mode not in {'matches','high_ivr','all'}:
        raise ValueError('Unknown screen filter')
    search = query.get('search', [''])[0].strip().upper()
    offset = int(query.get('offset', ['0'])[0])
    if not 0 <= offset <= 100000 or len(search)>40:
        raise ValueError('Invalid screen page or search')
    metadata = json.loads(path.read_text())
    with path.with_suffix('.csv').open(newline='') as handle:
        selected = [r for r in csv.DictReader(handle)
                    if (mode=='all' or mode=='matches' and r.get('status')=='MATCH'
                        or mode=='high_ivr' and r.get('high_ivr')=='True')
                    and (not search or search in r.get('instrument','').upper())]
    return dict(available=True, metadata=metadata, report=path.name, matched=len(selected),
                offset=offset, limit=100, rows=selected[offset:offset+100],
                next_offset=offset+100 if offset+100<len(selected) else None,
                basis='Saved screen; report and input dates are historical, not live trade eligibility.')
