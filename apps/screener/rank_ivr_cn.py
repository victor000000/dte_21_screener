import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""CN product board, ranked by IVR over published cn_market.iv_history.

The US screen answers "which of 3,000 names is rich against its own history"; this answers the
same question for the 23 products in cn_product_map, which is the whole tradable CN option
universe we hold. Same ranker -- compute.iv_rank.rank_series -- so an IVR of 90 means the same
thing on both boards. The selection rule (one series per product, the longest one) and the
rendering live in apps/screener/cn_iv/board.py; this file is the query and the file write.

Rankable is not tradable: a product whose chains are missing or long expired can rank 100 and
still have no legs to sell, so the bars column carries the latest chain date and the two are
read together.

"""
import argparse

from data_providers.lake import connect_store

from apps.screener.cn_iv.board import build_board, render
from bootstrap import ROOT
from data import clock

DB = bootstrap.DATA_ROOT / "cn_market.duckdb"
REPORTS = ROOT / "reports"


def load(db_path):
    if pathlib.Path(db_path).resolve() == DB.resolve():
        con = connect_store(bootstrap.DATA_ROOT, "cn")
    else:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""SELECT underlying, source, day, atm_iv FROM iv_history
                          WHERE atm_iv IS NOT NULL ORDER BY underlying, day""").fetchall()
    bars = {r[0]: (r[1], r[2]) for r in con.execute(
        """SELECT product, count(*), max(day) FROM option_bars GROUP BY 1""").fetchall()}
    # The universe comes from the MAP, not from iv_history -- iterating the series would
    # silently drop every product that has no series yet.
    universe = con.execute("""SELECT product, venue, ak_symbol FROM cn_product_map
                              ORDER BY product""").fetchall()
    con.close()
    series = {}
    for u, s, d, iv in rows:
        series.setdefault(u, {}).setdefault(s, []).append((d, iv))
    return universe, series, bars


def staleness(data_day):
    """Why the board is behind the clock, read off the exchanges' own trading calendar.

    Returns None when the calendar cannot be reached, and the note then says nothing -- which
    is the point. Its predecessor hardcoded "Golden Week (Oct 1-8, 2026)" and fired on ANY gap
    of two days or more, so a downloader that had silently died for a week would have been
    reported as a closed exchange. The dates were wrong too: the exchanges shut Oct 1-7 and
    reopened Oct 8. A holiday is something the calendar knows; a gap is something we caused,
    and the two must not print the same sentence.
    """
    if data_day is None:
        return None
    try:
        import akshare as ak

        from apps.screener.cn_iv.calendar import cn_calendar, closed_since
        cal = cn_calendar(ak)
    except Exception:                                          # noqa: BLE001
        return None
    missed = closed_since(cal, data_day, clock.now())
    if missed:
        return (f"{len(missed)} CN session(s) since are NOT stored (latest {missed[-1]}) "
                f"— a download gap, not a holiday.")
    nxt = next((d for d in cal if d > data_day), None)
    return f"No CN session is missing: the next session after the data is {nxt}."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ivr", type=float, default=35.0,
                    help="IVR floor for PASS (user criterion, 2026-10-04)")
    ap.add_argument("--write", action="store_true", help="write reports/ivr_cn_<date>.md")
    ap.add_argument("--db", default=str(DB), help="read another copy (smoke test)")
    args = ap.parse_args()

    universe, series, bars = load(args.db)
    board = build_board(universe, series, bars)
    data_day = max((b["res"]["last_day"] for b in board if b["res"]), default=None)
    text = render(board, data_day, args.min_ivr, context=staleness(data_day))
    print(text)
    if args.write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        out = REPORTS / f"ivr_cn_{clock.today()}.md"
        out.write_text(text)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
