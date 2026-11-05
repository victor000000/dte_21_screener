import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""fill_leg_strikes.py — fetch bars for the LISTED strikes the screen's legs need, and nothing else.

Why this exists, measured 2026-10-05:
  `download_option_bars.py --dense` builds its strike list from a ±30% grid in 1% steps.
  That grid lands on strikes that are not listed: ARM Nov-20 was asked for 61 strikes and
  returned 0 bars, twice, on every live expiry — while its real chain has 78 strikes in
  2.5/5-point increments. The grid also MISSES the ladder around the money, which is where
  the strategy trades: MSFT's stored Nov-20 puts run 410..455 then jump to 525, and the
  0.19Δ put sits at ~460, inside that hole. Result: IVR ranks fine but 115 of 194 screen
  names came back NO-LEG.

So this asks Alpaca the question the grid was guessing at — `GET /v2/options/contracts`
returns the LISTED contracts per expiry — keeps the ones inside the Δ band the strategy
trades, subtracts what `option_bars` already holds (per symbol, so nothing is re-fetched),
and requests the remainder. One contracts call + one bars call per name, ~2 requests.

Output goes to a staging DB (default staging/alpaca_legs.duckdb) in the same shape as every
other downloader, so `merge_staging.py` folds it in; re-running is idempotent because the
"have" set is re-read from staging UNION merged.

    uv run python apps/screener/fill_leg_strikes.py \
        [--universe plans/universe_screen.txt] [--expiry 2026-11-20] [--workers 4]
"""
import argparse
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import duckdb

ROOT = bootstrap.ROOT
SEC = json.loads((bootstrap.DATA_ROOT / "secrets" / "alpaca.json").read_text())
HDR = {"APCA-API-KEY-ID": SEC["key_id"], "APCA-API-SECRET-KEY": SEC["secret"]}
SRC = "alpaca"
from shared.rates import R_US as R
DELTA_LO, DELTA_HI = 0.12, 0.30      # wider than the 0.16-0.22 trade band so the picker has
                                     # neighbours to choose from as spot moves
BAR_BATCH = 100                      # symbols per /v1beta1/options/bars call
CONTRACTS = "https://paper-api.alpaca.markets/v2/options/contracts"
BARS = "https://data.alpaca.markets/v1beta1/options/bars"

from shared.net import retry, throttle  # noqa: E402


def get(url):
    def _once():
        throttle("alpaca")
        r = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30)
        return json.loads(r.read())
    return retry(_once, what=url[:90])


def listed_contracts(underlying, expiry):
    """Every contract Alpaca lists for this underlying+expiry, paginated."""
    out, token = [], None
    while True:
        q = {"underlying_symbols": underlying, "expiration_date": expiry.isoformat(),
             "limit": "10000"}
        if token:
            q["page_token"] = token
        d = get(f"{CONTRACTS}?{urllib.parse.urlencode(q)}")
        out.extend(d.get("option_contracts") or [])
        token = d.get("next_page_token")
        if not token:
            return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="plans/universe_screen.txt")
    ap.add_argument("--expiry", default="2026-11-20")
    ap.add_argument("--staging", default="alpaca_legs")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--band", nargs=2, type=float, default=[DELTA_LO, DELTA_HI],
                    metavar=("LO", "HI"),
                    help="absolute-delta window to fetch; widen it for names whose own "
                         "0.19Δ strike the screener computes just outside the trade band")
    args = ap.parse_args()
    lo, hi = args.band
    expiry = dt.date.fromisoformat(args.expiry)
    today = dt.date.today()
    T = max((expiry - today).days, 1) / 365.0

    tickers = [l.strip().upper() for l in (bootstrap.DATA_ROOT / args.universe).read_text().splitlines()
               if l.strip() and not l.startswith("#")]

    st_path = bootstrap.DATA_ROOT / "staging" / f"{args.staging}.duckdb"
    con = duckdb.connect(str(st_path))
    con.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_history.duckdb'}' AS mh (READ_ONLY)")
    con.execute(f"ATTACH '{bootstrap.DATA_ROOT / 'market_data' / 'yahoo.duckdb'}' AS yh (READ_ONLY)")
    con.execute("""CREATE TABLE IF NOT EXISTS option_bars (
        source TEXT, symbol TEXT, underlying TEXT, expiry DATE, strike DOUBLE, call_put TEXT,
        day DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
        vwap DOUBLE, PRIMARY KEY (source, symbol, day))""")

    # spot: last warehouse close at or before the expiry-45d anchor, matching the
    # downloader's convention; a name with no such row falls back to its latest close.
    anchor = expiry - dt.timedelta(days=45)
    spots = dict(con.execute("""
        SELECT symbol, close FROM (
            SELECT symbol, close, date, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) rn
            FROM yh.prices WHERE date <= ? AND close > 0 AND symbol IN (SELECT unnest(?)))
        WHERE rn = 1""", [anchor, tickers]).fetchall())
    atm = dict(con.execute("""
        SELECT underlying, atm_iv FROM (
            SELECT underlying, atm_iv, row_number() OVER (PARTITION BY underlying ORDER BY day DESC) rn
            FROM mh.iv_history WHERE expiry IS NULL AND atm_iv IS NOT NULL
              AND underlying IN (SELECT unnest(?)))
        WHERE rn = 1""", [tickers]).fetchall())
    have = {}
    for u, s in con.execute("""SELECT underlying, symbol FROM mh.option_bars WHERE expiry=?
                               UNION SELECT underlying, symbol FROM option_bars WHERE expiry=?""",
                            [expiry, expiry]).fetchall():
        have.setdefault(u, set()).add(s)

    from compute import bs

    def plan_one(tk):
        """One name's listed-contract call + delta filter. Threaded: this phase was
        sequential, and at ~0.3-0.5 s of latency per call it, not the gate, set the wall
        clock for a 194-name universe (the gate allows 3.2/s; one thread asked for ~2/s
        of that and spent the rest of each second waiting on the wire)."""
        S = spots.get(tk)
        if not S:
            return None
        iv = atm.get(tk) or 0.45
        try:
            cs = listed_contracts(tk, expiry)
        except Exception as e:
            print(f"  {tk}: contracts FAILED (not recorded) {repr(e)[:50]}")
            return None
        held = have.get(tk, set())
        miss = []
        for c in cs:
            K = float(c["strike_price"])
            d = bs.bs_delta(S, K, T, R, iv, c["type"] == "call")
            if d and lo <= abs(d) <= hi and c["symbol"] not in held:
                miss.append(c["symbol"])
        return (tk, S, miss)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        plan = [r for r in ex.map(plan_one, tickers) if r]

    print(f"plan: {len(plan)} names, {sum(len(m) for _, _, m in plan):,} symbols to fetch "
          f"(band Δ {lo}-{hi}, expiry {expiry})")

    def fetch(item):
        tk, S, miss = item
        got, start = [], expiry - dt.timedelta(days=540)
        for i in range(0, len(miss), BAR_BATCH):
            batch = miss[i:i + BAR_BATCH]
            try:
                out, token = {}, None
                while True:
                    url = (f"{BARS}?symbols={','.join(batch)}&timeframe=1Day"
                           f"&start={start.isoformat()}&limit=10000")
                    if token:
                        url += f"&page_token={token}"
                    r = get(url)
                    for s_, bs_ in (r.get("bars") or {}).items():
                        out.setdefault(s_, []).extend(bs_)
                    token = r.get("next_page_token")
                    if not token:
                        break
                for s, bs_ in out.items():
                    cp = s[-9]
                    K = int(s[-8:]) / 1000
                    for b in bs_:
                        got.append([SRC, s, tk, expiry, K, cp, b["t"][:10], b["o"], b["h"],
                                    b["l"], b["c"], b["v"], b.get("vw")])
            except Exception as e:
                return tk, None, f"{repr(e)[:50]}"
        return tk, got, None

    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for tk, got, err in ex.map(fetch, plan):
            if err:
                failed += 1
                print(f"  {tk}: FAILED (not recorded) {err}")
                continue
            rows.extend(got)

    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        if chunk:   # DuckDB raises on an empty list, not a no-op
            con.executemany("INSERT OR REPLACE INTO option_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            chunk)
    con.close()

    by_tk = {}
    for r in rows:
        by_tk[r[2]] = by_tk.get(r[2], 0) + 1
    empty = [t for t, _s, m in plan if m and t not in by_tk]
    print(f"wrote {len(rows):,} bars into {st_path.name} for {len(by_tk)} names; "
          f"{failed} failed; {len(empty)} requested-but-empty")
    if empty:
        print("  empty (strikes listed but no traded bars):", " ".join(sorted(empty)[:20]),
              "..." if len(empty) > 20 else "")
    print(f"\nnext: uv run --no-project --with duckdb python scripts/merge_staging.py")


if __name__ == "__main__":
    main()
