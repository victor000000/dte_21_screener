"""report.py — the markdown file and the console table, over the same rows.

Two renderers, one grouping. They were inline in a 79-line main(); they are here
so the format is testable without a database, which matters because the markdown
is what gets read and the console is what gets watched.
"""
from itertools import groupby

from data import clock
from shared.rates import fx_of

from .constants import HARVEST
from .narrative import narrative


def _totals(g, broker):
    """Position theta/vega are stored per position already (qty * greek * 100), so
    these are the broker's totals without any further weighting."""
    fx = fx_of(broker)
    th = sum(x["theta"] or 0.0 for x in g) / fx
    vg = sum(x["vega"] or 0.0 for x in g) / fx
    return th, vg


def markdown(rows, rt_moves, root):
    out = [f"# Per-leg P&L — {clock.today()}", "",
           "Percentages of the entry credit (short) or debit (long). `mark` is the last "
           "price the source gave; `est` re-prices with QuantLib at the current underlying, "
           "solving the IV from the leg's current price. Grouped by broker: an order goes "
           "to one broker and a margin call is one broker's problem, so each block is "
           "readable on its own.", ""]
    for broker, group in groupby(rows, lambda r: r["broker"]):
        g = list(group)
        th, vg = _totals(g, broker)
        dp = sum(x["pnl_est"] for x in g) / len(g)
        out += [f"## {broker}", "",
                f"{len(g)} legs · mean P/L% **{dp:+.1f}%** · theta **{th:+,.1f}/day** · "
                f"vega **{vg:+,.1f}/vol-pt**", "",
                "| underlying | leg | qty | entry | mark → est | IV | **P/L% mark** | "
                "**P/L% est** | Δ | target | account |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in g:
            tgt = "—" if r["sec_type"] == "STOCK" else f"{r['target_50']:.4f}"
            ivs = f"{r['iv'] * 100:.0f}%" if r["iv"] else "—"
            # A LEG MARKED AT ITS OWN FILL IS NOT A LEG AT BREAKEVEN. build_positions prices
            # a leg from its fill when its expiry has no chain snapshot yet, which is normal
            # for one opened since the last snapshot -- so mark == entry and P/L% is exactly
            # 0.0%, indistinguishable in this table from a position genuinely flat on the
            # day. Measured 2026-10-07: three Dec-18 legs (CRWD 225P/240P, EWZ 43P) read
            # 0.0% and looked like the best-behaved rows on the book while carrying no
            # market observation at all. The source is already carried in the row; this
            # names it instead of letting a zero speak for itself.
            at_fill = r.get("mark_source") == "fill"
            leg = f"{r['leg']} ⚑fill" if at_fill else r["leg"]
            out.append(
                f"| {r['underlying']} | {leg} | {r['qty']} | {r['entry']:.4f} | "
                f"{r['mark']:.4f} → {r['est']:.4f} | {ivs} | "
                f"**{r['pnl_mark']:+.1f}%** | **{r['pnl_est']:+.1f}%** | {r['delta']:+.1f}pp | "
                f"{tgt} | {r['account']} |")
        out.append("")
    out += ["", "## The read", ""] + narrative(rows, rt_moves)
    path = root / "reports" / f"leg_estimates_{clock.today()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    return path


def console(rows, rt_moves):
    hdr = (f"{'underlying':10} {'leg':9} {'qty':>5} {'entry':>8} {'mark':>8} {'est':>8} "
           f"{'P/L% mark':>10} {'P/L% est':>9} {'Δ':>8}  account")
    for broker, group in groupby(rows, lambda r: r["broker"]):
        g = list(group)
        th, vg = _totals(g, broker)
        print(f"\n=== {broker} — {len(g)} legs · theta {th:+,.1f}/day · vega {vg:+,.1f}/vol-pt ===")
        print(hdr); print("-" * (len(hdr) + 13))
        for r in g:
            print(f"{r['underlying']:10} {r['leg']:9} {r['qty']:>5} "
                  f"{r['entry']:>8.4f} {r['mark']:>8.4f} {r['est']:>8.4f} "
                  f"{r['pnl_mark']:>9.1f}% {r['pnl_est']:>8.1f}% {r['delta']:>+7.1f}pp  {r['account']}")
    print("\n=== the read ===")
    for line in narrative(rows, rt_moves):
        print(line.replace("**", ""))
