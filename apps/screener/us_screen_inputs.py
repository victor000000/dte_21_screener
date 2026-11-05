"""Read-only liquidity and capitalization inputs, with explicit units and dates."""
import json
from apps.screener.us_inventory import table_exists


def equity_metrics(con, cache_path):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    rows = con.execute("""WITH recent AS (
        SELECT symbol,date,close,volume,row_number() OVER (PARTITION BY symbol ORDER BY date DESC) rn
        FROM yh.prices WHERE date >= (SELECT max(date) FROM yh.prices)-60
        AND isfinite(close) AND close>0 AND isfinite(volume) AND volume>=0)
        SELECT symbol,avg(close),avg(volume),count(*),max(date) FROM recent
        WHERE rn<=20 GROUP BY 1""").fetchall()
    caps = {s: (v, 'cached marketcap/AUM') for s, v in cache.items() if v and v > 0}
    if table_exists(con, 'mh.fundamentals_snapshot'):
        for s, v, day, source in con.execute("""SELECT symbol,market_cap,day,source
                FROM mh.fundamentals_snapshot WHERE isfinite(market_cap) AND market_cap>0
                QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY day DESC,source)=1""").fetchall():
            caps[s] = (v, f'{source} {day}')
    return {s: dict(avg_price=p, avg_volume=v, liquidity_sessions=n, price_asof=d,
                    volume_unit='shares/day', capitalization=caps.get(s, (None, 'missing'))[0],
                    cap_source=caps.get(s, (None, 'missing'))[1]) for s, p, v, n, d in rows}


def futures_metrics(con, today):
    if not all(table_exists(con, f'mh.{t}') for t in ['us_futures_daily', 'us_futures_contracts']):
        return {}
    rows = con.execute("""WITH observations AS (
        SELECT DISTINCT d.source,d.contract_id,d.root,d.venue,d.day,d.close,d.volume,c.expiry
        FROM mh.us_futures_daily d JOIN mh.us_futures_contracts c
        ON d.source=c.source AND d.contract_id=c.contract_id
        WHERE c.sec_type='FUT' AND c.expiry>=? AND isfinite(d.volume) AND d.volume>=0
        AND d.day<=?), recent AS (
        SELECT *,row_number() OVER (PARTITION BY source,contract_id ORDER BY day DESC) rn
        FROM observations), summaries AS (
        SELECT root,venue,source,contract_id,expiry,avg(close) p,avg(volume) v,count(*) n,max(day) last_day
        FROM recent WHERE rn<=20 GROUP BY 1,2,3,4,5)
        SELECT root,venue,contract_id,p,v,n,last_day FROM summaries
        QUALIFY row_number() OVER (PARTITION BY root,venue ORDER BY last_day DESC,v DESC,expiry,source,contract_id)=1""",
        [today, today]).fetchall()
    return {(r, venue): dict(liquidity_contract=cid, avg_price=p, avg_volume=v,
                            liquidity_sessions=n, price_asof=d, volume_unit='contracts/day',
                            capitalization=None, cap_source='not applicable')
            for r, venue, cid, p, v, n, d in rows}
