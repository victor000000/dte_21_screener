"""render.py — the CN board's report text, split out of board.py for the horizon columns.

Two things this text must not do. It must not head the table with today's date while the data
is a week old — that is what the `Data through` note is for. And it must not explain a stale
board with a hardcoded holiday: the version this replaced said "Golden Week (Oct 1-8, 2026)"
on ANY gap of two days or more, so a downloader that died silently would have been reported
as a closed exchange, and the date was wrong anyway (the exchanges closed Oct 1-7, 2026 and
reopened Oct 8). The cause now comes from the caller, read off the exchange calendar; if the
caller cannot reach it, the note says nothing rather than guessing.
"""
from apps.screener.cn_iv.windows import WINDOWS
from compute.iv_rank import MIN_POINTS
from data import clock

HORIZON_NOTE = (
    "The horizon columns rank the same latest ATM IV inside that trailing window of the same "
    "series, by `compute.iv_rank.range_rank`. `full` means the product's own history is "
    "SHORTER than the window — there is no windowed number to print, and the whole-series IVR "
    "column is its since-inception value. `n/a(n)` means the range is flat/invalid or the window holds too few points to "
    "rank. Windows are calendar days back from the last stored day, not from today's clock.")


def cell(w):
    """One horizon: the range rank, or an honest reason there is not one."""
    if w is None:
        return "-"
    if not w["covered"]:
        return "full"
    return f"{w['ivr']:.0f}" if w["ivr"] is not None else f"n/a({w['n']})"


def render(board, data_day, min_ivr, context=None):
    """The report text. The date in it is the last SESSION in the data, not today's clock."""
    stale = (clock.today() - data_day).days if data_day else None
    n_pass = sum(1 for b in board if b["res"] and b["res"]["ivr"] is not None and b["res"]["ivr"] >= min_ivr)
    n_ranked = sum(1 for b in board if b["res"] and b["res"]["ivr"] is not None)
    heads = " | ".join(label for label, _ in WINDOWS)
    L = [f"# CN option board by IVR — {clock.today()}", "",
         f"IVR = 100 * (latest IV - minimum IV) / (maximum IV - minimum IV), using each product's own series "
         f"(full history, >= {MIN_POINTS} distinct daily points), the same `compute.iv_rank.rank_series` the US screen "
         f"ranks on. IV is the VENUE's own number where the venue publishes one "
         f"(CZCE/SHFE/INE/GFEX 隐含波动率); where it does not (DCE behind a bot wall, CFFEX "
         f"MO), it is solved from the chain's last prices by compute.bs — each product is "
         f"ranked only against its own series, never across sources.", "",
         HORIZON_NOTE, ""]
    if data_day:
        note = (f"**Data through {data_day}** — {stale} day(s) behind today's clock."
                if stale else f"**Data through {data_day}**.")
        if context:
            note += " " + context
        L += [note, ""]
    L += [f"| Product | Venue | ATM IV % | IVR(full) | {heads} | history | option bars held "
          f"| flag |",
          "|---|---|---|---|" + "---|" * (len(WINDOWS) + 3)]
    for b in board:
        bar_txt = (f"{b['bars']:,} to {b['last_bar']}" if b["bars"]
                   else "**none — not tradable**")
        if b["res"] is None:
            dashes = " | ".join(["-"] * len(WINDOWS))
            L.append(f"| {b['product']} | {b['venue']} | - | - | {dashes} | "
                     f"**no IV series** | {bar_txt} | not rankable |")
            continue
        r = b["res"]
        ivr = f"{r['ivr']:.0f}" if r["ivr"] is not None else "n/a"
        flag = "PASS" if r["ivr"] is not None and r["ivr"] >= min_ivr else ("pending" if r["ivr"] is None else "")
        if b["n"] < MIN_POINTS:
            flag = f"pending ({b['n']}<{MIN_POINTS})"
        iv_pct = f"{r['iv'] * 100:.1f}" if r["iv"] is not None else "n/a"
        cells = " | ".join(cell(b["windows"].get(label)) for label, _ in WINDOWS)
        L.append(f"| {b['product']} | {b['venue']} | {iv_pct} | {ivr} | {cells} | "
                 f"{b['n']} from {b['since']} | {bar_txt} | {flag} |")
    L += ["", f"Pass at IVR >= {min_ivr:.0f}: {n_pass} of {n_ranked} rankable "
              f"({len(board)} products in cn_product_map)"]
    unranked = [b["product"] for b in board if b["res"] is None]
    if unranked:
        L += ["", "**Not rankable: no IV series stored** — " + ", ".join(unranked) +
              ". A product lands here when its venue publishes no IV and the solver path has "
              "not covered it yet; it is a gap in our data, not a reading of the market."]
    dupes = [b for b in board if b["others"]]
    if dupes:
        L += ["", "Products with a second stored series (the longest usable one above is the one "
                  "ranked): " + "; ".join(f"{b['product']} also has {', '.join(b['others'])}"
                                          for b in dupes)]
    return "\n".join(L) + "\n"
