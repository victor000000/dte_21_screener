"""narrative.py — the read, in plain language, derived only from the numbers.

Pure: it takes the collected rows and the underlying moves and returns lines. No
database, no network, no globals -- which is what makes the thresholds in
constants.py testable without a book.
"""
from .constants import HARVEST, NEAR, STALE
from apps.trade_profile import mark_provenance


def narrative(rows, rt_moves):
    """The read, in plain language, derived only from the numbers above."""
    opts = [r for r in rows if r["sec_type"] != "STOCK"]
    L = []
    over = sorted([r for r in opts if r["pnl_est"] >= HARVEST], key=lambda r: -r["pnl_est"])
    near = sorted([r for r in opts if HARVEST - NEAR <= r["pnl_est"] < HARVEST],
                  key=lambda r: -r["pnl_est"])
    worst = sorted(opts, key=lambda r: r["pnl_est"])[:2]

    if over:
        L.append("**Past the 50% target — these are closes, not holds.**")
        for r in over:
            gap = ""
            if r["pnl_mark"] < HARVEST:
                gap = (f" The stored mark still reads {r['pnl_mark']:+.1f}%, so on the mark "
                       f"alone you would not have flagged it — the underlying moved and the "
                       f"mark has not caught up.")
            L.append(f"- **{r['underlying']} {r['leg']}** ({r['broker']}, {r['qty']}x) at "
                     f"**{r['pnl_est']:+.1f}%** on the model.{gap}")
    else:
        L.append("**Nothing is past the 50% target yet.**")

    if near:
        L.append("")
        L.append("**Approaching it** (within 10 points): " + ", ".join(
            f"{r['underlying']} {r['leg']} {r['pnl_est']:+.1f}% ({r['broker']})" for r in near) + ".")

    if worst and worst[0]["pnl_est"] < 0:
        L.append("")
        L.append("**The loss that matters.**")
        for r in worst:
            if r["pnl_est"] >= 0:
                continue
            L.append(f"- **{r['underlying']} {r['leg']}** ({r['broker']}, {r['qty']}x) at "
                     f"**{r['pnl_est']:+.1f}%**"
                     + (f", against {r['pnl_mark']:+.1f}% on the mark — the underlying moved "
                        f"{rt_moves.get(r['underlying'], 0):+.1f}% and the leg went through "
                        f"the strike." if abs(r["delta"]) >= STALE else "."))

    stale = [r for r in rows if abs(r["delta"]) >= STALE]
    if stale:
        L.append("")
        L.append("**Where the mark and the model disagree (≥5pp)** — the underlying's move "
                 "since the marks were taken, so the model column is the live one:")
        for r in sorted(stale, key=lambda x: -abs(x["delta"])):
            L.append(f"- {r['underlying']} {r['leg']} ({r['broker']}): "
                     f"{r['pnl_mark']:+.1f}% → {r['pnl_est']:+.1f}% ({r['delta']:+.1f}pp)")

    L.append("")
    L.append("The model holds IV fixed, so it prices the underlying's move and not the vol "
             "move that came with it — read it as a direction, not a level.")
    # WHAT THE MARKS ARE, computed from the rows. This sentence was hardcoded to "the last
    # stored snapshot, not a live quote" and stayed that way through the change that put the
    # US legs on the broker's live two-sided book -- the same stale assertion the risk
    # profile's header carried, made in a second file. See mark_provenance.py.
    if rows:
        L.append("On the marks: " + mark_provenance.sentence([r.get("mark_source") for r in rows])
                 + ".")
    return L
