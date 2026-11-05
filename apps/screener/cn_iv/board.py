"""board.py — the CN product board: every product in cn_product_map, ranked by IVR.

Two things this does differently from the US screen, both because CN is not US:

  ONE SERIES PER PRODUCT, THE LONGEST ONE. A product can carry more than one series (SC has a
  64-point akshare_sc_hist and a ~420-point akshare_sc_vol, built from different endpoints of
  the same exchange). rank_series' own SOURCE_RANK picks by source NAME, which is a US
  ordering that knows nothing about these; and ranking on 64 points when 420 are stored would
  waste the deeper series. A product is never ranked on a mixture of two.

  THE UNIVERSE COMES FROM THE MAP, not from iv_history. Iterating the series instead would
  silently drop every product that has no series yet -- the board would look complete while a
  whole venue was missing from it, which is the one failure a ranking table must not have.

  THE HORIZONS COME FROM THE SAME CHOSEN SERIES. 1Y/2Y/5Y/10Y are windows of the source picked
  above, not a second scan of iv_history -- otherwise a product could be ranked over one series
  in the IVR column and a different one in the 5Y column, and nothing in the table would say so.

The rendering lives in render.py (this file is held to the repo's 100-line cap and the text got
too long); `render` is re-exported below, so `board.render(...)` keeps working for callers and
tests that reach it here.
"""
from apps.screener.cn_iv.render import render  # noqa: F401  (re-export, see docstring)
from apps.screener.cn_iv.windows import rank_windows
from compute.iv_rank import MIN_POINTS, daily_series, rank_series

__all__ = ["build_board", "pick_series", "render"]


def pick_series(by_source):
    """The series to rank: the longest that can carry an IVR, else the longest at all.

    Returns (source, [(day, iv)]) -- one source's rows, never a mixture. A product ranked
    across two endpoints would be measuring a seam, not a range.
    """
    daily = {s: daily_series(v) for s, v in by_source.items()}
    if not daily:
        return None, []
    ranked = [s for s, v in daily.items() if v and
              rank_series([(s, d, iv) for d, iv in v], lookback=None)["ivr"] is not None]
    src = max(ranked or daily, key=lambda s: (len(daily[s]), s))
    return src, daily[src]


def build_board(universe, series, bars):
    """-> list of per-product dicts, ranked (rankable first, by IVR descending)."""
    board = []
    for prod, venue, _name in universe:
        n_bars, last_bar = bars.get(prod, (0, None))
        entry = {"product": prod, "venue": venue, "src": None, "n": 0, "res": None,
                 "windows": {}, "since": None,
                 "bars": n_bars, "last_bar": last_bar, "others": []}
        if prod in series and any(series[prod].values()):
            src, rows = pick_series(series[prod])
            if not rows:
                board.append(entry)
                continue
            entry.update(src=src, n=len(rows), since=min(d for d, _ in rows),
                         res=rank_series([(src, d, v) for d, v in rows], lookback=None),
                         windows=rank_windows(rows),
                         others=[s for s in series[prod] if s != src])
        board.append(entry)
    board.sort(key=lambda b: -(b["res"]["ivr"] if b["res"] and b["res"]["ivr"] is not None
                               else -1))
    return board
