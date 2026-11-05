"""windows.py — per-horizon IVR: the latest ATM IV ranked inside its own trailing window.

board.py ranks each product against its whole stored series, which answers the right question
only while every series is the same length. They are not: CN options listed years apart (SHFE
copper 2018-09, butadiene rubber 2023-07, CZCE glass 2024, CFFEX MO 2022-07), so a product's
history is whatever its own listing allows — 4.2 years for MO, 8 for copper, 2 for nothing.

That is why a window a product cannot cover must not return a number. A "5Y IVR" computed over
2.7 years of CZCE data is not a 5-year reading, and printed beside a genuine one it is
indistinguishable from it. So the uncovered case returns ivr=None and the board prints `full`,
pointing at the whole-series column — which IS that product's since-inception range rank.

The range rank itself is `compute.iv_rank.range_rank`, shared with rank_series, so a window and
the whole series can never disagree about the same day.
"""
import datetime as dt

from compute.iv_rank import MIN_POINTS, daily_series, range_rank

WINDOWS = (("1Y", 365), ("2Y", 730), ("5Y", 1825), ("10Y", 3650))
SLACK_DAYS = 10   # a series starting a holiday week after the cutoff still covers the window


def rank_windows(rows, asof=None):
    """rows: [(day, iv)] for ONE product from ONE source -> {label: entry} for every WINDOW.

    entry = {"ivr": float|None, "n": int, "covered": bool}: the range rank of the latest value
    among the window's points, how many points that was, and whether the product's own history
    actually reaches back the whole window.

    `asof` defaults to the series' own last day — the DATA day, never today's clock. A board
    three sessions stale must not rank a window that ends three sessions after the series does,
    or the window silently becomes the whole series and every horizon shows the same number.
    """
    rows = daily_series(rows)
    if not rows:
        return {}
    asof = asof or rows[-1][0]
    # Everything is measured AT asof: the value ranked, the points a window contains, and the
    # cutoff itself. Ranking the latest stored IV against a window that stops earlier (or
    # letting days after asof into the window) would answer a question about a different day
    # while printing one date.
    upto = [(d, v) for d, v in rows if d <= asof]
    if not upto:
        return {}
    oldest, cur = rows[0][0], upto[-1][1]
    out = {}
    for label, days in WINDOWS:
        cutoff = asof - dt.timedelta(days=days)
        covered = oldest <= cutoff + dt.timedelta(days=SLACK_DAYS)
        win = [v for d, v in upto if d > cutoff]
        out[label] = {"ivr": (range_rank(win, cur) if covered and len(win) >= MIN_POINTS
                              else None),
                      "n": len(win), "covered": covered}
    return out
