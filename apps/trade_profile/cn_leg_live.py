"""CN held-leg valuation using provider positions and immutable Sina transport receipts.

Writes application reports only; no ingestion, canonical writes or order actions.
"""
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import re
import threading
import time

from data_providers.providers import cn_positions
from data_providers.providers.sina_futures import SinaFutures
from data_providers.runtime import data_home
from .cn_live_inputs import native_ids, multiplier_evidence
from .cn_live_valuation import value_leg
from .cn_live_status import status
from .cn_risk_context import accounts_for, group_scenarios

OUT = Path(__file__).resolve().parents[2] / 'reports' / 'cn_leg_live'
LOCK = threading.Lock()
LAST_ATTEMPT = float("-inf")
LAST_ERROR = None


def refresh():
    snapshot = cn_positions.positions()
    positions = snapshot['positions']
    if not positions:
        raise ValueError('No provider-delivered CN positions')
    evidence = multiplier_evidence(snapshot)
    codes = list(dict.fromkeys(code for p in positions for code in native_ids(p)))
    client = SinaFutures(data_home()/'var/interactive-quotes/cn/raw', tries=1, timeout=(5,12))
    client.session.headers['Referer'] = 'https://finance.sina.com.cn'
    response = client.get('https://hq.sinajs.cn/list='+','.join(codes))
    received = datetime.now(timezone.utc)
    fields = {k:v.split(',') for k,v in re.findall(r'var hq_str_([^=]+)="([^"]*)"', response.content.decode('gb18030'))}
    legs = [value_leg(p,fields,received,evidence.get(p['symbol'],dict(multiplier=None,multiplier_basis='Unavailable'))) for p in positions]
    legs.sort(key=lambda r:(r['broker'],r['root'],r['premium_pnl_pct'] is None,r['premium_pnl_pct'] or 0))
    groups = defaultdict(list)
    for r in legs:
        groups[(r['broker'],r['account'],r['future'])].append(r)
    futures = []
    for (broker,account,future), rows in groups.items():
        futures.append(dict(broker=broker,account=account,future=future,legs=len(rows),
            close_pnl_cny=sum(r['close_pnl_cny'] for r in rows if r['close_pnl_cny'] is not None) if any(r['close_pnl_cny'] is not None for r in rows) else None,
            pnl_complete=all(r['close_pnl_cny'] is not None for r in rows),
            **group_scenarios(rows),
            **{k:sum(r['model'][k] for r in rows) if all(r['model'] for r in rows) else None
               for k in ('position_delta','gamma_pnl_1pct_cny','up_1pct_cny','down_1pct_cny','vega_cny_per_point','theta_cny_per_day')}))
    result = dict(generated_utc=received.isoformat(),release=snapshot['release'],legs=legs,futures=futures,
                  accounts=accounts_for(snapshot['release'],{r['account'] for r in legs}),
                  source='Sina native exact-contract books via provider transport',source_sha256=hashlib.sha256(response.content).hexdigest(),
                  quoted_legs=sum(r['quote'] is not None for r in legs),cash_legs=sum(r['close_pnl_cny'] is not None for r in legs),
                  close_pnl_cny=sum(r['close_pnl_cny'] for r in legs if r['close_pnl_cny'] is not None) if any(r['close_pnl_cny'] is not None for r in legs) else None,
                  limitations=['Holdings are the latest published broker exports, not a live CN account connection.',
                    'Native quote clock is not certified as the book event clock; feed delay is unknown. Receipt time is not quote time.',
                    'Shorts close at ask; longs at bid. Estimated P&L excludes fees/slippage and assumes displayed prices for all contracts.',
                    'Premium return uses absolute entry premium, not margin. Inferred multipliers are not exchange verified.',
                    'Model Greeks/scenarios are estimates at each dated midpoint, not current broker Greeks or margin forecasts.',
                    'No cross-product or cross-month delta netting. Current account buying power unavailable.'])
    OUT.mkdir(parents=True,exist_ok=True)
    name = received.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
    payload = json.dumps(result,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n'
    (OUT/name).write_text(payload)
    temp = OUT/'latest.tmp'
    temp.write_text(payload)
    temp.replace(OUT/'latest.json')
    return result


def report(update=False):
    global LAST_ATTEMPT, LAST_ERROR
    with LOCK:
        latest = OUT/'latest.json'
        # Leave jitter room for the UI's 10-second cadence; coalesce concurrent tabs.
        if update and time.monotonic()-LAST_ATTEMPT >= (30 if LAST_ERROR else 9):
            LAST_ATTEMPT = time.monotonic()
            try:
                result = refresh()
                LAST_ERROR = None
                return status(result)
            except Exception:
                LAST_ERROR = 'CN source refresh failed; displaying saved evidence. Automatic retry after 30 seconds.'
        if LAST_ERROR and not latest.exists():
            raise ValueError(LAST_ERROR)
        result = json.loads(latest.read_text()) if latest.exists() else dict(legs=[],futures=[],limitations=[],generated_utc=None)
        result['refresh_error'] = LAST_ERROR
        return status(result)


if __name__ == '__main__':
    print(json.dumps(report(update=True),ensure_ascii=False,indent=2,default=str))
