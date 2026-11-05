"""Class-aware range-IVR rules; missing data stays distinct from a failed threshold."""
import math
from compute.iv_rank import rank_series


def assess(item, iv_rows, metrics, expected_day, min_ivr=35, strict_ivr=False):
    result = dict(item, **metrics)
    rank = rank_series(iv_rows)
    passes_ivr = rank is not None and rank['ivr'] is not None and (
        rank['ivr'] > min_ivr and not math.isclose(rank['ivr'], min_ivr, rel_tol=0, abs_tol=1e-10)
        if strict_ivr else rank['ivr'] >= min_ivr)
    result.update(ivr=rank['ivr'] if rank else None, ivp=rank['ivp'] if rank else None,
                  iv=rank['iv'] if rank else None, iv_asof=rank['last_day'] if rank else None,
                  iv_sessions=rank['n'] if rank else 0, iv_source=rank['source'] if rank else None,
                  iv_method=rank['kind'] if rank else 'no comparable daily IV series')
    reasons = []
    if item.get('listing_scope', 'US_listed') != 'US_listed':
        reasons.append('MARKET_SCOPE_UNVERIFIED')
    if rank is None or rank['ivr'] is None:
        reasons.append('UNRANKABLE')
    elif not passes_ivr:
        reasons.append('LOW_IVR')
    if rank and rank['last_day'] and expected_day and rank['last_day'] < expected_day:
        reasons.append('STALE_IV')
    if item['optionability'] not in ('unexpired_contract_observed', 'chain_metadata_only'):
        reasons.append('OPTIONABILITY_UNVERIFIED')
    if item['asset_class'] != 'equity_or_fund':
        reasons.append('LIQUIDITY_RULE_UNCONFIGURED')
        if not metrics.get('liquidity_sessions'):
            reasons.append('MISSING_CONTRACT_LIQUIDITY')
    else:
        if metrics.get('liquidity_sessions', 0) < 20:
            reasons.append('INSUFFICIENT_PRICE_VOLUME_HISTORY')
        if expected_day and metrics.get('price_asof') and metrics['price_asof'] < expected_day:
            reasons.append('STALE_PRICE_VOLUME')
        for name, floor, label in [('avg_volume', 5e6, 'LOW_SHARE_VOLUME'),
                                   ('avg_price', 30, 'LOW_PRICE'),
                                   ('capitalization', 1e9, 'LOW_CAP_OR_AUM')]:
            value = metrics.get(name)
            if value is None or not math.isfinite(value):
                reasons.append(f'MISSING_{name.upper()}')
            elif value <= floor:
                reasons.append(label)
    result['status'] = '; '.join(reasons) if reasons else 'MATCH'
    result['high_ivr'] = passes_ivr
    result.update(ivr_threshold=min_ivr, ivr_operator='>' if strict_ivr else '>=')
    return result
