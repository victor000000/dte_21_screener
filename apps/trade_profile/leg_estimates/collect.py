"""collect.py — one dict per leg, every number computed exactly once."""
from compute import bs
from data import clock
from apps.trade_profile.targets import analyze

from .constants import R


def mark_spot(con, underlying, strike, call_put):
    """The spot of the newest snapshot holding this strike — NOT the mark's spot any more.

    NO LONGER USED as the IV anchor: positions.mark is now a price at the LIVE spot, so
    anchoring it here paired two different moments (see the comment in collect()). Left in
    place for anything that wants a snapshot spot, but note the join matches strike and
    call_put WITHOUT the expiry — the same bug that was live in build_positions on
    2026-10-06, where a Dec-18 leg silently took a Nov-20 row's greeks and mark. Fix that
    before using this for anything that prices a leg.
    """
    row = con.execute("""
        SELECT s.spot FROM chain_snapshots s
        JOIN chain_rows r ON r.snap_id = s.snap_id AND r.strike = ? AND r.call_put = ?
        WHERE s.underlying = ? ORDER BY s.ts_utc DESC LIMIT 1""",
        [strike, call_put, underlying]).fetchone()
    return row[0] if row and row[0] else None


def collect(con, account=None):
    """One dict per leg, every number computed exactly once."""
    q = "SELECT * FROM positions WHERE qty <> 0" + (" AND account = ?" if account else "")
    cols = [d[0] for d in con.execute("DESCRIBE positions").fetchall()]
    out = []
    for r in con.execute(q, [account] if account else []).fetchall():
        L = dict(zip(cols, r))
        entry, model, qty = L["avg_price"] or 0.0, L["mark"] or 0.0, L["qty"]
        # MARK IS THE OBSERVATION; `model` IS THE OTHER COLUMN. build_positions writes
        # `mark` as a price at TODAY'S live spot (mark_source='model' whenever the chain had
        # no live book) and keeps the price the source actually gave in `mark_obs`. Reading
        # `mark` here put a model number under a label that promises a fact, and made delta
        # identically 0.0pp on every leg: the module rendered one number twice, and its own
        # "where the mark and the model disagree" section could never fire. Measured
        # 2026-10-07 -- six CRWD legs, up to 7.5pp apart (230P read -57.3% against a real last
        # price of -61.4%). mark_obs is NULL only when nothing priced the leg at all.
        mark = L["mark_obs"] if L["mark_obs"] is not None else model
        a = analyze(entry, mark, qty)
        row = {"account": L["account"], "broker": L["broker"], "underlying": L["underlying"],
               "expiry": L["expiry"], "sec_type": L["sec_type"], "qty": qty,
               "entry": entry, "mark": mark, "mark_model": model, "rt_spot": L["spot"],
               # Carried so the narrative can say what the marks ARE instead of asserting
               # it. See mark_provenance.py -- that assertion went stale in two files.
               "mark_source": L["mark_source"],
               "pnl_mark": a["pnl_pct"], "target_50": a["target_50"],
               "strike": L["strike"], "call_put": L["call_put"],
               "theta": L["theta_day"], "vega": L["vega_pt"],
               "leg": "STOCK" if L["sec_type"] == "STOCK" else f"{L['strike']:g}{L['call_put']}"}
        if L["sec_type"] == "STOCK":
            row.update(iv=None, est_mark_spot=None,
                       est=L["spot"],
                       pnl_est=((L["spot"] or 0) / entry - 1) * 100 if entry else 0.0)
        else:
            T = max((L["expiry"] - clock.today()).days, 1) / 365.0
            # SOLVE FROM `model`, NEVER FROM `mark`. `model` is a price AT today's live spot
            # (build_positions writes it that way), so the IV solved from it against that
            # same spot is the IV actually behind the leg today, and est round-trips to it.
            # `mark` is a price from an OLDER spot; pairing IT with the live spot is the
            # 2026-10-06 bug -- EWZ's Nov-20 43 call came back 77.4% IV and $4.83 against a
            # mark of 2.47, and META's 850 call $17.55 against 13.05.
            iv = (bs.implied_vol(model, L["spot"], L["strike"], T, R, L["call_put"] == "C")
                  if (model and L["spot"]) else None)
            est = bs.bs_price(L["spot"], L["strike"], T, R, iv, L["call_put"] == "C") if (iv and L["spot"]) else None
            if est is None or est != est:
                est = model         # nothing to say: the estimate IS the current price
            row.update(iv=iv, est=est, est_mark_spot=L["spot"],
                       pnl_est=analyze(entry, est, qty)["pnl_pct"])
        row["delta"] = row["pnl_est"] - row["pnl_mark"]
        out.append(row)
    # Broker first. The same contract is held at two brokers, and a broker's book is
    # what you act on -- an order goes to one broker, and a margin call is one broker's
    # problem. Sorting by underlying interleaved them, so reading down the table meant
    # switching accounts on almost every row.
    out.sort(key=lambda x: (x["broker"], x["underlying"], x["strike"] or 0,
                            x["call_put"] or "", x["account"]))
    return out
