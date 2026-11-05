import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""plan_builder.py — the risk navigator: one screen answering "what happens if…".

Reads the record (positions, account_daily) and the structure layer (earnings, events,
calendar). Writes plans/risk_navigator_<date>.md.

Per position      status (short/long, tested), σ-distance of the strike, the 50%-harvest
                  state and the underlying level that would trigger it, greeks in dollars.
Per account       net delta $ (per 1.00 move), theta $/day, vega $/vol-pt, and the **buffer-zero line**:
                  the move at which free funds are consumed (delta+gamma approximation).
Per underlying    a P/L grid at −10…+10% from the stored greeks.
Overlay           earnings / FOMC / macro inside the nearest expiry, per held name.

Approximations are labelled in the output: P/L uses delta+gamma (no vanna/volga), the
harvest trigger is a BS re-price at the position's own IV. If a number cannot be
computed from what is stored, it prints "n/a" rather than a guess.

    uv run python apps/plan/plan_builder.py [--account U0000000]
"""
import argparse
import datetime as dt
import math
import pathlib
import sys

from data import clock  # noqa: E402
from compute import bs  # noqa: E402
from data import db  # noqa: E402

ROOT = bootstrap.ROOT
from shared.rates import R_US as R


def iv_for(con, sym):
    """The stored IV for the underlying, or None — never a fabricated default: a made-up
    vol would silently produce a confident σ-distance and a wrong harvest level."""
    for col in ("iv", "atm_iv"):                     # schema-tolerant during the widening
        try:
            row = con.execute(f"""SELECT {col} FROM mh.iv_history WHERE underlying=?
                                  AND {col} IS NOT NULL AND expiry IS NULL
                                  ORDER BY day DESC LIMIT 1""",
                              [sym]).fetchone()
            return row[0] if row and row[0] else None
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None)
    args = ap.parse_args()

    con = db.connect(log="ro", history="ro", reference="ro")
    today = clock.today()
    q = "SELECT * FROM positions" + (" WHERE account=?" if args.account else "")
    cols = [d[0] for d in con.execute("DESCRIBE positions").fetchall()]
    rows = [dict(zip(cols, r)) for r in con.execute(q, [args.account] if args.account else []).fetchall()]

    L = [f"# Risk navigator — {today}", "",
         f"Book as of the last position build · {len(rows)} legs across "
         f"{len({r['account'] for r in rows})} accounts. Approximations are labelled; "
         f"n/a means the input is not stored, not that the risk is absent.", ""]

    # ---- per-account summary
    # build_positions FX-converts ONLY delta_notional_usd for the CN account; theta_day
    # and vega_pt are inserted raw CNY. Summing them into "$/day" and "$/vol-pt"
    # columns added CNY to USD (the CN account is ~CNY 694/day, i.e. about $97).
    # delta_notional is already USD, so it must NOT be converted again here.
    from shared.rates import FX_CNY
    def _is_cn(broker):
        return broker == "浙商期货"

    by_acct = {}
    for r in rows:
        a = by_acct.setdefault(r["account"], {"delta": 0.0, "theta": 0.0, "vega": 0.0, "n": 0})
        a["delta"] += r["delta_notional_usd"] or 0
        a["theta"] += (r["theta_day"] or 0) / (FX_CNY if _is_cn(r["broker"]) else 1.0)
        a["vega"] += (r["vega_pt"] or 0) / (FX_CNY if _is_cn(r["broker"]) else 1.0)
        a["n"] += 1
    L += ["## Accounts", "", "| account | legs | net delta $ (per 1.00 spot move) | theta $/day | vega $/vol-pt | free funds | buffer zeroes at |",
          "|---|---|---|---|---|---|---|"]
    for acct, a in by_acct.items():
        ad = con.execute("""SELECT available, currency, day FROM account_daily WHERE account=?
                            ORDER BY day DESC LIMIT 1""", [acct]).fetchone()
        avail, ccy = (ad[0], ad[1]) if ad else (None, None)
        if avail and a["delta"]:
            # `delta` is delta_notional_usd for every account; `available` is in the
            # account's OWN currency. The CN account is 浙商期货, whose available cash
            # is CNY -- dividing CNY by a USD notional inflated the CN buffer line by
            # the FX rate (~7.13x).
            fx = 7.13 if (ccy or "").upper() == "CNY" else 1.0
            # times 100, because delta_notional_usd is the dollar change per a 1.00
            # (100%) move in spot: build_positions writes exactly delta_units * spot
            # (verified against the table). The ratio avail/delta is therefore the
            # FRACTIONAL move that consumes free funds, and it was being printed as a
            # percentage -- understating the buffer by 100x. U0000000 showed "0.2%"
            # where the honest figure is 23.5%; the column header had the same error,
            # calling a full-notional delta a "$/1% move". The sensitivity grid below
            # uses full-notional semantics correctly, so the two contradicted each
            # other inside the same report.
            x = abs((avail / fx) / a["delta"]) * 100.0
            line = f"≈ {x:.1f}% adverse move" + (" (CNY→USD at %.2f)" % fx if fx != 1.0 else "")
        else:
            line = "n/a (no funds row)"
        fmt = lambda v: "n/a" if v is None else f"{v:,.0f}"
        L.append(f"| {acct} | {a['n']} | {fmt(a['delta'])} | {fmt(a['theta'])} | {fmt(a['vega'])} | "
                 f"{fmt(avail)} {ccy or ''} | {line} |")
    L.append("")

    # ---- per-position: tested? σ-distance? harvest state
    # Broker first. An order goes to one broker, so the broker is the axis a leg
    # list is read along; account stays as a column because it disambiguates two
    # books at the same broker.
    L += ["## Legs", "",
          "| broker | account | underlying | leg | qty | entry | mark | P/L | Δunits | θ/day | σ to strike | status | harvest |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    harvest_queue = []
    for r in sorted(rows, key=lambda x: (x["broker"], x["account"], x["underlying"],
                                         x["expiry"] or today, x["strike"] or 0)):
        S, K = r["spot"], r["strike"]
        iv = iv_for(con, r["underlying"]) if S and K else None
        dte = max(((r["expiry"] - today).days if r["expiry"] else 0), 0)
        sigma_move = (iv or 0) * math.sqrt(max(dte, 1) / 365.0) * (S or 0)
        dist_sigma = abs((S - K) / sigma_move) if (S and K and sigma_move) else None
        short = (r["qty"] or 0) < 0
        tested = "TESTED" if (dist_sigma is not None and dist_sigma < 1.0 and short) else "untested"
        pl = None
        if r["mark"] is not None and r["avg_price"] is not None and r["qty"]:
            mult = r["multiplier"] or 100
            pl = (r["avg_price"] - r["mark"]) * (-r["qty"]) * mult if short else \
                 (r["mark"] - r["avg_price"]) * r["qty"] * mult
        harv = ""
        if short and r["avg_price"] and r["mark"] is not None:
            pct = (r["avg_price"] - r["mark"]) / r["avg_price"] * 100 if r["avg_price"] else None
            if pct is not None and pct >= 50:
                harv = f"HARVEST NOW (+{pct:.0f}%)"
                harvest_queue.append((r["underlying"], r["strike"], r["call_put"], pct))
            elif iv is None:
                harv = "n/a (no stored IV for the level solve)"
            else:
                # BS level that would take the mark to half the entry credit
                T = max(dte, 1) / 365.0
                target = r["avg_price"] * 0.5
                lo, hi = (S or 1) * 0.5, (S or 1) * 1.5
                for _ in range(40):
                    mid = (lo + hi) / 2
                    px = bs.bs_price(mid, K, T, R, iv or 0.45, r["call_put"] == "C") if K else None
                    if px is None:
                        break
                    # a short call profits as S falls; a short put as S rises
                    if r["call_put"] == "C":
                        lo, hi = (lo, mid) if px > target else (mid, hi)
                    else:
                        lo, hi = (mid, hi) if px > target else (lo, mid)
                lvl = (lo + hi) / 2
                harv = f"50% at {r['underlying']} ≈ {lvl:,.1f}"
        L.append("| {bk} | {acc} | {u} | {k}{cp} {exp} | {q} | {e} | {m} | {pl} | {d} | {th} | {sg} | {st} | {h} |".format(
            bk=r["broker"], acc=r["account"], u=r["underlying"], k=f"{K:,.0f}" if K else "-",
            cp=r["call_put"] or "", exp=r["expiry"] or "-", q=r["qty"],
            e=f"{r['avg_price']:.2f}" if r["avg_price"] else "-",
            m=f"{r['mark']:.2f}" if r["mark"] is not None else "-",
            pl="n/a" if pl is None else f"{pl:+,.0f}",
            d="n/a" if r["delta_units"] is None else f"{r['delta_units']:+,.0f}",
            th="n/a" if r["theta_day"] is None else f"{r['theta_day']:+,.0f}",
            sg="n/a" if dist_sigma is None else f"{dist_sigma:.1f}σ",
            st=tested, h=harv or "-"))
    L.append("")

    # ---- sensitivity grid per underlying
    L += ["## Sensitivity (delta+gamma approximation, no vanna/volga)", "",
          "| underlying | spot | −10% | −5% | −2% | +2% | +5% | +10% |", "|---|---|---|---|---|---|---|---|"]
    by_und = {}
    for r in rows:
        d = by_und.setdefault(r["underlying"], {"d": 0.0, "g": 0.0, "S": r["spot"]})
        d["d"] += r["delta_notional_usd"] or 0
        d["g"] += r["gamma_units"] or 0
    for u, d in by_und.items():
        S = d["S"]
        if not S:
            L.append(f"| {u} | n/a | | | | | | |"); continue
        cells = []
        for x in (-0.10, -0.05, -0.02, 0.02, 0.05, 0.10):
            pl = d["d"] * x + 0.5 * d["g"] * (x * S) ** 2
            cells.append(f"{pl:+,.0f}")
        L.append(f"| {u} | {S:,.2f} | " + " | ".join(cells) + " |")
    L.append("")

    # ---- event overlay
    L += ["## Events inside the nearest expiry", ""]
    for u in sorted(by_und):
        exps = [r["expiry"] for r in rows if r["underlying"] == u and r["expiry"]]
        if not exps:
            continue
        exp = min(exps)
        ev = con.execute("""SELECT day, kind, name FROM ref.events WHERE day BETWEEN CURRENT_DATE AND ?
                            AND importance='high' ORDER BY day""", [exp]).fetchall()
        e = con.execute("""SELECT day, timing FROM ref.earnings WHERE underlying=?
                           AND day BETWEEN CURRENT_DATE AND ? ORDER BY day LIMIT 1""", [u, exp]).fetchone()
        bits = [f"earnings {e[0]}{' ' + e[1] if e[1] else ''}"] if e else []
        bits += [f"{d} {n}" for d, k, n in ev[:3]]
        L.append(f"- **{u}** (to {exp}): " + ("; ".join(bits) if bits else "no flagged events"))
    L.append("")

    if harvest_queue:
        L += ["## Harvest queue (≥50% of entry credit, short legs)", ""]
        for u, K, cp, pct in harvest_queue:
            L.append(f"- {u} {K:,.0f}{cp} — +{pct:.0f}%")
        L.append("")

    out = ROOT / "plans" / f"risk_navigator_{today}.md"
    out.write_text("\n".join(L) + "\n")
    con.close()
    print(f"risk navigator -> {out}")
    for a, v in by_acct.items():
        print(f"  {a}: {v['n']} legs · delta {v['delta']:+,.0f} · theta {v['theta']:+,.0f}/day · vega {v['vega']:+,.0f}")
    for item in harvest_queue:
        print(f"  HARVEST {item[0]} {item[1]}{item[2]} +{item[3]:.0f}%")


if __name__ == "__main__":
    main()
