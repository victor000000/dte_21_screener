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

"""capture_risk.py — capture the LIVE risk profile of the book into trades.duckdb.

Why this exists: `risk_profile.py` reads the `positions` table, whose marks are whatever the
last `build_positions.py` left behind (9/29 as of today) — so it answers "what was the risk",
not "what is the risk". It also used to DROP the table on every run, so nothing was ever
recoverable. This captures the *live* picture and APPENDS it, stamped, so the trade log can
answer "what did the risk look like at 09:52 on Oct 1" months from now.

Everything is computed from live marks, with greeks from our own bs.py rather than a vendor
field (yfinance's `impliedVolatility` returned 6.3% on META 850C today — worthless).

    uv run python apps/trade_profile/capture_risk.py
"""
import datetime as dt
import pathlib
import sys

from ib_async import IB, Option, Stock

from compute import bs  # noqa: E402
from data import db  # noqa: E402
from datasources import ibmarks  # noqa: E402
from datasources import tws  # noqa: E402

EXPIRY_CN = dt.date(2026, 12, 11)
from shared.rates import R_US, R_CN, FX_CNY, SHOCKS

# CN MARKS cannot be pulled live from this box; the CZCE daily file is the last real print
# (CN market is closed Oct 1-7). Only the marks live here, keyed by (strike, call_put):
# WHICH legs exist, their qty, entry and broker come from `positions`, so a closed leg
# cannot keep pricing itself from a stale constant, and a leg the book has but this table
# doesn't is reported instead of silently missing from the totals.
# (S, settle, IV, exchange delta from chain_snapshots source='czce_daily_file_20260930'.)
CN_MARKS = {(2650.0, "P"): (2972.0, 81.50, 0.3892, -0.2473),
            (3350.0, "C"): (2972.0, 66.50, 0.3842, +0.2433)}


def main():
    con = db.connect(log="ro")     # read phase: cannot write, and closes before the TWS work
    rows = con.execute("""
        SELECT account, broker, underlying, strike, call_put, qty, avg_price,
               COALESCE(multiplier,100), COALESCE(asset_class,'Equity'),
               COALESCE(sector,'-'), COALESCE(industry,'-'), COALESCE(subindustry,'-'),
               sec_type, expiry, spot
        FROM positions WHERE strike IS NOT NULL AND qty <> 0
    """).fetchall()
    # Stock/ETF legs carry no strike and no greeks: ALL of their risk is delta = qty x spot.
    # Leaving them out dropped 6 of the book's 26 legs -- and every one of the ~$12.5k of
    # delta notional they carry -- from every capture row ever written.
    cash = con.execute("""
        SELECT account, broker, underlying, qty, avg_price, COALESCE(multiplier,1),
               COALESCE(asset_class,'Equity'), COALESCE(sector,'-'),
               COALESCE(industry,'-'), COALESCE(subindustry,'-'), spot
        FROM positions WHERE strike IS NULL AND qty <> 0
    """).fetchall()
    # The leg LIST comes from `positions` -- marks are refreshed live below, but which
    # holdings exist is only as fresh as the last build_positions run. Stamp that vintage
    # on every row we write. Without it a reader cannot tell today's book from a two-day-old
    # one, which is exactly how a stale capture got read as current.
    book_as_of = con.execute("SELECT max(as_of) FROM positions WHERE qty <> 0").fetchone()[0]
    if book_as_of:
        age_h = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                 - book_as_of).total_seconds() / 3600
        print(f"book vintage: {book_as_of:%Y-%m-%d %H:%M} UTC ({age_h:.1f}h old)")
        if age_h > 24:
            print(f"  !! the book list is {age_h/24:.1f} days old -- re-run "
                  f"build_positions.py, or this capture describes holdings you may not have")
    # Release trades.duckdb before touching TWS. DuckDB allows ONE writer, and this script
    # then blocks for the whole TWS session (connect, qualify, a reqTickers per leg, account
    # summary) -- on a gateway this repo documents as routinely hanging. Holding the handle
    # across it means no fill can be recorded while a live capture runs, which is the
    # opposite of what the log of record is for. Re-opened below, only for the INSERTs.
    con.close()

    # Split by sec_type, not by account number: an account whose id happens to start with
    # "2010" is not what makes a leg Chinese. The CN rows are read here too -- they are the
    # book of record for WHICH CN legs exist (their marks are the one thing we cannot get).
    us = [r for r in rows if r[12] != "FUT_OPT"]
    cn = [r for r in rows if r[12] == "FUT_OPT"]
    syms = sorted({r[2] for r in us} | {r[2] for r in cash})
    ib = IB()
    ib.RequestTimeout = 45
    tws.connect(ib, client_id=110, timeout=25)

    n = ibmarks.clean      # IB leaves NaN / -1 for unavailable fields; see ibmarks.py

    # qualifyContracts returns a SAME-LENGTH list with None in the slot of anything it
    # cannot qualify (the sync docstring claims it filters; it does not). A None reaching
    # reqTickers crashes on contract.secType and kills the whole capture, so drop them.
    stock_pairs = list(zip(syms, ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in syms])))
    stock_ok = [(s, c) for s, c in stock_pairs if c]
    for s, c in stock_pairs:
        if not c:
            print(f"  !! {s}: TWS could not qualify the stock -- no live spot for its legs")
    spot = {}
    for (s, _), t in zip(stock_ok, ib.reqTickers(*[c for _, c in stock_ok]) if stock_ok else []):
        spot[s] = (n(t.bid) + n(t.ask)) / 2 if (n(t.bid) and n(t.ask)) else (n(t.last) or n(t.close))

    # The expiry comes from `positions` (r[13]). Hardcoding it meant a rolled leg was quietly
    # priced and greeked off the OLD expiry's contract at the same strike/right.
    opt_reqs = [r for r in us if r[13]]           # rows with no expiry in `positions` can't be requested
    opt_ok = []
    for r, c in zip(opt_reqs, ib.qualifyContracts(*[
            Option(r[2], r[13].strftime("%Y%m%d"), r[3], r[4], "SMART",
                   currency="USD", multiplier="100") for r in opt_reqs])):
        if c:
            opt_ok.append((r, c))
        else:
            print(f"  !! {r[2]} {r[3]:g}{r[4]} {r[13]}: TWS could not qualify the contract")
    marks = {}
    for (r, _), t in zip(opt_ok, ib.reqTickers(*[c for _, c in opt_ok]) if opt_ok else []):
        b, a = n(t.bid), n(t.ask)
        # Keyed by account+expiry too: the same strike/right can exist in two accounts at
        # different expiries, and one account's quote must never stand in for the other's.
        marks[(r[0], r[13], r[2], r[3], r[4])] = ((b + a) / 2, (a - b)) if (b and a) else (n(t.close), None)
    acct = {r.tag: float(r.value) for r in ib.accountSummary()
            if r.tag in ("NetLiquidation", "ExcessLiquidity", "AvailableFunds",
                         "InitMarginReq", "MaintMarginReq")}
    ib.disconnect()

    legs, skipped = [], []       # skipped = priced-nowhere legs, reported at the end

    for acct_id, broker, u, k, cp, q, entry, mult, aclass, sec, ind, sub, typ, exp, snap_spot in us:
        if exp is None:
            skipped.append(f"{u} {k:g}{cp} (positions has no expiry)")
            continue
        mid, spread = marks.get((acct_id, exp, u, k, cp), (None, None))
        if not mid:
            skipped.append(f"{u} {k:g}{cp} (no two-sided quote)")
            continue
        # Live spot, else the build_positions snapshot: a dataless ticker loses mark quality,
        # it does not silently drop the leg (and its whole underlying) out of the totals.
        # Either way the SPOT is as soft as a one-sided option quote when it falls back --
        # every greek is solved against it, so it belongs in the soft flag too.
        live_spot = n(spot.get(u))
        S = live_spot or n(snap_spot)
        if S is None:
            skipped.append(f"{u} {k:g}{cp} (no spot)")
            continue
        T_us = bs.T_years(exp)
        call = cp == "C"
        iv = bs.implied_vol(mid, S, k, T_us, R_US, call)
        if not iv:
            # The leg is kept (its P&L is real) but it contributes NOTHING to delta/gross/
            # vega/theta -- the row UNDERSTATES it. margin_curve.py warns for this exact
            # case; silence here made a short leg look hedged.
            print(f"  !! {u} {k:g}{cp}: no IV solvable from mid {mid:g} at spot {S:g} -- "
                  f"delta/vega/theta set to 0, this leg is UNDERSTATED in the totals")
        d, g, th, v = bs.bs_greeks(S, k, T_us, R_US, iv, call) if iv else (0, 0, 0, 0)
        legs.append(dict(acct=acct_id, broker=broker or acct_id, u=u, k=k, cp=cp, q=q,
                         mid=mid, S=S, iv=iv, d=d, g=g, th=th, v=v, mult=mult,
                         sect=(sec, ind, sub), aclass=aclass,
                         one_sided=(spread is None) or (live_spot is None),
                         fx_rate=1.0, pnl=(entry - mid) * (-q) * mult))

    # Stock/ETF legs: delta is the position (1.0 per share), greeks are zero by definition.
    for acct_id, broker, u, q, entry, mult, aclass, sec, ind, sub, snap_spot in cash:
        live_spot = n(spot.get(u))
        S = live_spot or n(snap_spot) or n(entry)
        if S is None:
            skipped.append(f"{u} (stock, no spot)")
            continue
        legs.append(dict(acct=acct_id, broker=broker or acct_id, u=u, k=None, cp=None, q=q,
                         mid=None, S=S, iv=None, d=1.0, g=0.0, th=0.0, v=0.0, mult=mult,
                         sect=(sec, ind, sub), aclass=aclass,
                         one_sided=(live_spot is None), fx_rate=1.0,
                         pnl=(S - entry) * q * mult))

    # CN legs: WHICH legs exist (and their qty/entry/mult/broker) comes from `positions`;
    # only the marks are the frozen CZCE print.
    for acct_id, broker, u, k, cp, q, entry, mult, aclass, sec, ind, sub, typ, exp, snap_spot in cn:
        mark = CN_MARKS.get((k, cp))
        if mark is None:
            skipped.append(f"{u} {k:g}{cp} (CN leg with no recorded mark)")
            continue
        S, settle, iv, exch_d = mark
        T_cn = bs.T_years(exp) if exp else bs.T_years(EXPIRY_CN)
        # Prefer the EXCHANGE's delta over ours for CN: it is the venue's own model on its
        # own instrument, and ours disagreed (we get -0.219/+0.275 where CZCE publishes
        # -0.2473/+0.2433) because a CNY futures option needs the futures carry, not r.
        _, g, th, v = bs.bs_greeks(S, k, T_cn, R_CN, iv, cp == "C")
        mult = mult or 10
        legs.append(dict(acct=acct_id, broker=broker or acct_id, u=u, k=k, cp=cp, q=q,
                         mid=settle, S=S, iv=iv, d=exch_d, g=g, th=th, v=v, mult=mult,
                         sect=(sec, ind, sub), aclass=aclass, one_sided=False,
                         fx_rate=FX_CNY, pnl=(entry - settle) * (-q) * mult / FX_CNY))
    cn_keys = {(r[3], r[4]) for r in cn}
    for k, cp in sorted(set(CN_MARKS) - cn_keys):
        print(f"  !! recorded CN mark for {k:g}{cp} has no position -- not priced "
              f"(leg closed? the constant is stale)")

    if not legs:
        print("\n!! no leg could be priced -- nothing written; the book is NOT flat")
        return       # the DB handle is already closed; nothing to write

    # State the direction of every position before pricing it. A flipped sign is INVISIBLE
    # in the aggregates -- it just moves that leg's contribution to the other side, which
    # looks like a market view rather than a bug. Convention: qty < 0 is SHORT. (Note: in
    # `fills` the sign is NOT stored -- qty is always positive and direction lives in
    # `action`; `positions` is where the signed net is materialised.)
    def leg_txt(l):
        """Stock legs have no strike/right -- they still need a legible label."""
        side = "SHORT" if l["q"] < 0 else "LONG"
        if l["k"] is None:
            return f"{side} {abs(l['q'])}x {l['u']} (stock)"
        return f"{side} {abs(l['q'])}x {l['k']:g}{l['cp']}"

    print("\nsigned structure being priced (qty<0 = SHORT):")
    for u in sorted({l["u"] for l in legs}):
        parts = "  ".join(leg_txt(l) for l in sorted((x for x in legs if x["u"] == u),
                                                     key=lambda x: (x["cp"] or "", x["k"] or 0)))
        print(f"  {u:<7}{parts}")

    # Anything dropped here is exposure the rows below do NOT contain -- say so, with the
    # count, or a missing leg reads as a market view instead of a data failure.
    if skipped:
        print(f"  !! {len(skipped)} leg(s) NOT priced, so NOT in any row below: "
              + "; ".join(skipped))

    # A leg marked off a one-sided quote (TWS gave us `close` instead of a real bid/ask), or
    # off a spot that is not a live quote, has its IV -- and therefore every greek, and every
    # scenario cell -- solved from a stale print. Flag it: the greeks are then a property of
    # that print, not of the market. Two captures of this same book disagreed on TLT by ~$15k
    # of delta notional; without this line neither row says which of its legs to distrust.
    one_sided = [l for l in legs if l.get("one_sided")]
    if one_sided:
        print(f"  note: {len(one_sided)} leg(s) soft -- a ONE-SIDED option quote (a close, not "
              f"a bid/ask) or a spot that is not a live quote -- so their greeks are soft: "
              + ", ".join(f"{l['u']} {leg_txt(l)}" for l in one_sided))
        print("        expected outside RTH; DURING the session it means no two-sided market "
              "and the row should not be trusted as a live mark.")

    def fx(l):
        """Carried on the leg itself: keying on the broker NAME meant the currency conversion
        silently depended on how that broker happened to be spelled."""
        return l["fx_rate"]

    def agg(sel):
        g = [l for l in legs if sel(l)]
        if not g:
            return None
        # every figure below is USD, CN converted at fx() -- the whole point is that a
        # reader can add these across brokers without asking what currency they are in
        delta_usd = sum(l["d"] * l["q"] * l["mult"] * l["S"] / fx(l) for l in g)
        # abs() has to wrap the WHOLE product, not just the delta. q is negative on every
        # leg of this book, so abs(d)*q flips the sign and gross came out negative on every
        # row -- a "gross exposure" column that could never be summed or compared to a
        # margin figure. Magnitude only: the sign of a gross number is meaningless.
        gross = sum(abs(l["d"] * l["q"] * l["mult"] * l["S"]) / fx(l) for l in g)
        vega = sum((l["v"] or 0) * l["q"] * l["mult"] / fx(l) for l in g)
        theta = sum((l["th"] or 0) * l["q"] * l["mult"] / fx(l) for l in g)
        pnl = {}
        for s in SHOCKS:
            pnl[s] = sum((l["d"] * l["S"] * s + 0.5 * l["g"] * (l["S"] * s) ** 2)
                         * l["q"] * l["mult"] / fx(l) for l in g)
        return delta_usd, gross, vega, theta, pnl

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    src = "capture_risk_live_tws"
    con = db.connect()          # re-open the log of record just for the write
    con.execute("ALTER TABLE risk_profile ADD COLUMN IF NOT EXISTS book_as_of TIMESTAMP")
    # APPEND, by design (see the module docstring): the DELETE that used to sit here keyed on
    # a `now` generated microseconds earlier, so it could never match a previous run -- it
    # only claimed an idempotency that did not exist.

    def ins(gt, key, a):
        # Named columns on purpose: a positional VALUES list breaks silently the day a
        # column is added to this table, and this table is a log of record.
        con.execute("""INSERT INTO risk_profile
                         (group_type, group_key, delta_usd, gross_delta_usd, vega_usd,
                          theta_usd, pnl_m15, pnl_m10, pnl_m5, pnl_0, pnl_p5, pnl_p10,
                          pnl_p15, ts_utc, source, book_as_of)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [gt, key, a[0], a[1], a[2], a[3], a[4][SHOCKS[0]], a[4][SHOCKS[1]],
                     a[4][SHOCKS[2]], a[4][SHOCKS[3]], a[4][SHOCKS[4]], a[4][SHOCKS[5]],
                     a[4][SHOCKS[6]], now, src, book_as_of])

    n = 0
    print(f"\n{'group':>10s} {'key':>26s} {'delta$':>11s} {'vega/pt':>9s} {'theta/d':>9s} "
          f"{'-10%':>10s} {'+10%':>10s}")
    for b in sorted({l["broker"] for l in legs}):
        a = agg(lambda l, b=b: l["broker"] == b)
        ins("broker", b, a); n += 1
        print(f"{'broker':>10s} {b:>26s} {a[0]:11,.0f} {a[2]:9,.0f} {a[3]:9,.0f} "
              f"{a[4][-0.10]:10,.0f} {a[4][0.10]:10,.0f}")
    for u in sorted({l["u"] for l in legs}):
        a = agg(lambda l, u=u: l["u"] == u)
        ins("ticker", u, a); n += 1
        print(f"{'ticker':>10s} {u:>26s} {a[0]:11,.0f} {a[2]:9,.0f} {a[3]:9,.0f} "
              f"{a[4][-0.10]:10,.0f} {a[4][0.10]:10,.0f}")
    a = agg(lambda l: True)
    con.close()

    print(f"\nsaved {n} rows -> risk_profile  ts_utc={now:%Y-%m-%d %H:%M:%S} source={src}")
    print(f"  priced {len(legs)} of {len(us) + len(cash) + len(cn)} legs"
          + (f" ({len(skipped)} NOT priced)" if skipped else ""))
    print(f"  book: delta ${a[0]:,.0f}  vega {a[2]:,.0f}/pt  theta {a[3]:,.0f}/d  "
          f"open P/L {sum(l['pnl'] for l in legs):+,.0f}")
    print("  IBKR margin: " + "  ".join(
        f"{k} {v:,.0f}" for k, v in acct.items()))


if __name__ == "__main__":
    main()
