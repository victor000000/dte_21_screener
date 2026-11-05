import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

# ── --help guard ─────────────────────────────────────────────────────────────
# No argparse here, so `script.py --help` used to execute this script in full.
# That is not hypothetical: a 2026-10-05 sweep ran every app with --help and
# rewrote `fills`, `risk_profile` and `positions`. The write does not have to be
# in THIS file either -- live_risk_profile.py orchestrates build_positions and
# risk_profile through subprocess, so "does it INSERT?" is the wrong test. The
# rule is simply that a script with no argument parser must not run on --help.
from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below, and a
# docstring must be the first statement, so all 33 copies printed "(no docstring)".

"""trade_log_analytics.py — the trade log's analytics view (record database only).

Answers, from what is actually recorded:
  * realized P/L overall, by month, by underlying, by broker — and the win rate on closes
  * the IV we sold vs the IV we bought (fills carry fill-time IV), i.e. the vol edge actually
    captured, per underlying
  * fees actually paid, per broker (settlement-corrected where 结算单 provided them)
  * the open book marked to the last build: unrealized P/L, theta/day, vega, and the share
    of the book by underlying

Everything is computed from `fills` / `positions`; a metric whose inputs are missing prints
n/a rather than 0. Hold time is reported only where a closing fill carries its realized P/L
(the FIFO pass writes it) — otherwise n/a, because the pairing is not stored.

    uv run python apps/trade_log/trade_log_analytics.py
"""
import datetime as dt
from data import clock
import pathlib

import duckdb

ROOT = bootstrap.ROOT
DB = bootstrap.DATA_ROOT / "trades.duckdb"


def f(v, n=0):
    return "n/a" if v is None else f"{v:,.{n}f}"


def main():
    con = duckdb.connect(str(DB), read_only=True)
    today = clock.today()
    L = [f"# Trade log analytics — {today}", "",
         "Computed from `fills` and `positions`. n/a means the input is not recorded.", ""]

    tot_fills = con.execute("SELECT count(*) FROM fills").fetchone()[0]
    n_closed = con.execute("SELECT count(*) FROM fills WHERE realized_pnl IS NOT NULL").fetchone()[0]
    wins = con.execute("SELECT count(*) FROM fills WHERE realized_pnl > 0").fetchone()[0]
    # PER CURRENCY. The book holds real CNY rows (broker 浙商期货, fills.currency='CNY'),
    # and summing them with USD produced a single meaningless number: the headline
    # realized was -544.37, which is USD +21,645.63 plus CNY -22,190 added together.
    # Fees, the monthly table and the open-book greeks all had the same defect.
    ccy_rows = con.execute("""
        SELECT COALESCE(currency,'?') AS ccy, count(*), sum(fee),
               sum(realized_pnl), count(realized_pnl)
        FROM fills GROUP BY 1 ORDER BY 1""").fetchall()
    parts = []
    for ccy, n, fee, real, ncl in ccy_rows:
        seg = f"{ccy} — realized **{f(real)}**, fees **{f(fee, 2)}** ({ncl} closed of {n})"
        parts.append(seg)
    L += ["## Realized", "",
          f"- fills **{tot_fills}** · closing fills with realized P/L **{n_closed}**",
          "- **by currency** (never summed across — CNY and USD are different units):"]
    L += [f"  - {x}" for x in parts]
    L += ["- win rate on closes: " +
          (f"**{wins / n_closed * 100:.0f}%** ({wins}/{n_closed})" if n_closed else "n/a"), ""]

    cov = con.execute("""
        SELECT source, COALESCE(currency,'?') AS ccy, count(*), sum(realized_pnl)
        FROM fills WHERE realized_pnl IS NOT NULL
        GROUP BY 1, 2 ORDER BY 2, 3 DESC""").fetchall()
    meaning = {
        "schwab_transactions": "FIFO-reconciled from the full transaction history — complete for Schwab",
        "journal": "IBKR closes as written in the user's journal — partial coverage by nature",
        "live_record_cn": "China closes from the settlement statements (结算单)",
    }
    # PER CURRENCY, like every other money table here. `journal` carried both: 13 CNY
    # closes (-23,940) and 3 USD ones (+309.63), and summing them printed -23,630.37 --
    # a number in no currency at all, and the one a reader would quote as the journal's
    # contribution. The two are ~77x apart at FX, so neither dominates the other.
    L += ["## What the realized total is made of (coverage differs by broker)", "",
          "| source | currency | closes | realized | meaning |", "|---|---|---|---|---|"]
    for s, ccy, n, r in cov:
        L.append(f"| {s} | {ccy} | {n} | {f(r)} | {meaning.get(s, '—')} |")
    L += ["", "A negative total here means the recorded IBKR journal entries outweigh the "
              "reconciled Schwab closes — it is coverage, not a performance verdict. "
              "Per-broker realized P/L should be read only where coverage is complete.", ""]

    # `count(*)` was labelled "closing fills" but counted every fill: Sept 2026 showed
    # 141 where only 31 rows carry a realized P/L. Now counts closes, and currency is a
    # column because summing CNY and USD in a month is the same error as at the top.
    L += ["## By month", "",
          "| month | currency | closing fills | realized | fees |", "|---|---|---|---|---|"]
    for m, ccy, n, r, fee in con.execute("""
            SELECT strftime(ts_utc, '%Y-%m') AS m, COALESCE(currency,'?') AS ccy,
                   count(realized_pnl), sum(realized_pnl), sum(fee)
            FROM fills WHERE ts_utc IS NOT NULL
            GROUP BY 1, 2 ORDER BY 1 DESC, 2 LIMIT 24""").fetchall():
        L.append(f"| {m} | {ccy} | {n} | {f(r)} | {f(fee, 2)} |")
    L.append("")

    # Currency is a COLUMN and the sort is WITHIN it. Ordering by sum(realized_pnl) across
    # both put MO2610-C-7900 at 11,440 CNY next to MU at 14,445 USD, as though the first
    # were the bigger number -- 11,440 CNY is about $1,604. The ranking was meaningless
    # and the top of the table was the place it misled most.
    L += ["## By underlying", "",
          "| underlying | ccy | fills | realized | win rate | avg IV sold | avg IV bought |",
          "|---|---|---|---|---|---|---|"]
    for u, ccy, n, r, w, ncl, ivs, ivb in con.execute("""
            SELECT underlying, COALESCE(currency,'?') AS ccy, count(*), sum(realized_pnl),
                   sum(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END),
                   count(realized_pnl),
                   avg(CASE WHEN action='SELL' THEN iv_at_fill END),
                   avg(CASE WHEN action='BUY'  THEN iv_at_fill END)
            FROM fills GROUP BY 1, 2 ORDER BY 2, sum(realized_pnl) DESC NULLS LAST""").fetchall():
        wr = f"{w / ncl * 100:.0f}%" if ncl else "n/a"
        L.append(f"| {u} | {ccy} | {n} | {f(r)} | {wr} | "
                 f"{'n/a' if ivs is None else f'{ivs * 100:.1f}%'} | "
                 f"{'n/a' if ivb is None else f'{ivb * 100:.1f}%'} |")
    L.append("")

    # 浙商期货 bills in CNY, so its fee and realized columns were not comparable with the
    # USD brokers' -- two units in one column, in three of four rows.
    L += ["## By broker", "", "| broker | ccy | fills | fees | realized |", "|---|---|---|---|---|"]
    for b, ccy, n, fee, r in con.execute("""
            SELECT broker, COALESCE(currency,'?') AS ccy, count(*), sum(fee), sum(realized_pnl)
            FROM fills GROUP BY 1, 2 ORDER BY 2, 3 DESC""").fetchall():
        L.append(f"| {b} | {ccy} | {n} | {f(fee, 2)} | {f(r)} |")
    L.append("")

    # ---- open book, marked to the last position build
    # `qty <> 0` matters: a closed leg left in the table with stale greeks would still
    # contribute to these totals. And the currency is carried through, because
    # build_positions FX-converts only delta_notional_usd for the CN account --
    # theta_day and vega_pt are raw CNY, so summing them into a "$/day" figure added
    # yen to dollars (the CN account alone is ~¥694/day of the reported 1,222).
    rows = con.execute("""
        SELECT underlying,
               CASE WHEN broker='浙商期货' THEN 'CNY' ELSE 'USD' END AS ccy,
               sum(qty) AS qty, sum(theta_day) AS theta,
               sum(vega_pt) AS vega, sum(delta_notional_usd) AS dn,
               sum(CASE WHEN qty < 0 THEN (avg_price - mark) * (-qty) * COALESCE(multiplier,100)
                        ELSE (mark - avg_price) * qty * COALESCE(multiplier,100) END) AS upl
        FROM positions WHERE qty <> 0 GROUP BY 1, 2 ORDER BY upl DESC NULLS LAST""").fetchall()
    tot = {}
    for _u, ccy, _q, th, v, _dn, up in rows:
        d = tot.setdefault(ccy, [0.0, 0.0, 0.0])
        d[0] += th or 0; d[1] += v or 0; d[2] += up or 0
    t_theta = sum(v[0] for v in tot.values()); t_vega = sum(v[1] for v in tot.values())
    t_upl = sum(v[2] for v in tot.values())
    L += ["## Open book (last build marks)", "",
          "- **by currency** (CN theta/vega are CNY; build_positions FX-converts only "
          "delta_notional_usd, so these are NOT convertible by summing):"]
    for ccy, (th, v, up) in sorted(tot.items()):
        L.append(f"  - {ccy} — unrealized **{f(up)}** · theta **{f(th)}/day** · vega **{f(v)}/vol-pt**")
    L += ["", "| underlying | ccy | net qty | unrealized | theta/day | vega |",
          "|---|---|---|---|---|---|"]
    for u, ccy, qty, theta, vega, dn, upl in rows:
        L.append(f"| {u} | {ccy} | {f(qty)} | {f(upl)} | {f(theta)} | {f(vega, 1)} |")
    L.append("")

    out = ROOT / "reports" / f"trade_log_analytics_{today}.md"
    out.write_text("\n".join(L) + "\n")
    con.close()
    print(f"analytics -> {out}")
    # Per currency, matching the report. A single "realized" here was the same
    # defect as the body: CNY and USD added together.
    print("  realized by currency: " + " · ".join(
        f"{ccy} {f(real)} (fees {f(fee, 2)})" for ccy, _n, fee, real, _ncl in ccy_rows))
    print("  open book by currency: " + " · ".join(
        f"{c} upl {f(v[2])} theta {f(v[0])}/day vega {f(v[1], 1)}"
        for c, v in sorted(tot.items())))


if __name__ == "__main__":
    main()
