import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

# ── --help guard ─────────────────────────────────────────────────────────────
# This script WRITES to a database and takes no arguments, so `script.py --help`
# used to execute it in full. Not hypothetical: a 2026-10-05 sweep ran every app
# with --help and rewrote the fills table (via seed_fills.py) and risk_profile.
# A read-only-looking flag must not be a write. Exits before any connection.
from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below, and a
# docstring must be the first statement, so all 33 copies printed "(no docstring)".

"""risk_profile.py — Risk-Navigator-style profile of the COMBINED book (US + China).

Mirrors the RN lens: delta-notional, vega, theta, gamma per position; spot-shock
scenario ladder; breakdowns by broker / ticker / sector / industry / subindustry.
Writes risk_profile_<date>.md and a `risk_profile` table in the DB.

Run: uv run python risk_profile.py
"""
import datetime as dt
import pathlib
import sys

import duckdb

from data import clock  # noqa: E402
from data import db  # noqa: E402
from apps.trade_profile import close_cost  # noqa: E402
from apps.trade_profile import mark_provenance  # noqa: E402

from shared.rates import SHOCKS, FX_CNY as FXCNY, fx_of

# The documented shared connector: it is the one place that knows where trades.duckdb lives.
def main():
    con = db.connect()
    # Columns 16-20 are appended, so every index above them (0-15) keeps its meaning --
    # `agg` and `scenario_pnl` index positionally.
    pos = con.execute("""SELECT broker, underlying, sec_type, strike, call_put, qty, spot,
    delta_units, gamma_units, theta_day, vega_pt, delta_notional_usd, asset_class, sector, industry, subindustry,
    spot_source, spot_class, spot_is_realtime, avg_price, multiplier, expiry, mark, mark_obs,
    mark_source, bid, ask
    FROM positions""").fetchall()

    # WHAT THE OPTION MARKS ARE -- see mark_provenance.py. Index 24, not 23:
    # mark_source is appended AFTER mark_obs, and reading 23 fed the marks in, so the
    # header called a book of live quotes "no live quote".
    # `!= "STOCK"`, not `== "OPT"`: the China legs are FUT_OPT and their marks count
    # too. leg_estimates uses the same rule, so the two reports cannot describe one
    # book with two different numbers.
    mark_srcs = [r[24] for r in pos if r[2] != "STOCK"]

    # WHICH SPOTS ARE NOT REAL-TIME. The user's rule (2026-10-06) is that risk work uses
    # real-time prices by default, in extended hours as well as regular hours. That cannot
    # be enforced here -- this script reads whatever build_positions stored -- but it can
    # be REPORTED, which is the difference between a profile that is known to be current
    # and one that only looks it. `is_realtime` is False for both a stored close and an
    # overnight `last_only` print, and both are the previous session's price wearing
    # today's timestamp.
    stale_spots = sorted({(r[1], r[16] or "?", r[17] or "?")
                          for r in pos if r[6] is not None and not r[18]})

    # `positions` carries the vintage stamped by build_positions.py. Every row this script
    # writes must carry it too: this script reads SNAPSHOT greeks, so what it produces is a
    # profile of the book as of that moment, never of "now". A run two days later over the same
    # position table produces two rows that look like two different market views and are really
    # the same stale book -- the reader has no way to tell without this column.
    def book_vintage(c):
        """Holdings-list vintage — the SAME query capture_risk.py runs, so the column means one
    thing whichever script wrote the row. Missing column (a `positions` table built before
    as_of existed) is a real state, not a crash: report the vintage as unknown."""
        try:
            return c.execute("SELECT max(as_of) FROM positions WHERE qty <> 0").fetchone()[0]
        except duckdb.Error:
            return None


    book_as_of = book_vintage(con)
    if book_as_of:
        age_d = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                 - book_as_of).total_seconds() / 86400
        print(f"book vintage: {book_as_of:%Y-%m-%d %H:%M} UTC ({age_d:.1f} days old)")
        if age_d > 1:
            print(f"  !! {age_d:.1f} days stale -- these are NOT current greeks. "
                  f"Use capture_risk.py for a live profile.")


    def scenario_pnl(p, shock):
        """Approx P&L for a uniform % shock; China legs converted to USD."""
        broker = p[0]
        # Extended unpack: the SELECT appends spot provenance after column 15.
        _, _, _, _, _, _, spot, du, gu, th, v, *_ = p
        if spot is None:
            return 0.0
        dS = spot * shock
        fx = FXCNY if broker == "浙商期货" else 1.0
        return (du * dS + 0.5 * (gu or 0) * dS * dS) / fx


    def agg(rows):
        def usd(v, broker):
            return (v or 0) / (FXCNY if broker == "浙商期货" else 1.0)
        return {
            "delta_usd": sum(r[11] or 0 for r in rows),
            "gross_delta_usd": sum(abs(r[11] or 0) for r in rows),
            "vega_usd": sum(usd(r[10], r[0]) for r in rows),
            "theta_usd": sum(usd(r[9], r[0]) for r in rows),
            "pnl": {s: sum(scenario_pnl(r, s) for r in rows) for s in SHOCKS},
        }


    def fmt(v):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.1f}"


    def table(title, groups):
        lines = [f"\n### {title}", "| Group | Δ notional $ | Vega $/pt | Theta $/day | P&L @ -10% | @ -5% | @ +5% | @ +10% |",
                 "|---|---|---|---|---|---|---|---|"]
        for k, rows in groups:
            a = agg(rows)
            lines.append(f"| {k} | {fmt(a['delta_usd'])} | {fmt(a['vega_usd'])} | {fmt(a['theta_usd'])} | "
                         f"{fmt(a['pnl'][-0.10])} | {fmt(a['pnl'][-0.05])} | {fmt(a['pnl'][0.05])} | {fmt(a['pnl'][0.10])} |")
        return "\n".join(lines)


    def by(key_idx):
        g = {}
        for r in pos:
            g.setdefault(r[key_idx] or "?", []).append(r)
        return sorted(g.items(), key=lambda kv: -abs(agg(kv[1])["delta_usd"]))


    def by_pair(*idxs):
        g = {}
        for r in pos:
            g.setdefault(" / ".join(str(r[i]) for i in idxs), []).append(r)
        return sorted(g.items(), key=lambda kv: -abs(agg(kv[1])["delta_usd"]))


    overall = agg(pos)
    # UTC DATE via clock.today(), not `date.today()` -- eight hours ahead on this box. The
    # note here used to say the opposite, describing what this did BEFORE clock.py was
    # written to fix it; a stale note about a fixed bug tells the reader the filename lies
    # when it does not. See tests/apps/audit/test_report_artifact_clock.py.
    today = clock.today().isoformat()
    # COMPUTED from each row's mark_source; as a fixed sentence it survived the move onto
    # the broker's book and the report called live quotes models.
    vintage = (f"**Book as of {book_as_of:%Y-%m-%d %H:%M} UTC — greeks at the current spot, "
               f"{mark_provenance.sentence(mark_srcs)}.**"
               if book_as_of else "**Book vintage UNKNOWN (positions.as_of is empty).**")
    if stale_spots:
        # Count UNDERLYINGS, not rows of the set: the key carries source and class, so one
        # underlying appearing under two of them would inflate the count past the total.
        n_stale = len({u for u, _, _ in stale_spots})
        n_all = len({r[1] for r in pos})
        warn = (f"**⚠️ {n_stale} of {n_all} underlyings are NOT "
                f"priced in real time** — every greek below is computed at a spot that is not "
                f"a live quote. `last_only` is a shut exchange, which is the normal state out "
                f"of hours; `broker_snapshot` means no quote came back at all:")
        detail = " · ".join(f"`{u}` ({src}, {cls})" for u, src, cls in stale_spots)
        print(f"\n!! NOT real-time: {detail}\n!! `last_only` = shut exchange (normal out of "
              "hours); `broker_snapshot` = NO quote came back. Greeks scale with the spot.\n")
    else:
        warn, detail = None, None

    out = [f"# Combined risk profile — {today}",
           f"\nPositions: {len(pos)} legs across brokers: {sorted({r[0] for r in pos})}",
           f"\n{vintage} Computed from the `positions` table, so this describes the holdings left by "
           f"the last `build_positions.py` run — for a live picture use `capture_risk.py`."]
    if warn:
        out.append(f"\n{warn}\n{detail}")
    _mp = mark_provenance.detail(mark_srcs)
    if _mp:
        out.append(f"\n*{_mp}.*")
    out += close_cost.from_rows(pos, fx_of)   # the mid is not what closing costs
    out += [
           "\n*Greeks: US by Black-Scholes, ESTIMATED at the live underlying spot from the IV "
           "each leg was struck at (the previous close for a last-session mark / the fill for "
           "a leg opened since), so the IV is the market's and the price is today's; China "
           "from broker 快期 "
           "snapshot. Scenarios = uniform % shock on every underlying, 0-day horizon, IV unchanged. "
           f"USD; CNY at {FXCNY}.*",
           f"\n## Overall\n- **Delta notional: ${fmt(overall['delta_usd'])}** (gross ${fmt(overall['gross_delta_usd'])})",
           f"- **Vega: ${fmt(overall['vega_usd'])} per vol pt** · **Theta: ${fmt(overall['theta_usd'])}/day**",
           "\n| Shock | " + " | ".join(f"{s:+.0%}" for s in SHOCKS) + " |",
           "|---|" + "---|" * len(SHOCKS),
           "| P&L $ | " + " | ".join(fmt(overall["pnl"][s]) for s in SHOCKS) + " |"]

    # ── legs: profit and estimate ────────────────────────────────────────────────────────
    #
    # The headline tables aggregate, and an aggregate cannot be acted on: an order goes to
    # one broker for one contract, and the >=50% close rule is read per leg. Until now the
    # per-leg profit existed only in this conversation, recomputed by hand each time -- which
    # is how the China legs went missing from every leg table given for a whole session
    # (the ad-hoc queries filtered sec_type='OPT' and silently dropped 'FUT_OPT').
    #
    # "Est. mark" is the price at TODAY'S spot: a live book where the chain had one, a
    # Black-Scholes estimate at the live spot where it did not (build_positions says which
    # per leg). Profit is measured entry -> that mark, which is the number the close rule
    # reads. Multiplier comes from the row, so a CZCE leg at 10 is not scored as a 100.
    def leg_lines():
        rows = []
        for r in pos:
            entry, mult, mark, obs, qty = r[19], r[20] or 100, r[22], r[23], r[5]
            if entry is None or mark is None:
                continue
            obs = mark if obs is None else obs
            fx = FXCNY if r[0] == "浙商期货" else 1.0

            def pct_of(m):
                return (entry - m) / entry * 100 if qty < 0 else (m - entry) / entry * 100

            pnl = ((entry - mark) if qty < 0 else (mark - entry)) * abs(qty) * mult / fx
            pct_obs, pct_est = pct_of(obs), pct_of(mark)
            name = (f"{r[1]} {r[21]:%m-%d} " if r[21] else f"{r[1]} ") + \
                   (f"{r[3]:g}{r[4]}" if r[2] != "STOCK" else "STOCK")
            flag = ""
            if qty < 0 and pct_est >= 50:
                flag = " **<= 50% - CLOSE**"
            elif qty < 0 and pct_est >= 40:
                flag = " <- near 50%"
            # TWO P&L PERCENTAGES, because they answer different questions. `P&L %` is
            # measured to the OBSERVED mark -- what the contract actually last traded at,
            # which outside regular hours is the previous session's close. `Est. P&L %` is
            # measured to the mark repriced at TODAY'S spot. The gap between them is exactly
            # how much of the leg's result is the underlying having moved since that trade,
            # and how much is real. On a stale observation the second is the honest one, and
            # showing only the first is how a book reads calm while the market has moved on.
            rows.append((pct_est, f"| {r[0]} | {name} | {qty:g} | {entry:,.3f} | {obs:,.3f} | "
                                  f"{pct_obs:+.1f}% | {mark:,.3f} | {pct_est:+.1f}% | "
                                  f"{fmt(pnl)} |{flag}"))
        return [t for _, t in sorted(rows, key=lambda x: -x[0])]

    out.append("\n## Legs — profit and estimate\n"
               "*`Mark` is the price the source gave (outside regular hours, the previous "
               "session's close); `Est. mark` is that leg repriced at the current spot. "
               "**P&L %** is measured to the observed mark, **Est. P&L %** to the estimated "
               "one — the gap is the underlying's move since the observation. `<= 50% - "
               "CLOSE` marks a short leg that has captured half its credit.*\n"
               "\n| Broker | Leg | Qty | Entry | Mark | P&L % | Est. mark | Est. P&L % | "
               "Est. P&L $ | |"
               "\n|---|---|---|---|---|---|---|---|---|---|")
    out.extend(leg_lines())

    out.append(table("By broker", by(0)))
    out.append(table("By ticker", by(1)))
    out.append(table("By asset class", by(12)))
    out.append(table("By sector / industry", by_pair(13, 14)))
    out.append(table("By subindustry", by(15)))

    report = "\n".join(out)
    path = bootstrap.ROOT / "reports" / f"risk_profile_{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")

    # NOTE: this used to DROP the table, which made risk_profile overwrite-only — the trade
    # log could never answer "what was the risk at 09:52". It now APPENDS, and every row of one
    # run carries ONE ts_utc (stamped once, below), so a run is one timestamp and a re-run is a
    # new, distinct capture. Nothing here deletes, on purpose; the log keeps both.
    con.execute("""CREATE TABLE IF NOT EXISTS risk_profile (group_type TEXT, group_key TEXT, delta_usd DOUBLE,
    gross_delta_usd DOUBLE, vega_usd DOUBLE, theta_usd DOUBLE, pnl_m15 DOUBLE, pnl_m10 DOUBLE,
    pnl_m5 DOUBLE, pnl_0 DOUBLE, pnl_p5 DOUBLE, pnl_p10 DOUBLE, pnl_p15 DOUBLE,
    ts_utc TIMESTAMP, source TEXT, book_as_of TIMESTAMP)""")
    con.execute("ALTER TABLE risk_profile ADD COLUMN IF NOT EXISTS book_as_of TIMESTAMP")
    # ONE timestamp for the whole run: evaluated per row, every row got its own ts_utc, so
    # `WHERE ts_utc = (SELECT max(ts_utc) ...)` returned a single arbitrary group instead of
    # the run. One run must be addressable by one timestamp.
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for gt, groups in [("broker", by(0)), ("ticker", by(1)), ("asset_class", by(12)),
                       ("sector_industry", by_pair(13, 14)), ("subindustry", by(15))]:
        for k, rows in groups:
            a = agg(rows)
            # Named columns: positional VALUES breaks silently when a column is added.
            con.execute("""INSERT INTO risk_profile
                         (group_type, group_key, delta_usd, gross_delta_usd, vega_usd,
                          theta_usd, pnl_m15, pnl_m10, pnl_m5, pnl_0, pnl_p5, pnl_p10,
                          pnl_p15, ts_utc, source, book_as_of)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [gt, k, a["delta_usd"], a["gross_delta_usd"], a["vega_usd"], a["theta_usd"],
                         a["pnl"][-0.15], a["pnl"][-0.10], a["pnl"][-0.05], a["pnl"][0.0],
                         a["pnl"][0.05], a["pnl"][0.10], a["pnl"][0.15],
                         now, "risk_profile_py", book_as_of])
    con.close()
    print(report)
    print(f"\nwritten: {path}")


# Guard added by the data/application split: unguarded, importing this module ran it.
if __name__ == "__main__":
    main()
