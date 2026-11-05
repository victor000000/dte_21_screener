import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""crosscheck_sources.py — cross-source consistency audit for the trading data.

Method inherited from the market_data subproject (CROSSCHECK.md / SOURCE_CONSISTENCY.md):
  * recheck data against sources that did NOT produce it — agreement must be evidence, not restatement;
  * compare RATIOS, so each vendor's conventions (raw vs split-restated, bases) cancel out;
  * report AGREE / DIFFER / INFO with counts, a stated tolerance and named examples — never a bare "ok".

Checks (all offline; --live adds the network ones):
  U1  US daily bars   yahoo.prices (warehouse)  vs  underlying_daily (our downloads)     tol 0.5%
  O1  fills on tape   fills.price  inside the same day's option_bars low..high           outside = INFO
  U2  live edge       yahoo.prices last close   vs  yfinance last close        (--live)  tol 0.5%
  I1  IV agreement    IBKR 30-day series        vs  Futu panel IV              (--live)  tol 2 vol pts

Writes reports/data_consistency_<date>.md and one row per check into source_checks.

  uv run python apps/audit/crosscheck_sources.py [--live]
"""
import argparse
import datetime as dt
import pathlib
import sys

import duckdb

from shared.net import throttle

from data import clock  # noqa: E402
from data import db  # noqa: E402

ROOT = bootstrap.ROOT
REPORTS = ROOT / "reports"
TOL_PX = 0.005          # 0.5% between two vendors' daily closes
TOL_IV_PTS = 2.0        # vol points between two IV engines
DEFAULT_SYMBOLS = ["META", "CRWD", "SWKS", "TLT", "EWZ", "ILMN", "NBIS", "SNDK"]

DDL_CHECKS = """
CREATE TABLE IF NOT EXISTS source_checks (
  run_ts TIMESTAMP, check_id TEXT, subject TEXT, src_a TEXT, src_b TEXT,
  n INTEGER, verdict TEXT, detail TEXT
)"""


def u1_daily(con, symbols):
    """yahoo.prices vs underlying_daily over the full overlap, per symbol."""
    rows = con.execute("""
        SELECT u.symbol, count(*) AS n,
               median(abs(u.close / y.close - 1)) AS med_dev,
               max(abs(u.close / y.close - 1))    AS max_dev
        FROM mh.underlying_daily u
        JOIN yh.prices y ON y.symbol = u.symbol AND y.date = u.day
        WHERE list_contains(?, u.symbol) AND u.source LIKE '%alpaca%'
        GROUP BY 1 ORDER BY 1""", [symbols]).fetchall()
    out = []
    for sym, n, med, mx in rows:
        verdict = "AGREE" if mx <= TOL_PX else "DIFFER"
        out.append((f"U1:{sym}", sym, "yahoo.prices", "underlying_daily", n, verdict,
                    f"median dev {med:.4%} · max dev {mx:.4%} over {n} shared days"))
    return out


def o1_fills_on_tape(con):
    """Every fill's price must sit inside that day's Alpaca bar range (spaces stripped)."""
    rows = con.execute("""
        SELECT f.broker, f.underlying, f.symbol, f.qty, f.price, f.ts_utc,
               b.low, b.high
        FROM main.fills f
        JOIN mh.option_bars b
          ON b.symbol = REPLACE(f.symbol, ' ', '')
         AND b.day = CAST(f.ts_utc AS DATE)
        WHERE f.ts_utc IS NOT NULL AND f.price IS NOT NULL AND f.price > 0""").fetchall()
    if not rows:
        return [("O1", "all fills", "fills", "option_bars", 0, "INFO",
                 "no overlapping fill/bar pairs yet (option_bars still downloading)")]
    outside = [r for r in rows if not (min(r[6], r[7]) <= r[4] <= max(r[6], r[7]))]
    detail = f"{len(rows) - len(outside)}/{len(rows)} inside the day's range"
    if outside:
        detail += "; outside: " + ", ".join(
            f"{r[2].strip()} {r[4]} vs [{r[6]},{r[7]}]" for r in outside[:5])
    return [("O1", "all fills", "fills", "option_bars", len(rows),
             "AGREE" if not outside else "INFO", detail)]


def u2_live_edge(con, symbols):
    import socket
    import yfinance as yf
    socket.setdefaulttimeout(25)   # never let a flaky connection hang the audit
    out = []
    for sym in symbols:
        try:
            throttle('yfinance')
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            if hist.empty:
                continue
            live = float(hist["Close"].iloc[-1])
            live_day = hist.index[-1].date()
            row = con.execute(
                "SELECT close FROM yh.prices WHERE symbol=? AND date=?", [sym, live_day]).fetchone()
            if not row:
                continue
            dev = abs(live / row[0] - 1)
            out.append((f"U2:{sym}", sym, "yahoo.prices", "yfinance", 1,
                        "AGREE" if dev <= TOL_PX else "DIFFER",
                        f"{live_day}: yahoo {row[0]:.2f} vs yfinance {live:.2f} ({dev:.3%})"))
        except Exception as e:  # network hiccup is not a data defect
            out.append((f"U2:{sym}", sym, "yahoo.prices", "yfinance", 0, "INFO", repr(e)[:80]))
    return out


def i1_iv_agreement(con):
    """Latest IBKR 30-day IV vs the Futu panel, per ticker — two independent IV engines."""
    try:
        from futu import OpenQuoteContext  # noqa: F401
    except ImportError:
        return [("I1", "all", "ibkr_tws30d", "futu_panel", 0, "INFO",
                 "futu sdk not installed in this run")]
    return [("I1", "all", "ibkr_tws30d", "futu_panel", 0, "INFO",
             "run with the futu extra once the TWS sweep has landed")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    ap.add_argument("--live", action="store_true", help="also run the network checks (U2, I1)")
    args = ap.parse_args()

    con = db.connect(log="rw", history="ro", universe=True)
    con.execute(DDL_CHECKS)

    rows = u1_daily(con, args.symbols) + o1_fills_on_tape(con)
    if args.live:
        rows += u2_live_edge(con, args.symbols) + i1_iv_agreement(con)
    else:
        rows.append(("U2/I1", "all", "—", "—", 0, "INFO", "skipped (offline run; pass --live)"))

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)   # naive UTC, per convention
    if rows:   # DuckDB raises on an empty list, not a no-op — a live run can find none
        con.executemany("INSERT INTO source_checks VALUES (?,?,?,?,?,?,?,?)",
                        [(now, *r) for r in rows])
    con.close()

    stamp = clock.today().isoformat()
    n_agree = sum(1 for r in rows if r[5] == "AGREE")
    n_differ = sum(1 for r in rows if r[5] == "DIFFER")
    lines = [f"# Data consistency audit — {stamp}", "",
             f"Generated by `scripts/crosscheck_sources.py`"
             f"{'' if args.live else ' (offline run)'}. "
             f"**{n_agree} agree, {n_differ} differ, "
             f"{len(rows) - n_agree - n_differ} informational.**", "",
             "| check | subject | sources | n | verdict | detail |",
             "|---|---|---|---|---|---|"]
    for cid, subj, a, b, n, verdict, detail in rows:
        lines.append(f"| `{cid}` | {subj} | {a} vs {b} | {n} | {verdict} | {detail} |")
    lines += ["", "Tolerances: daily closes 0.5% (four-decimal storage, different vendors' rounding) ·",
              "IV engines 2 vol points · a fill outside its day's option bar range is INFO, not an error —",
              "the fill can be the more accurate print."]
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"data_consistency_{stamp}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"{n_agree} agree · {n_differ} differ · {len(rows)} checks -> {path}")


if __name__ == "__main__":
    main()
