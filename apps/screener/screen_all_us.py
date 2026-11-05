"""Default US range-IVR screen: all provider-observed equities/funds, indices and futures."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap
import argparse
from data import clock
from compute.iv_rank import fetch_series
from apps.screener.us_inventory import inventory
from apps.screener.us_screen_inputs import equity_metrics, futures_metrics
from apps.screener.us_screen_rules import assess
from apps.screener.us_screen_data import open_snapshot, futures_iv
from apps.screener.us_screen_report import write_reports


def run(min_ivr=50, strict_ivr=True):
    con, release = open_snapshot(bootstrap.DATA_ROOT)
    try:
        today = clock.today()
        items = inventory(con, today)
        per, excluded = fetch_series(con)
        typed, methods = futures_iv(con)
        equities = equity_metrics(con, bootstrap.DATA_ROOT / 'var/cache_marketcap.json')
        futures = futures_metrics(con, today)
        expected = con.execute('SELECT max(date) FROM yh.prices').fetchone()[0]
        rows = []
        for item in items:
            is_future = item['asset_class'] == 'future'
            label = item['series_label']
            # Never append legacy rows to fill a short or invalid typed history.
            iv_rows = typed[label] if is_future and label in typed else per.get(label, [])
            metrics = futures.get((item['root'], item['venue']), {}) if is_future else equities.get(item['root'], {})
            result = assess(item, iv_rows, metrics, expected, min_ivr, strict_ivr=strict_ivr)
            if is_future:
                result.update(methods.get(result['iv_source'], {'iv_delivery': 'legacy_iv_history'}))
            rows.append(result)
    finally:
        con.close()
    rows.sort(key=lambda r: (r['ivr'] is None, -(r['ivr'] or 0), r['instrument']))
    gaps = ['Full-US venue coverage and authoritative optionability/security master remain pending provider delivery; ICE/other unsupported feeds are not complete.',
            'The published product catalog includes outright, combo and mixed-definition families; catalog presence does not establish active options.',
            'Direct bond-option inventory is unverified; bond funds remain in equity/fund candidates and Treasury futures are separate.',
            'No configured futures/index liquidity thresholds; these instruments cannot receive a full MATCH.',
            f'{len(excluded)} source/symbol pairs excluded as ambiguous per-expiry IV series.',
            'Missing, stale or flat series and unknown venue scope are retained in the CSV.']
    write_reports(rows, expected, min_ivr, gaps, release=release, strict_ivr=strict_ivr)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    thresholds = ap.add_mutually_exclusive_group()
    thresholds.add_argument('--min-ivr', type=float, help='inclusive IVR floor')
    thresholds.add_argument('--ivr-above', type=float, help='strict IVR floor (default: >50)')
    args = ap.parse_args()
    run(args.min_ivr, strict_ivr=False) if args.min_ivr is not None else run(
        args.ivr_above if args.ivr_above is not None else 50, strict_ivr=True)


if __name__ == '__main__':
    main()
