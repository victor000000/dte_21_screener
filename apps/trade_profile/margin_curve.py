import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""margin_curve.py — margin requirement as a function of underlying price, per position.

WHY THIS EXISTS

Every other risk view in this repo answers "what do I lose if the market moves". None
answers "what does the broker DEMAND if the market moves", which is the question that
actually forces liquidation. A short strangle's requirement is convex in spot: as the
underlying approaches a strike the 20%-of-spot term grows while the out-of-the-money
credit shrinks, so margin rises from both ends at once, and the 10% floor is what stops
it rising forever. That shape is invisible in a P&L ladder and it is what makes 25 TLT
sets behave differently from 25 sets of anything else.

WHY NOT IBKR's OWN MODEL

`IB.whatIfOrder` gives IBKR's authoritative margin (initMarginAfter / maintMarginAfter),
but it takes an Order, not a price -- there is no way to ask "what would my margin be if
TLT were 80". It is exact at today's market and silent everywhere else, and a curve needs
everywhere else.

So the SHAPE comes from the Reg-T formula, which is price-dependent by construction, and
the LEVEL is calibrated against IBKR's real number at today's spot (the account's actual
InitMarginReq, which is the same model what-if would report but measured rather than
predicted). The calibration factor is reported, never hidden: if it is far from 1.0 the
formula's shape is still informative but its level is not, and you should say so out loud
rather than quietly scaling.

The factor is a measurement of IBKR against IBKR's own positions, so it is applied to
IBKR rows and to no others. Schwab's margin model was never measured and 浙商期货 is
charged under exchange rules that are not Reg-T at all; those rows are reported at
factor 1.0 and labelled UNCALIBRATED, because inheriting IBKR's number would be an
assertion dressed as a calibration. The CN rows additionally price a Reg-T shape on a
CNY notional (converted at FX_CNY) purely as a proxy -- they are the least trustworthy
line in the report and are marked as such.

Known limitation, stated rather than papered over: for the Schwab account there is no
programmatic equity, so no liquidation trigger is computable -- only the curve. Pass
--schwab-equity to supply one from a recent export.

    uv run python apps/trade_profile/margin_curve.py
"""
import argparse
import datetime as dt
import pathlib
import re
import sys

from ib_async import IB, Option, Stock

from datasources import tws

from data import clock  # noqa: E402
from compute import bs  # noqa: E402
from data import db  # noqa: E402
from datasources import ibmarks  # noqa: E402

ROOT = bootstrap.ROOT
from shared.rates import R_US as R
REG_T_RATE = 0.20             # FINRA 4210: 20% of underlying value
REG_T_FLOOR = 0.10            # ...minus OTM, floored at 10%
from shared.rates import FX_CNY

# CN option codes, in all three spellings the log holds: MA701C3350, MO2610-P-7400,
# sc2612P570. The trailing group is the strike, which is what pairs an observation in
# fills with a leg in the book.
CN_CONTRACT = re.compile(r"^([A-Za-z]+\d{3,4})-?([CP])-?(\d+(?:\.\d+)?)$")
SHOCKS = [i / 100 for i in range(-20, 21)]      # -20% .. +20% in 1% steps
INFO_TAGS = ("NetLiquidation", "EquityWithLoanValue", "InitMarginReq",
             "MaintMarginReq", "ExcessLiquidity", "AvailableFunds")


def naked_core(S, K, cp, n, mult):
    """Reg-T core requirement for `n` naked short contracts, WITHOUT the premium.

    FINRA 4210: 20% of underlying value minus the out-of-the-money amount, floored at
    10%. The floor is taken against the UNDERLYING for a call and the EXERCISE PRICE for
    a put -- that asymmetry is easy to miss and it is what makes a deep-OTM put stop
    getting cheaper to carry once spot runs away from it.
    """
    otm = max(0.0, S - K) if cp == "P" else max(0.0, K - S)
    base = REG_T_RATE * S - otm
    floor = REG_T_FLOOR * (K if cp == "P" else S)
    return max(base, floor) * mult * n


def position_margin(S, legs, T, r=R):
    """Margin for one underlying+expiry group at hypothetical underlying price `S`.

    `legs` carry SIGNED qty (negative = short -- the convention every fill in this
    database confirms). Long options cover shorts 1:1 within the same right; whatever is
    left over is naked and carries the requirement. A 1x2 put ratio therefore margins as
    ONE naked short put plus the short call, because the long wing covers its twin.

    Premium is allocated to the naked fraction only: the covered pair is a debit spread,
    paid in full, and charging margin against its premium would double-count it.
    """
    if not legs:
        return 0.0, 0.0
    mult = legs[0]["mult"]
    core_parts, prem = [], 0.0
    for cp in ("P", "C"):
        shorts = [l for l in legs if l["cp"] == cp and l["qty"] < 0]
        if not shorts:
            continue
        long_q = sum(l["qty"] for l in legs if l["cp"] == cp and l["qty"] > 0)
        short_q = sum(-l["qty"] for l in shorts)
        naked = max(0.0, short_q - long_q)
        if naked <= 0:
            continue
        # Several short strikes could survive the netting. The requirement is set by the
        # worst of them, so charge the naked count at the most expensive strike.
        core_parts.append(max(naked_core(S, l["K"], cp, naked, mult) for l in shorts))
        frac = naked / short_q
        prem += frac * sum(bs.bs_price(S, l["K"], T, r, l["iv"] or 0.0, cp == "C")
                           * (-l["qty"]) * mult for l in shorts)
    # Short strangle rule: the greater side's requirement plus the other side's premium.
    # With `naked_core` premium-free, that is max(core) + total naked premium.
    return (max(core_parts) if core_parts else 0.0) + prem, (max(core_parts) if core_parts else 0.0)


def to_legs(g):
    """positions row -> the shape position_margin wants. One place, so a rename in the
    table cannot leave half the call sites reading a key that no longer exists."""
    mult = g[0]["mult"]
    return [dict(K=r["strike"], cp=r["call_put"], qty=r["qty"], iv=r["iv"], mult=mult)
            for r in g]


_n = ibmarks.clean          # IB leaves NaN / -1 for unavailable fields; see ibmarks.py


def fetch_marks(ib, rows):
    """Live spot per underlying and live mid per leg. Falls back to the stored mark.

    A one-sided quote is recorded as such rather than silently accepted -- a greek solved
    from a stale close is a property of that print, not of the market.
    """
    # The CN book is not on this TWS at all -- asking it to qualify MA701 as a SMART/USD
    # stock returns None, and a None inside the contract list crashes reqTickers on
    # `.secType`. Qualify only what this broker actually carries.
    us = [r for r in rows if r["broker"] != "浙商期货"]
    syms = sorted({r["underlying"] for r in us})
    cs = [c for c in ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in syms]) if c]
    spot = {}
    for s, t in zip(syms, ib.reqTickers(*cs)):
        spot[s] = ((_n(t.bid) + _n(t.ask)) / 2 if (_n(t.bid) and _n(t.ask))
                   else (_n(t.last) or _n(t.close)))
    # qualifyContracts returns None for anything it cannot resolve; carrying those into
    # reqTickers turns an unqualifiable leg into a crash instead of a skipped one.
    opts, ok = [], []
    for r, c in zip(us, ib.qualifyContracts(*[
            Option(r["underlying"], r["expiry"].strftime("%Y%m%d"), r["strike"],
                   r["call_put"], "SMART", currency="USD", multiplier="100") for r in us])):
        if c:
            opts.append(c)
            ok.append(r)
        else:
            print(f"  !! {r['underlying']} {r['strike']:g}{r['call_put']}: IBKR cannot "
                  f"qualify this contract -- falling back to the stored mark")
    marks, soft = {}, []
    for r, t in zip(ok, ib.reqTickers(*opts)):
        b, a = _n(t.bid), _n(t.ask)
        key = (r["account"], r["underlying"], r["strike"], r["call_put"])
        marks[key] = (b + a) / 2 if (b and a) else (_n(t.close) or r["mark"])
        if not (b and a):
            soft.append(f"{r['underlying']} {r['strike']:g}{r['call_put']}")
    return spot, marks, soft


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None, help="limit to one account")
    ap.add_argument("--no-calibrate", action="store_true",
                    help="report the raw Reg-T curve, unscaled by the IBKR factor")
    ap.add_argument("--schwab-equity", type=float, default=None,
                    help="Schwab account equity (USD) from a recent export, to enable its trigger")
    args = ap.parse_args()

    con = db.connect(log="ro", trades_ro=True)
    raw = con.execute("""
        SELECT account, broker, underlying, expiry, strike, call_put, qty, mark,
               COALESCE(multiplier,100), spot
        FROM positions WHERE strike IS NOT NULL AND qty <> 0 ORDER BY account, underlying, strike
    """).fetchall()
    cols = ("account", "broker", "underlying", "expiry", "strike", "call_put", "qty",
            "mark", "mult", "spot")
    rows = [dict(zip(cols, r)) for r in raw]
    if args.account:
        rows = [r for r in rows if args.account in r["account"]]
    book_as_of = con.execute("SELECT max(as_of) FROM positions").fetchone()[0]

    ib = IB()
    ib.RequestTimeout = 45
    tws.connect(ib, client_id=121, timeout=25)
    spot, marks, soft = fetch_marks(ib, rows)
    acct = {r.tag: float(r.value) for r in ib.accountSummary() if r.tag in INFO_TAGS}
    ib.disconnect()

    # ---- per-leg IV, solved from the live mark (never read from a vendor field: yfinance
    # returned 6.3% on META 850C once, which is nonsense and is a known trap here).
    for r in rows:
        S = spot.get(r["underlying"]) or r["spot"]
        r["S0"] = S
        T = bs.T_years(r["expiry"])
        r["T"] = T
        key = (r["account"], r["underlying"], r["strike"], r["call_put"])
        mark = marks.get(key, r["mark"])
        r["mid"] = mark
        r["iv"] = bs.implied_vol(mark, S, r["strike"], T, R, r["call_put"] == "C") if (mark and S) else None
        if r["iv"] is None:
            print(f"  !! {r['underlying']} {r['strike']:g}{r['call_put']}: no IV from mark "
                  f"{mark} at spot {S} -- leg priced at intrinsic, premium understated")

    groups = {}
    for r in rows:
        # Broker first: the margin rule differs BY BROKER (Reg-T vs the exchange's own),
        # so a curve's level is only meaningful within one broker's book. Grouping by
        # account alone put IBKR and Schwab sections in an order that mixed the two.
        groups.setdefault((r["broker"], r["account"], r["underlying"], r["expiry"]), []).append(r)

    # ---- calibration: the formula's margin for the IBKR book vs the account's REAL
    # InitMarginReq at today's spot. Measured, not predicted -- same model what-if reports.
    ibkr_groups = {k: v for k, v in groups.items() if v[0]["broker"] == "IBKR"}
    factor, actual, formula = 1.0, None, None
    if ibkr_groups and "InitMarginReq" in acct:
        formula = sum(position_margin(g[0]["S0"], to_legs(g), g[0]["T"])[0]
                      for g in ibkr_groups.values())
        actual = acct["InitMarginReq"]
        if formula > 0:
            factor = actual / formula
    if args.no_calibrate:
        factor = 1.0

    # ── The factor belongs to IBKR and to nothing else ───────────────────────────
    # It is defined as IBKR's REAL InitMarginReq divided by what the Reg-T formula says
    # about IBKR's OWN book. Applying it to another broker's positions asserts that
    # Schwab and 浙商期货 charge the same multiple of Reg-T that IBKR charges for a
    # different portfolio -- which nothing measured. It was applied to every group in
    # the per-name table, the trough line and the liquidation trigger, so a Schwab leg
    # read as "calibrated" while resting on an IBKR ratio, and the CN group carried a
    # Reg-T formula (a US equity-option rule) scaled by an IBKR constant on top of it.
    # Uncalibrated groups now say so instead of silently inheriting the number.
    # ── The CN book is calibrated the same way IBKR's is, from what the broker CHARGED ──
    # 浙商期货 is not charged under Reg-T at all -- these are Chinese futures options, and
    # the margin is the exchange's, booked per lot in the 结算单. Running the US Reg-T
    # formula on a CNY notional and converting at FX is a category error, and it was not a
    # small one: the open book is 31 MA701 2650P + 31 MA701 3350C, the statements record
    # 4,964.6 CNY/lot for the puts and 4,199.6 for the calls, so the real requirement is
    # 284,090 CNY ≈ $39,845 -- while the proxy printed $19,748, under half.
    #
    # The observations are already in the log (fills.margin_local, written from the
    # 持仓明细), keyed by contract. So this is the IBKR treatment applied to the group that
    # most needed it: measured level, Reg-T shape, and a factor that says how far off the
    # shape is. A leg with no observation leaves the group at 1.0 and uncalibrated, rather
    # than calibrating from the legs that happen to have one.
    cn_per_lot = {}
    try:
        for sym, per_lot in con.execute("""
                SELECT symbol, median(margin_local / NULLIF(qty, 0))
                FROM fills WHERE broker = '浙商期货' AND margin_local IS NOT NULL AND qty <> 0
                GROUP BY symbol""").fetchall():
            m = CN_CONTRACT.match(sym or "")
            if m and per_lot:
                cn_per_lot[(m.group(1).upper(), m.group(2), float(m.group(3)))] = per_lot
    except Exception as e:
        print(f"  !! could not read observed CN margins ({repr(e)[:60]}); CN stays uncalibrated")

    def cn_group_factor(g):
        """(factor, observed_total_cny) for a CN group, from the charged per-lot margins."""
        seen = [(r, cn_per_lot.get((r["underlying"].upper(), r["call_put"], float(r["strike"]))))
                for r in g]
        if not seen or any(v is None for _r, v in seen):
            return 1.0, None
        observed = sum(abs(r["qty"]) * v for r, v in seen)
        f = position_margin(g[0]["S0"], to_legs(g), g[0]["T"])[0]
        return (observed / f if f > 0 else 1.0), observed

    def group_factor(broker, g=None):
        if broker == "IBKR":
            return factor
        if broker == "浙商期货" and g is not None:
            return cn_group_factor(g)[0]
        return 1.0

    uncalibrated = sorted({v[0]["broker"] for v in groups.values()
                           if v[0]["broker"] != "IBKR" and not (
                               v[0]["broker"] == "浙商期货" and cn_group_factor(v)[1] is not None)})

    today = clock.today().isoformat()
    out = [f"# Margin vs price — {today}",
           f"\n**Book as of {book_as_of:%Y-%m-%d %H:%M} UTC** — leg list from the last "
           f"`build_positions.py` run; spots and option marks pulled live from TWS.",
           f"\n*Reg-T core ({REG_T_RATE:.0%} of spot − OTM, floored at {REG_T_FLOOR:.0%} of "
           f"strike for puts / spot for calls) + short premium marked at each price. "
           f"Long wings cover shorts 1:1; the remainder is naked. Values in USD.*"]
    if actual is not None:
        out.append(f"\n**Calibration: IBKR InitMarginReq ${actual:,.0f} vs formula "
                   f"${formula:,.0f} ⇒ factor {factor:.3f}.** The curve's SHAPE is Reg-T; its "
                   f"level is scaled by this. A factor far from 1.0 means the two models "
                   f"disagree about this book's structure, not about its size."
                   + (f" **This factor applies to the IBKR rows only.** It is a measurement "
                      f"of IBKR's requirement against IBKR's own positions, so the "
                      f"{', '.join(uncalibrated)} rows are left at 1.0 and labelled "
                      f"UNCALIBRATED — no one measured their broker's ratio, and inheriting "
                      f"IBKR's would be a claim, not a measurement."
                      if uncalibrated else ""))
        out.append(f"\n*(IBKR margin terms: ELV ${acct.get('EquityWithLoanValue',0):,.0f} · "
                   f"init ${acct.get('InitMarginReq',0):,.0f} · maint ${acct.get('MaintMarginReq',0):,.0f} · "
                   f"excess liquidity ${acct.get('ExcessLiquidity',0):,.0f})*")
    else:
        out.append("\n**No calibration available** — curve is raw Reg-T and its LEVEL should "
                   "not be trusted, only its shape.")

    # 浙商期货's level comes from the margins its own settlement statements recorded, so it
    # is reported with the same prominence as IBKR's — it is a measurement, not a fallback.
    for g in [v for v in groups.values() if v[0]["broker"] == "浙商期货"]:
        gf, obs_cny = cn_group_factor(g)
        if obs_cny is None:
            out.append(f"\n**CN calibration unavailable for {g[0]['underlying']}** — no "
                       f"settlement margin recorded for one or more of its legs, so the row "
                       f"is raw Reg-T (a US equity-option rule on a CNY notional) at factor "
                       f"1.0. Treat its LEVEL as meaningless, not merely approximate.")
            continue
        # position_margin works on the notional it is handed, and a CN underlying's spot is
        # in CNY -- so `base` is CNY, not dollars. The ratio is unit-free (that is why the
        # factor is right), but printing it with a "$" would restate the very error this
        # calibration exists to correct, one line after correcting it.
        base = position_margin(g[0]["S0"], to_legs(g), g[0]["T"])[0]
        out.append(f"\n**CN calibration ({g[0]['underlying']}): the broker charged "
                   f"{obs_cny:,.0f} CNY (${obs_cny / FX_CNY:,.0f}) against a Reg-T formula of "
                   f"{base:,.0f} CNY (${base / FX_CNY:,.0f}) ⇒ factor {gf:.3f}.** 浙商期货 is "
                   f"charged under exchange rules, not Reg-T, so the formula supplies only the "
                   f"curve's SHAPE; its LEVEL is scaled to the margin actually booked in the 结算单.")

    if uncalibrated:
        out.append(f"\n*Uncalibrated at factor 1.0: {', '.join(uncalibrated)}.*")
    if soft:
        out.append(f"\n*{len(soft)} leg(s) marked off a one-sided quote, greeks soft: "
                   f"{', '.join(sorted(set(soft)))}*")

    print(f"\n{'='*100}\nCALIBRATION  actual ${actual:,.0f}  formula ${formula:,.0f}  "
          f"factor {factor:.3f}\n{'='*100}" if actual else "\nNO CALIBRATION\n")

    for (bkr, acct_id, u, exp), g in sorted(groups.items(), key=lambda kv: -abs(kv[1][0]["qty"] * kv[1][0]["S0"] * kv[1][0]["mult"])):
        S0, T, mult = g[0]["S0"], g[0]["T"], g[0]["mult"]
        legs = to_legs(g)
        struct = "  ".join(f"{'SHORT' if r['qty']<0 else 'LONG'} {abs(r['qty'])}x {r['strike']:g}{r['call_put']}"
                           for r in sorted(g, key=lambda r: (r["call_put"], r["strike"])))
        out.append(f"\n## {u} — {bkr} / {acct_id}\n\n`{struct}`\n")
        out.append(f"spot {S0:,.2f} · expiry {exp} ({T*365:.0f}d) · "
                   f"{len(g)} legs\n")
        out.append("| move | price | raw Reg-T | calibrated | per naked lot |")
        out.append("|---|---:|---:|---:|---:|")
        # Report the TROUGH, not a "peak". A naked short call's requirement is 20% of spot
        # once the OTM credit is gone, so it is linear in spot and rises WITHOUT BOUND --
        # any "peak" would just be wherever the grid happened to stop. The interior feature
        # that carries information is where the two sides cross and carry is cheapest.
        fx = FX_CNY if g[0]["broker"] == "浙商期货" else 1.0
        gf = group_factor(g[0]["broker"], g)
        trough, trough_m = None, float("inf")
        curve = []
        for s in SHOCKS[::2]:       # every 2% keeps the report readable
            S = S0 * (1 + s)
            m, _ = position_margin(S, legs, T)
            m /= fx
            curve.append((s, S, m))
            if m < trough_m:
                trough, trough_m = S, m
        for s, S, m in curve:
            mark = " ◀ spot" if abs(s) < 0.005 else ""
            out.append(f"| {s:+.0%} | {S:,.2f}{mark} | ${m:,.0f} | ${m*gf:,.0f} | "
                       f"${m*gf/max(1,sum(-l['qty'] for l in legs if l['qty']<0)):,.0f} |")
        out.append(f"\n**Cheapest carry at {trough:,.2f}** (${trough_m:,.0f} raw, "
                   f"${trough_m*gf:,.0f} calibrated"
                   + ("; this broker is UNCALIBRATED — its factor is 1.0, because the "
                      "measured one is IBKR's alone" if gf == 1.0 and factor != 1.0 else "")
                   + "). The requirement rises on BOTH sides "
                   f"of that point and is unbounded to the upside.")
        print(f"{u:<6}{acct_id:<14}spot {S0:8.2f}  min margin ${trough_m*gf:>10,.0f} "
              f"at {trough:8.2f} ({trough/S0-1:+.1%})")

    # ---- account-level liquidation trigger: uniform shock across the account's names,
    # where equity + P&L falls through the requirement.
    # A liquidation is triggered by the MAINTENANCE requirement, not the initial one --
    # they differ by ~12% on this account, which is the difference between "breaches at
    # -40%" and a materially nearer number. The ratio is measured from the account, and
    # applied only where it is known: Schwab's is not, so it stays at 1.0 and says so.
    maint_ratio = (acct["MaintMarginReq"] / acct["InitMarginReq"]
                   if acct.get("InitMarginReq") else 1.0)

    for broker, eq in (("IBKR", acct.get("EquityWithLoanValue")),
                       ("Schwab", args.schwab_equity)):
        bg = {k: v for k, v in groups.items() if v[0]["broker"] == broker}
        if not bg:
            continue
        if eq is None:
            note = ("\n### Liquidation trigger — Schwab\n\n**Not computable.** Schwab equity "
                    "is only knowable from a manual export, so no trigger is emitted rather "
                    "than one built on a stale balance. Re-run with "
                    "`--schwab-equity <recent equity>` to enable it.\n")
            out.append(note)
            print(f"\n{broker}: trigger NOT computed (no equity figure; see report)")
            continue
        trig = None
        for s in [i / 100 for i in range(-40, 41)]:
            margin = pnl = 0.0
            for g in bg.values():
                legs = to_legs(g)
                S = g[0]["S0"] * (1 + s)
                m, _ = position_margin(S, legs, g[0]["T"])
                ratio = maint_ratio if broker == "IBKR" else 1.0
                margin += m * group_factor(g[0]["broker"], g) * ratio / (FX_CNY if g[0]["broker"] == "浙商期货" else 1.0)
                for r in g:
                    mp = bs.bs_price(S, r["strike"], g[0]["T"], R, r["iv"] or 0.0, r["call_put"] == "C")
                    pnl += (mp - r["mid"]) * r["qty"] * r["mult"]
            if eq + pnl - margin <= 0:
                trig = (s, S)
                break
        if trig:
            # Read the factors off the groups the trigger actually summed. Asking
            # group_factor(broker) with no group returned the IBKR factor for IBKR and a
            # flat 1.0 for anything else -- right for this two-broker loop by luck, and
            # wrong the moment a third broker is added or a group is uncalibrated.
            fs = {round(group_factor(v[0]["broker"], v), 2) for v in bg.values()}
            label = f"{fs.pop():.2f}" if len(fs) == 1 else "mixed"
            out.append(f"\n### Liquidation trigger — {broker}\n\nA uniform "
                       f"{trig[0]:+.0%} move exhausts the cushion: equity + P&L falls through "
                       f"the requirement. Model-based (Reg-T shape × {label}), so treat it "
                       f"as an ordering, not a level.\n")
            print(f"{broker}: maintenance breach at a uniform {trig[0]:+.0%} move")
        else:
            out.append(f"\n### Liquidation trigger — {broker}\n\nNo breach within ±40% on this "
                       f"model (equity ${eq:,.0f}).\n")
            print(f"{broker}: no breach within +/-40%")

    report = "\n".join(x for x in out if x is not None)
    path = ROOT / "reports" / f"margin_curve_{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    con.close()
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
