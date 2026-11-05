"""IVR is range position; IVP is observation frequency, never an HV proxy.

US defaults to the latest 252 distinct daily observations (at least 60 required).
CN full-history callers explicitly use lookback=None; calendar horizons are separate.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bootstrap  # noqa: F401

SOURCE_RANK = ("futu_panel", "ibkr_tws30d", "akshare_ma_hist", "akshare_sc_hist", "yf_chain")
MIN_POINTS = 60
LOOKBACK_POINTS = 252


def percentile(ivs, cur):
    """IVP: share of observations at or below the latest IV, including ties (0-100)."""
    return sum(1 for v in ivs if v <= cur + 1e-12) / len(ivs) * 100


def valid_iv(value):
    return value is not None and math.isfinite(value) and value > 0


def daily_series(rows):
    """Collapse identical dates; conflicting values invalidate that date, never pick a max."""
    days = {}
    for day, value in rows:
        if day is None:
            return []
        if day in days and days[day] != value:
            days[day] = None
        else:
            days[day] = value
    return sorted(days.items())


def range_rank(ivs, cur):
    """IVR = 100*(current-low)/(high-low); current must belong to the supplied window."""
    if not ivs or not valid_iv(cur) or not all(valid_iv(v) for v in ivs):
        return None
    low, high = min(ivs), max(ivs)
    return (cur-low)/(high-low)*100 if low <= cur <= high and high > low else None


def iv_column(con, table="mh.iv_history"):
    """Use the same canonical IV expression through both schema generations."""
    columns = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
    if not columns & {"iv", "atm_iv"}:
        raise ValueError(f"{table} has no IV column")
    return "coalesce(iv, atm_iv)" if {"iv", "atm_iv"} <= columns else "iv" if "iv" in columns else "atm_iv"


def fetch_series(con, col=None, table="mh.iv_history", symbols=None):
    """Return daily observations by underlying, and excluded (underlying, source) pairs.

    An expiry label is allowed when there is only one distinct IV per source/day.
    Any fan-out day excludes the whole source, avoiding a mixture of expiry tenors.
    """
    col = col or iv_column(con, table)
    where = [f"{col} IS NOT NULL"]
    params = []
    if symbols is not None:
        syms = sorted(symbols)
        if not syms:
            return {}, {}
        where.append("underlying = ANY(?)")
        params.append(syms)
    rows = con.execute(f"""
        SELECT underlying, source, day, max({col}) AS iv,
               count(DISTINCT {col}) AS n_iv
        FROM {table} WHERE {' AND '.join(where)}
        GROUP BY 1, 2, 3 ORDER BY 1, 3""", params).fetchall()

    by_src, excluded = {}, {}
    for u, src, day, iv, n_iv in rows:
        if n_iv > 1:
            excluded[(u, src)] = (f"{n_iv} distinct IVs on {day} — per-expiry rows, "
                                  f"not a single daily series")
            continue
        by_src.setdefault(u, {}).setdefault(src, []).append((day, iv))
    # Exclude the whole source, not just the day with multiple expiry observations.
    for u, src in excluded:
        by_src.get(u, {}).pop(src, None)
    by_underlying = {u: [(s, d, v) for s in srcs for d, v in srcs[s]]
                     for u, srcs in by_src.items()}
    return by_underlying, excluded



def _rank_daily(src, series, min_points, lookback):
    window = series[-lookback:] if lookback is not None else series
    ivs = [v for _, v in window]
    cur = ivs[-1] if ivs else None
    valid = bool(ivs) and all(valid_iv(v) for v in ivs)
    enough = len(ivs) >= min_points
    rank = range_rank(ivs, cur) if enough else None
    reason = (f"IVR needs {min_points}" if not enough else
              "latest IV is NaN/non-finite/non-positive" if not valid_iv(cur) else
              "invalid IV history" if not valid else "flat IV range" if rank is None else "")
    reason = ", ".join(filter(None, [reason, "partial history" if lookback is not None and len(ivs) < lookback else ""]))
    horizon = f"last {lookback} observations" if lookback is not None else "full history"
    return {"source": src, "last_day": window[-1][0] if window else None,
            "first_day": window[0][0] if window else None, "n": len(ivs),
            "iv": cur if valid_iv(cur) else None, "ivr": rank,
            "ivp": percentile(ivs, cur) if enough and valid else None,
            "kind": f"{src}(range IVR, {horizon}, n={len(ivs)}" + (f", {reason}" if reason else "") + ")"}


def rank_series(rows, min_points=MIN_POINTS, lookback=LOOKBACK_POINTS):
    """Rank one underlying, choosing a usable source before applying source preference."""
    if lookback is not None and lookback < 1:
        raise ValueError("lookback must be positive or None for full history")
    by_src = {}
    for src, day, iv in rows:
        by_src.setdefault(src, []).append((day, iv))
    if not by_src:
        return None
    results = [_rank_daily(s, daily_series(v), min_points, lookback) for s, v in sorted(by_src.items())]
    ranked = [r for r in results if r["ivr"] is not None]
    def priority(result):
        src = result["source"]
        return (SOURCE_RANK.index(src) if src in SOURCE_RANK else len(SOURCE_RANK), -result["n"], src)
    return min(ranked, key=priority) if ranked else max(results, key=lambda r: r["n"])
