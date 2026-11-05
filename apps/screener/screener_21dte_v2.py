import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

"""screener_21dte_v2.py — the real screen: every number comes from a stored series.

Reads (log → history → reference → warehouse, the resolution order of DATABASE_DESIGN §6):
  mh.iv_history       IVR/IVP computed over the stored series (vendor numbers kept as
                      provenance); the ranking rule and source preference live in
                      compute.iv_rank, shared with the filter that builds the universe
  mh.option_bars      the smile: IV per strike from bar closes via bs.implied_vol, delta via
                      bs.bs_delta → the ±0.16–0.22Δ strangle legs
  yh.prices           spot + HV30 close-to-close (the warehouse owns US daily bars)
  ref.earnings        the veto: a report inside the expiry window flags the name
  ref.calendar/events expiry is a trading day; FOMC/macro inside the window is listed

Writes: reports/screener_<date>.md + one screener_runs row per candidate (the audit trail).
Schema-tolerant: reads `iv` (post-widening) or `atm_iv` (current) from iv_history.
With no selection arguments, delegates to the all-US asset-class IVR/coverage
screen. Explicit symbols, universe or expiry retain this stock option-leg path.

    uv run python apps/screener/screener_21dte_v2.py \
        [--expiry 2026-11-20] [--symbols META CRWD ...] [--min-ivr 35]
"""
import argparse
import datetime as dt
import math
import pathlib
import sys

from data import clock  # noqa: E402
from compute import bs  # noqa: E402
from compute.iv_rank import fetch_series, rank_series, iv_column as series_iv_column  # noqa: E402
from data import db  # noqa: E402
from apps.screener.smile_marks import price_legs

ROOT = bootstrap.ROOT
from shared.rates import R_US as R
HV_WINDOW = 30


def third_friday(year, month):
    d = dt.date(year, month, 1)
    fri = [d + dt.timedelta(days=i) for i in range(31)
           if (d + dt.timedelta(days=i)).month == month and (d + dt.timedelta(days=i)).weekday() == 4]
    return fri[2]


def next_monthly_expiry(today, min_dte=35):
    y, m = today.year, today.month
    for _ in range(4):
        e = third_friday(y, m)
        if (e - today).days >= min_dte:
            return e
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None


def iv_column(con):
    return series_iv_column(con)


def iv_series(con, sym, col):
    # ONE row per (source, day), via the shared accessor -- the filter that builds the
    # universe reads the same way, so scope and PASS cannot disagree. The old inline query
    # required `expiry IS NULL`, which excluded alpaca_atm entirely (it labels its one
    # daily row with an expiry) and left 1,075 names unrankable forever.
    #
    # prefer the best-ranked source that actually has enough history for an IVR — a
    # one-row live panel is fresher but cannot rank anything. Rule: compute.iv_rank.
    by_u, _excluded = fetch_series(con, col=col, table="mh.iv_history", symbols=[sym])
    return rank_series(by_u.get(sym, []))


def spot_and_hv(con, sym):
    """Freshest close wins, and the HV series is merged across both stores.

    Reading the warehouse first was a real bug (found 2026-09-30 by rechecking): its last
    build was 5 days old, so the screen priced legs off a stale spot — SWKS came out 5.6%
    too high. The warehouse is deeper, our tail is newer; neither alone is right.
    """
    px = {}
    for day, close in con.execute("""
            SELECT date AS day, close FROM yh.prices WHERE symbol=?
            UNION ALL
            SELECT day, close FROM mh.underlying_daily WHERE symbol=?""",
            [sym, sym]).fetchall():
        if close is not None and math.isfinite(close) and close > 0:
            px[day] = close                  # only usable tail rows override the warehouse
    if not px:
        return None, None
    days = sorted(px)[-(HV_WINDOW + 2):]
    rows = [(d, px[d]) for d in days]
    spot = rows[-1][1]
    cl = [r[1] for r in rows]
    if len(cl) < HV_WINDOW + 1:
        return spot, None
    rets = [math.log(cl[i + 1] / cl[i]) for i in range(len(cl) - 1)][-HV_WINDOW:]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return spot, math.sqrt(var * 252)


def smile_legs(con, sym, expiry, spot):
    """IV per strike from stored bars → ±0.16–0.22Δ legs, plus the put-call skew in vol points."""
    # Each expiry has its own feed date. A newer chain must not hide an older one.
    asof = con.execute("SELECT max(day) FROM mh.option_bars WHERE underlying=?", [sym]).fetchone()[0]
    if asof is None:
        return None, None, None, "no option bars for this name"
    def bars_for(exp):
        return con.execute("""
            SELECT strike, call_put, day, close FROM mh.option_bars
            WHERE underlying=? AND expiry=? AND close > 0 AND day >= (
                SELECT max(day) - INTERVAL 7 DAY FROM mh.option_bars
                WHERE underlying=? AND expiry=? AND close > 0)""",
            [sym, exp, sym, exp]).fetchall()

    bars = bars_for(expiry)
    exp_used = expiry
    if not bars:
        # The target expiry's strike grid is only chosen 45 days before it expires, so a
        # fresh target often has no bars yet. Fall back to the nearest expiry that does,
        # and say which one was used — a leg computed on the wrong expiry silently is
        # worse than no leg at all.
        alt = con.execute("""
            SELECT expiry FROM mh.option_bars WHERE underlying=? AND expiry > ? AND close > 0
            ORDER BY expiry LIMIT 1""", [sym, clock.today()]).fetchone()
        if not alt:
            return None, None, None, "no option bars at or after today"
        exp_used = alt[0]
        bars = bars_for(exp_used)
        if not bars:
            return None, None, None, f"no bars for {exp_used}"
    asof = max(row[2] for row in bars)
    legs, unmatched = price_legs(con, sym, exp_used, spot, bars, clock.today())

    def nearest(cp):
        """Strike nearest 0.19Δ — but only from inside the 0.16–0.22Δ band the strategy trades.

        The old form ended `... or legs[cp]`: when nothing was in band it silently fell back
        to the WHOLE ladder and returned whatever sat closest to 0.19 however far away. MUB
        (spot 100.96, every priced put in the money) came back with a -0.66Δ put and was
        reported PASS — a tradeable-looking row for a trade the strategy would never put on,
        and a delta 3x outside the band. If the band is empty the honest answer is None.
        """
        cand = [x for x in legs[cp] if 0.16 <= abs(x["delta"]) <= 0.22]
        return min(cand, key=lambda x: abs(abs(x["delta"]) - 0.19)) if cand else None

    put, call = nearest("P"), nearest("C")
    skew = (put["iv"] - call["iv"]) * 100 if (put and call) else None
    note = None if exp_used == expiry else f"legs on {exp_used} (nearest with bars)"
    if (clock.today() - asof).days > 7:
        note = " · ".join(filter(None, [note, f"bars to {asof}"]))
    if unmatched:
        note = " · ".join(filter(None, [note, f"missing underlying closes on {len(unmatched)} bar date(s)"]))
    return put, call, skew, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry", default=None)
    ap.add_argument("--symbols", nargs="*", default=None)
    # Explicit stock option-leg runs may use the trade-filter universe. The default
    # entrypoint assesses every observed US asset class before applying its own rules.
    ap.add_argument("--universe", default=None,
                    help="explicit stock/fund option-leg universe; by default screen all US asset classes")
    ap.add_argument("--min-ivr", type=float, default=None,
                    help="IVR floor for PASS (user criterion, 2026-10-04; was 30)")
    args = ap.parse_args()

    if not args.symbols and not args.universe and not args.expiry:
        from apps.screener.screen_all_us import run
        run() if args.min_ivr is None else run(args.min_ivr, strict_ivr=False)
        return

    if args.min_ivr is None:
        args.min_ivr = 35.0

    con = db.connect(log="rw", history="ro", reference="ro", universe=True)
    today = clock.today()
    expiry = dt.date.fromisoformat(args.expiry) if args.expiry else next_monthly_expiry(today)
    dte = (expiry - today).days
    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols]
    else:
        uni = bootstrap.DATA_ROOT / (args.universe or 'plans/universe_screen.txt')
        if not uni.exists():
            print(f"universe file not found: {uni}"); return
        syms = [l.strip().upper() for l in uni.read_text().splitlines()
                if l.strip() and not l.startswith("#")]
        print(f"universe: {args.universe} ({len(syms)} names)")
    col = iv_column(con)

    # None means "not in the calendar", which is NOT the same as "closed". The
    # calendar is derived from days observed in bars (build_reference.py), so its last
    # entry is the most recent session WITH DATA -- a future expiry is never in it.
    # Reporting None as False made every run claim the expiry was not a trading day.
    on_cal = con.execute("SELECT is_open FROM ref.calendar WHERE venue='US' AND day=?",
                         [expiry]).fetchone()
    events = con.execute("SELECT day, kind, name FROM ref.events WHERE importance='high' "
                         "AND day BETWEEN CURRENT_DATE AND ? ORDER BY day", [expiry]).fetchall()

    rows = []
    for sym in syms:
        iv = iv_series(con, sym, col)
        spot, hv30 = spot_and_hv(con, sym)
        earn = con.execute("SELECT day, timing FROM ref.earnings WHERE underlying=? "
                           "AND day BETWEEN CURRENT_DATE AND ? ORDER BY day LIMIT 1",
                           [sym, expiry]).fetchone()
        put = call = skew = None
        note = "no spot"
        if spot:
            put, call, skew, note = smile_legs(con, sym, expiry, spot)
        credit = put["mark"] + call["mark"] if (put and call) else None
        margin = None
        if put and call and spot:
            # Reg-T short strangle: the GREATER side's requirement plus BOTH sides'
            # premium. The previous form added each side's premium into its own
            # requirement and then took the max, which silently discarded the losing
            # side's premium entirely:
            #   max(call_core + call_prem, put_core + put_prem)   <-- wrong
            #   max(call_core, put_core) + call_prem + put_prem   <-- correct
            # For META 645P/870C at 728.08 that is $8,499 vs the true $9,795 per
            # contract -- 13% understated, and the screen sizes positions off this.
            # margin_curve.py already implements the correct rule; the two disagreed.
            call_core = max(0.2 * spot - max(call["K"] - spot, 0), 0.1 * spot)
            put_core = max(0.2 * spot - max(spot - put["K"], 0), 0.1 * put["K"])
            margin = (max(call_core, put_core) + call["mark"] + put["mark"]) * 100
        flags = []
        if note:
            flags.append(note)
        if earn:
            flags.append(f"EARNINGS {earn[0]}{' ' + earn[1] if earn[1] else ''}")
        if skew is not None and skew > 3:
            flags.append(f"SKEW {skew:.1f}vp")
        # Tradeability is a GATE, not a footnote. Previously the flag depended only on IVR, so
        # a name with no strike in the 0.16-0.22Δ band still came back PASS with a fabricated
        # leg. Whatever the IVR says, a name whose legs cannot be constructed is not a
        # candidate -- 12 names in the 413 have no usable pair at all, and 53% of
        # (name, expiry, day) groups lack both legs.
        if not iv or iv["iv"] is None:
            flag = "NO-IV"
        elif not (put and call):
            flag = "NO-LEG"
        elif earn:
            flag = "EVENT"
        elif iv["ivr"] is not None and iv["ivr"] >= args.min_ivr:
            flag = "PASS"
        else:
            flag = "WATCH"
        rows.append({"sym": sym, "spot": spot, "iv": iv, "hv30": hv30, "put": put, "call": call,
                     "skew": skew, "credit": credit, "margin": margin, "flag": flag, "flags": flags})
    rows.sort(key=lambda r: -(r["iv"]["ivr"] if r["iv"] and r["iv"]["ivr"] is not None else -1))

    def num(x, n=2, fmt="f"):
        return "-" if x is None else format(x, f".{n}{fmt}")

    L = [f"# 21-DTE screener v2 — {today} · target expiry {expiry} ({dte} DTE)", "",
         f"Expiry on the US calendar: **{'unknown (not in calendar)' if not on_cal else ('open' if on_cal[0] else 'CLOSED')}**"
         f" · high-importance events "
         f"inside the window: {', '.join(f'{d} {n}' for d, k, n in events) or 'none'}", "",
         "| Sym | Spot | ATM IV % | IVR | series | HV30 % | VRP(vp) | Kput(Δ) | Kcall(Δ) | credit | margin | skew(vp) | flag |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        iv, p, c = r["iv"], r["put"], r["call"]
        current_iv = (iv or {}).get("iv")
        leg = lambda x: "-" if not x else f"{x['K']:.0f}({x['delta']:+.2f})"
        L.append("| {sym} | {spot} | {atm_iv} | {ivr} | {kind} | {hv} | {vrp} | {p} | {c} | {cr} | {mg} | {sk} | {flag} |".format(
            sym=r["sym"], spot=num(r["spot"]), kind=(iv or {}).get("kind", "-"),
            atm_iv=num(current_iv * 100 if current_iv is not None else None, 1), ivr=num((iv or {}).get("ivr"), 0),
            hv=num(r["hv30"] * 100 if r["hv30"] is not None else None, 1),
            vrp=num((current_iv - r["hv30"]) * 100
                    if current_iv is not None and r["hv30"] is not None else None, 1),
            p=leg(p), c=leg(c), cr=num(r["credit"]), mg=num(r["margin"], 0),
            sk=num(r["skew"], 1),
            flag=r["flag"] + (" · " + " · ".join(r["flags"]) if r["flags"] else "")))
    L += ["", "IVR = 100 * (latest IV - min IV) / (max IV - min IV), over the last 252 daily observations (minimum 60). IVP is the percentile. Vendor numbers "
              "stay in iv_history as provenance. credit and margin premiums are model estimates at "
              "the displayed spot, holding each leg's IV from its matched bar-date close; they are not live quotes."]
    out = ROOT / "reports" / f"screener_{today}.md"
    # v1 had this; v2 did not, so a fresh checkout with no reports/ directory
    # crashed on the last line of the run -- after doing all the work.
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")

    con.execute("""CREATE TABLE IF NOT EXISTS screener_runs (run_ts TIMESTAMP, underlying TEXT,
        spot DOUBLE, expiry DATE, dte INT, atm_iv DOUBLE, ivr DOUBLE, ivr_kind TEXT, hv20 DOUBLE,
        hv_rank DOUBLE, put_k DOUBLE, put_delta DOUBLE, call_k DOUBLE, call_delta DOUBLE,
        credit DOUBLE, margin_est DOUBLE, dollar_vol_20d DOUBLE, flag TEXT)""")
    for r in rows:
        iv = r["iv"] or {}
        con.execute("INSERT INTO screener_runs VALUES (CAST(current_timestamp AT TIME ZONE 'UTC' AS TIMESTAMP),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [r["sym"], r["spot"], expiry, dte, iv.get("iv"), iv.get("ivr"), iv.get("kind"),
                     r["hv30"], None,
                     r["put"]["K"] if r["put"] else None, r["put"]["delta"] if r["put"] else None,
                     r["call"]["K"] if r["call"] else None, r["call"]["delta"] if r["call"] else None,
                     r["credit"], r["margin"], None, r["flag"]])
    con.close()
    print(f"screened {len(rows)} names -> {out}")
    for r in rows[:8]:
        ivr = r["iv"]["ivr"] if r["iv"] and r["iv"]["ivr"] is not None else None
        print(f"  {r['sym']:6} {r['flag']:8} " +
              (f"IVR {ivr:.0f} [{r['iv']['kind']}]" if ivr is not None else "IVR n/a") +
              (f" · {', '.join(r['flags'])}" if r["flags"] else ""))


if __name__ == "__main__":
    main()
