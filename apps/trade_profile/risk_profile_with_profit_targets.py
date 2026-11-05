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

"""risk_profile_with_profit_targets.py — Risk profile + 50% profit target analysis.

Enhanced version that shows:
1. Standard risk profile (delta, vega, theta, scenarios)
2. Legs that have reached 50% profit
3. Legs approaching 50% profit (within 10% of target)
4. Distance to 50% profit for all short legs

Run: uv run python apps/trade_profile/risk_profile_with_profit_targets.py
"""
import datetime as dt
import duckdb

from data import clock
from data import db
from apps.trade_profile.targets import analyze as targets_analyze  # noqa: E402

from shared.rates import SHOCKS, FX_CNY as FXCNY

def main():
    con = db.connect()
    pos = con.execute("""SELECT broker, underlying, sec_type, strike, call_put, qty, spot,
    delta_units, gamma_units, theta_day, vega_pt, delta_notional_usd, asset_class, sector,
    industry, subindustry, avg_price, mark, expiry
    FROM positions WHERE qty <> 0""").fetchall()

    def book_vintage(c):
        try:
            return c.execute("SELECT max(as_of) FROM positions WHERE qty <> 0").fetchone()[0]
        except duckdb.Error:
            return None

    book_as_of = book_vintage(con)
    if book_as_of:
        age_d = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                 - book_as_of).total_seconds() / 86400
        print(f"book vintage: {book_as_of:%Y-%m-%d %H:%M} UTC ({age_d:.1f} days old)")

    def scenario_pnl(p, shock):
        broker = p[0]
        _, _, _, _, _, _, spot, du, gu, th, v, _, _, _, _, _, _, _, _ = p
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
    today = clock.today().isoformat()
    vintage = (f"**Book as of {book_as_of:%Y-%m-%d %H:%M} UTC — snapshot greeks, NOT live marks.**"
               if book_as_of else "**Book vintage UNKNOWN (positions.as_of is empty).**")

    out = [f"# Combined risk profile — {today}",
           f"\nPositions: {len(pos)} legs across brokers: {sorted({r[0] for r in pos})}",
           f"\n{vintage}",
           f"\n*Greeks: US by Black-Scholes; China from broker 快期. Scenarios = uniform % shock, 0-day horizon, IV unchanged. USD; CNY at {FXCNY}.*",
           f"\n## Overall\n- **Delta notional: ${fmt(overall['delta_usd'])}** (gross ${fmt(overall['gross_delta_usd'])})",
           f"- **Vega: ${fmt(overall['vega_usd'])} per vol pt** · **Theta: ${fmt(overall['theta_usd'])}/day**",
           "\n| Shock | " + " | ".join(f"{s:+.0%}" for s in SHOCKS) + " |",
           "|---|" + "---|" * len(SHOCKS),
           "| P&L $ | " + " | ".join(fmt(overall["pnl"][s]) for s in SHOCKS) + " |"]

    out.append(table("By broker", by(0)))
    out.append(table("By ticker", by(1)))

    # **NEW: 50% Profit Target Analysis**
    out.append("\n## 50% Profit Target Analysis")
    out.append("\n*Analyzing all short option legs for profit-taking opportunities*")

    # Filter option legs only (not stock)
    option_legs = [p for p in pos if p[2] == 'OPT']

    reached_50 = []
    approaching_50 = []
    all_shorts = []

    for p in option_legs:
        broker, underlying, sec_type, strike, call_put, qty, spot, _, _, _, _, _, _, _, _, _, avg_price, mark, expiry = p

        if qty >= 0:  # Skip long positions
            continue

        if not avg_price or not mark:
            continue

        # Through the shared helper. This loop skips longs above, so only the short
        # branch is reachable here, but the rule now lives in one place.
        _t = targets_analyze(avg_price, mark, qty)
        pnl_pct = _t['pnl_pct']
        target_50 = _t['target_50']
        distance_to_target = _t['distance']

        leg_info = {
            'underlying': underlying,
            'strike': strike,
            'call_put': call_put,
            'qty': qty,
            'avg_price': avg_price,
            'mark': mark,
            'pnl_pct': pnl_pct,
            'target_50': target_50,
            'distance': distance_to_target,
            'expiry': expiry
        }

        if pnl_pct >= 50:
            reached_50.append(leg_info)
        elif pnl_pct >= 40:  # Within 10% of 50% target
            approaching_50.append(leg_info)

        all_shorts.append(leg_info)

    # Sort by P&L percentage
    reached_50.sort(key=lambda x: -x['pnl_pct'])
    approaching_50.sort(key=lambda x: -x['pnl_pct'])
    all_shorts.sort(key=lambda x: -x['pnl_pct'])

    if reached_50:
        out.append("\n### ✅ Reached 50% Profit - CLOSE NOW")
        out.append("| Leg | Qty | Entry | Mark | P&L % | Target | Expiry |")
        out.append("|---|---|---|---|---|---|---|")
        for leg in reached_50:
            out.append(f"| {leg['underlying']} {leg['strike']:.0f}{leg['call_put']} | "
                      f"{leg['qty']} | ${leg['avg_price']:.2f} | ${leg['mark']:.2f} | "
                      f"+{leg['pnl_pct']:.1f}% | ${leg['target_50']:.2f} | {leg['expiry']} |")

    if approaching_50:
        out.append("\n### 📊 Approaching 50% - Watch Closely (40-50%)")
        out.append("| Leg | Qty | Entry | Mark | P&L % | Distance to 50% | Expiry |")
        out.append("|---|---|---|---|---|---|---|")
        for leg in approaching_50:
            out.append(f"| {leg['underlying']} {leg['strike']:.0f}{leg['call_put']} | "
                      f"{leg['qty']} | ${leg['avg_price']:.2f} | ${leg['mark']:.2f} | "
                      f"+{leg['pnl_pct']:.1f}% | {leg['distance']:.1f}% more | {leg['expiry']} |")

    # Show all shorts with their status
    out.append("\n### All Short Legs - Profit Status")
    out.append("| Leg | Qty | Entry | Mark | P&L % | To 50% Target | Status |")
    out.append("|---|---|---|---|---|---|---|")
    for leg in all_shorts[:15]:  # Limit to top 15
        if leg['pnl_pct'] >= 50:
            status = "✅ CLOSE"
        elif leg['pnl_pct'] >= 40:
            status = "⚡ WATCH"
        elif leg['pnl_pct'] >= 25:
            status = "📈 Profit"
        elif leg['pnl_pct'] >= 0:
            status = "➡️ Small +"
        else:
            status = "❌ Loss"

        sign = "+" if leg['pnl_pct'] >= 0 else ""
        out.append(f"| {leg['underlying']} {leg['strike']:.0f}{leg['call_put']} | "
                  f"{leg['qty']} | ${leg['avg_price']:.2f} | ${leg['mark']:.2f} | "
                  f"{sign}{leg['pnl_pct']:.1f}% | {leg['distance']:.1f}% | {status} |")

    out.append(table("By asset class", by(12)))
    out.append(table("By sector / industry", by_pair(13, 14)))

    report = "\n".join(out)
    path = bootstrap.ROOT / "reports" / f"risk_profile_targets_{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nwritten: {path}")
    con.close()

if __name__ == "__main__":
    main()
