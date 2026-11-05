import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""build_screen_universe.py — the download universe, defined by the trade filter.

The filter (user, 2026-10-04):

    market cap        > $1,000 M
    20-day avg volume > 5,000,000 shares
    20-day avg price  > $30
    IVR               > 35      (100 * (latest IV - min IV) / (max IV - min IV), own series)

IVR, not raw IV. The filter used to read "last-day IV > 50%", which is a different screen:
it admitted high-IV names pinned at the bottom of their own range (OKLO IV 66%, IVR 0) and
excluded low-IV names at their own highs (MUB IV 9.7%, IVR 99). The strategy sells premium
when a name's vol is rich relative to its own history, which is what IVR measures. The
ranking rule lives in compute/iv_rank.py, shared with the screen itself, so the filter's
scope and the screen's PASS cannot disagree about a ticker.

Why this exists: we were downloading option history for 6,005 names when the strategy can
only trade a small fraction of them. The liquidity and price legs alone cut it from 6,005 to
230 — and every name past that is quota spent on contracts the screen would never pick. The
filter is the scope, so it lives in code rather than in a message.

Order matters, cheapest first:
  1. 20d avg volume / price   — local, instant, from the warehouse
  2. market cap               — one vendor call per SURVIVING name (230, not 6,005)
  3. IVR                      — ranked over iv_history, which the IV sweep is filling

Stage 3 is the binding constraint: a name needs ≥60 daily IV points before it can be ranked,
so names without a series yet are reported as PENDING rather than silently dropped. A name
that ranks below 35 is judged and dropped — that is the filter working, not a gap.

Output: plans/universe_screen.txt (the names to download), plus a printed breakdown.
"""
import argparse
import datetime as dt
import json
import pathlib
import socket
import sys

from data import clock  # noqa: E402
from data import db  # noqa: E402
from compute.iv_rank import fetch_series, rank_series  # noqa: E402

ROOT = bootstrap.ROOT
socket.setdefaulttimeout(25)          # yfinance hangs rather than erroring

MIN_MCAP = 1_000e6
MIN_VOL = 5e6
MIN_PX = 30.0
MIN_IVR = 35.0                        # IV rank floor (user criterion, 2026-10-04; was IV > 50%)
LOOKBACK = 20


def liquidity(c, days=45):
    """20-day average volume and price, per symbol, from the warehouse."""
    q = f"""
        WITH w AS (
            SELECT symbol, close, volume,
                   row_number() OVER (PARTITION BY symbol ORDER BY date DESC) rn
            FROM yh.prices
            WHERE date >= (SELECT max(date) FROM yh.prices) - {days}
              AND volume IS NOT NULL AND close > 0)
        SELECT symbol, avg(volume) av, avg(close) ap
        FROM w WHERE rn <= {LOOKBACK} GROUP BY symbol"""
    return {r[0]: (r[1], r[2]) for r in c.execute(q).fetchall() if r[1] and r[2]}


def market_caps(symbols, cache_path):
    """One vendor call per surviving name. Cached, because this is the slow leg."""
    import yfinance as yf
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}
    # A null is NOT a cached answer — re-probe it. `s not in cache` treated a stored null as
    # done, so once a lookup failed the name was banned forever. Worse, for ETFs the failure
    # is SYSTEMATIC, not transient: yfinance's fast_info carries no market cap for funds, so
    # SPY, QQQ, IWM, TLT, GLD, EEM and ~45 other funds were all silently excluded from the
    # universe. Re-probing lets a better source fill them in; until then they are reported
    # as unknown rather than treated as too small.
    todo = [s for s in symbols if not cache.get(s)]
    if todo:
        print(f"  fetching market cap for {len(todo)} names...", flush=True)
    for i, s in enumerate(todo):
        mc = None
        mc = None
        try:
            fi = yf.Ticker(s).fast_info
            # FastInfo is attribute-first; .get() silently returns nothing, which is how a
            # whole run reported "mcap>1B: 0" while quietly succeeding at fetching nothing.
            mc = getattr(fi, "market_cap", None)
            if mc is None:
                try:
                    mc = fi["marketCap"]
                except Exception:
                    mc = None
        except Exception:
            mc = None
        if mc is None:
            # FUNDS HAVE NO marketCap. fast_info returns None for every ETF, which silently
            # dropped SPY, QQQ, IWM, TLT, GLD, EEM, AGG, BND, HYG, LQD and ~40 more from the
            # universe — the most liquid instruments on the board, and the ones a 21-DTE
            # premium screen trades most. For a fund the analogue is assets under management,
            # which yfinance exposes as totalAssets (SPY: $811.9B, verified 2026-10-01).
            try:
                inf = yf.Ticker(s).info
                mc = inf.get("totalAssets") or inf.get("netAssets")
            except Exception:
                mc = None
        if mc is not None:
            cache[s] = mc          # cache SUCCESSES only. Caching a failed lookup as null
                                   # permanently banned that name: 51 nulls accumulated
                                   # including SPY, QQQ, IWM, GLD, TLT, EEM — all missing
                                   # from the universe because one transient yfinance error
                                   # was treated as "market cap unknown forever".
        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(todo)}", flush=True)
            cache_path.write_text(json.dumps(cache))
    cache_path.write_text(json.dumps(cache))
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(bootstrap.DATA_ROOT / "plans" / "universe_screen.txt"))
    ap.add_argument("--cache", default=str(bootstrap.DATA_ROOT / "var" / "cache_marketcap.json"))
    ap.add_argument("--cached-caps-only", action="store_true", help="reuse cached market caps without vendor calls")
    args = ap.parse_args()

    c = db.connect(log=None, universe=True)
    liq = liquidity(c)
    print(f"1. warehouse symbols with {LOOKBACK}-day data : {len(liq):,}")

    s1 = {s: v for s, v in liq.items() if v[0] > MIN_VOL and v[1] > MIN_PX}
    print(f"2. pass vol>{MIN_VOL/1e6:.0f}M and px>${MIN_PX:.0f}      : {len(s1):,}")

    cache = pathlib.Path(args.cache)
    caps = ((json.loads(cache.read_text()) if cache.exists() else {}) if args.cached_caps_only
            else market_caps(sorted(s1), cache))
    if args.cached_caps_only:
        print("  market caps: cached values only; no vendor refresh")
    unknown = {s for s in s1 if not caps.get(s)}
    # UNKNOWN cap is KEPT, which is what the line below has always claimed and what
    # the code did not do: `(caps.get(s) or 0) > MIN_MCAP` gave an unknown a cap of
    # zero, so every name yfinance could not price was dropped by the market-cap gate
    # -- silently, under a message asserting the opposite. ETFs and ADRs are exactly
    # where yfinance reports no marketCap, so the drop landed on a whole asset class.
    s2 = {s: v for s, v in s1.items()
          if s in unknown or (caps.get(s) or 0) > MIN_MCAP}
    print(f"3. pass market cap > ${MIN_MCAP/1e9:.0f}B            : {len(s2):,}"
          f"   ({len(unknown):,} cap UNKNOWN — kept, mostly ETFs where yfinance reports none)")

    # IVR: position of the latest IV in its own stored min/max range, ranked by the
    # same rule the screen uses (compute.iv_rank) — one definition, so the filter's scope
    # and the screen's PASS cannot drift. Expiry-null rows only, per source, never mixed.
    #
    # Read IV by attaching market_history explicitly. The original read `mh`/`mhro`, but
    # this connection only ever attaches `yh` — both queries raised CatalogException, the
    # bare `except: continue` swallowed them, and the filter reported "0 confirmed on IV,
    # 179 pending" as though it were a coverage gap rather than a dead query. It also took
    # the MAX over all history rather than the latest day, which admits stale spikes
    # (META latest 0.464 vs max 0.564).
    ivr, iv_excluded = {}, {}
    try:
        c.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' AS mhiv (READ_ONLY)")
    except Exception as e:
        print(f"  WARNING: iv_history unavailable ({repr(e)[:60]}) — IVR leg skipped")
    try:
        per, iv_excluded = fetch_series(c, table="mhiv.iv_history", symbols=s2)
        ivr = {u: rank_series(rows) for u, rows in per.items()}
    except Exception as e:
        print(f"  WARNING: iv_history read failed ({repr(e)[:60]}) — IVR leg skipped")
    ranked = {u: v["ivr"] for u, v in ivr.items() if v and v["ivr"] is not None}
    have = {s for s in s2 if ranked.get(s, -1.0) >= MIN_IVR}
    # "pending" used to mean only "cannot judge", but the message asserted a specific cause
    # -- "no 60-day series yet" -- that was never tested, and was wrong for every name whose
    # rows exist at per-expiry granularity. Reason is now derived, and the two causes are
    # counted separately because they call for different responses: a short series fills
    # itself in, a per-expiry-only source needs the reader to look.
    pending = {s for s in s2 if s not in ranked}
    short = {s for s in pending if ivr.get(s)}          # has a short, flat or invalid series
    unread = pending - short                            # no rows read at all for this name
    print(f"4. pass IVR >= {MIN_IVR:.0f}                    : {len(have):,}"
          f"   ({len(s2) - len(have) - len(pending):,} ranked below, {len(pending):,} unrankable —"
          f" {len(short):,} short/flat/invalid series, {len(unread):,} no rows read)")
    if iv_excluded:
        print(f"   {len(iv_excluded)} (name, source) pair(s) excluded as per-expiry rows, not a "
              f"daily series: "
              + ", ".join(f"{u}/{s_}" for u, s_ in sorted(iv_excluded)[:6])
              + (" …" if len(iv_excluded) > 6 else ""))

    final = sorted(have | pending)          # keep pending rather than silently dropping
    pathlib.Path(args.out).write_text(
        f"# Screen universe — mcap>${MIN_MCAP/1e9:.0f}B, {LOOKBACK}d avg vol>{MIN_VOL/1e6:.0f}M, "
        f"avg px>${MIN_PX:.0f}, IVR>={MIN_IVR:.0f} (last 252 daily observations, minimum 60)\n"
        f"# Generated {clock.today()} by build_screen_universe.py; IVR uses min/max range\n"
        + ("# Market caps: cached values only\n" if args.cached_caps_only else "") +
        f"# {len(have)} ranked IVR>={MIN_IVR:.0f}, {len(pending)} pending (IV series unrankable)\n"
        + "\n".join(final) + "\n")
    print(f"\nwrote {args.out}: {len(final)} names "
          f"({len(have)} IVR-ranked + {len(pending)} pending)")
    c.close()


if __name__ == "__main__":
    main()
