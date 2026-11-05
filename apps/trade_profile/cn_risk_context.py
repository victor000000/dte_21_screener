"""Pinned account evidence and exact-future scenario aggregation for CN holdings."""
from data_providers.providers import cn_workspace


def accounts_for(release, accounts):
    if not accounts:
        return []
    with cn_workspace.connection('trades',release) as con:
        rows=cn_workspace.records(con, '''SELECT account,day,currency,net_liq,margin_used,
            available,risk_ratio,source,notes FROM account_daily
            WHERE account IN (SELECT unnest(?)) AND currency='CNY'
            QUALIFY row_number() OVER (PARTITION BY account ORDER BY day DESC,
                CASE WHEN source='cn_tracker_header_v1' THEN 0 ELSE 1 END)=1''',[sorted(accounts)])
    return [dict(r, day=str(r['day']), observation_basis='Dated broker export, not live buying power',
                 warning_budget_cny=r['net_liq']*.05 if r['net_liq'] and r['net_liq']>0 else None,
                 limit_budget_cny=r['net_liq']*.10 if r['net_liq'] and r['net_liq']>0 else None) for r in rows]


def group_scenarios(legs):
    models=[leg.get('model') for leg in legs]
    shocks=(-10,-5,-3,-1,0,1,3,5,10)
    complete=bool(models) and all(m and len(m.get('scenarios',[]))==len(shocks) for m in models)
    return dict(scenarios_complete=complete,scenarios=[dict(move_pct=move,
        pnl_cny=sum(m['scenarios'][i]['pnl_cny'] for m in models) if complete else None,
        iv_up_10pp_pnl_cny=sum(m['scenarios'][i]['iv_up_10pp_pnl_cny'] for m in models) if complete else None)
        for i,move in enumerate(shocks)])
