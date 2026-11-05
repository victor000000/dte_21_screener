import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root
import bootstrap  # noqa: F401

from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap below.

"""risk_profile_check.py — recheck the risk profile against the book it claims to describe.

WHY THIS EXISTS. On 2026-10-06 the risk profile was wrong four times in one session, and every
time it presented as a plausible number rather than an error: a book that still held a rolled
position, spots taken from the previous session's close, a Dec-18 leg carrying a Nov-20 row's
greeks, and a profile computed from a different set of spots than the marks beside it. None of
those raised anything. They were found by hand, one at a time, by recomputing.

Each of those is a check here, so the next session starts from evidence:

  BOOK      the book is non-empty, carries a vintage, and every leg has a mark and a spot
  GREEKS    every stored greek reproduces from that leg's own (mark, spot, IV)
  SPOT      where each spot came from is recorded, and how many are NOT real-time
  IV        every US leg's IV is solvable, sane, and near its expiry's ATM IV
  REPORT    reports/risk_profile_<date>.md actually describes THIS book
  CONSIST   leg_estimates (an independent path) agrees with positions
  PROFIT    the profitable short legs, ranked by how little profit sits in front of the risk

THE TWO MODES, and the difference matters:

  (default)   verify the book already in the database. No network, deterministic -- this is
              what a commit gate can run.
  --live      refresh quotes and rebuild the book FIRST, then verify. This is the one that
              uses a real-time price, and the only one that can catch a stale book, because
              a stale book and a fresh one are bit-identical to a verifier that does not
              refetch. Requires the market-data sources (TWS, Tiingo, yfinance, Alpaca).

A non-real-time spot is a WARN, not a FAIL. On this book it is the normal state outside
regular hours whenever TWS is down, and China has no quote feed at all -- failing on it
would block every commit during a gateway restart, which teaches people to bypass the gate.
But it is never silent: the counts and the tickers are printed either way.

Exit code is non-zero when anything FAILs, so it can gate a chain.

    uv run python apps/audit/risk_profile_check.py [--live] [--quiet]
"""
import argparse
import datetime as dt
import re
import statistics
import subprocess
import sys

import duckdb

from data import clock

from compute.bs import bs_greeks, bs_price, implied_vol, T_years

ROOT = bootstrap.ROOT
from shared.rates import FX_CNY as FXCNY, R_US, SHOCKS
from apps.trade_profile import mark_provenance  # noqa: E402
from apps.audit import check_close_cost  # noqa: E402
from apps.audit import check_mark_provenance  # noqa: E402
from apps.audit import check_broker_list  # noqa: E402

results = []          # (group, check, verdict, detail)
fail_count = 0


def add(group, check, ok, detail, warn=False):
    global fail_count
    verdict = "PASS" if ok else ("WARN" if warn else "FAIL")
    if verdict == "FAIL":
        fail_count += 1
    results.append((group, check, verdict, detail))


def is_cn(broker):
    return broker == "浙商期货"


def fx_of(broker):
    return FXCNY if is_cn(broker) else 1.0


# ── the checks ───────────────────────────────────────────────────────────────────────────

def load_book(con):
    """Every live leg, with the columns every check below needs (indices are positional)."""
    return con.execute("""
        SELECT broker, underlying, sec_type, expiry, strike, call_put, qty, spot, multiplier,
               mark, delta_units, gamma_units, theta_day, vega_pt, delta_notional_usd,
               spot_source, spot_class, spot_is_realtime, as_of, avg_price, mark_obs,
               mark_source, bid, ask
        FROM positions WHERE qty <> 0
        ORDER BY broker, underlying, expiry, strike""").fetchall()


def check_book(book):
    if not book:
        add("BOOK", "positions table is non-empty", False, "no live legs — nothing to check")
        return
    add("BOOK", "positions table is non-empty", True, f"{len(book)} legs")

    # ONE BUILD, ONE VINTAGE -- but not by exact equality. as_of is a column DEFAULT, so
    # each row takes its own current_timestamp and a build's rows differ by microseconds.
    # Testing `len(set(...)) == 1` failed every healthy book, which is how a check teaches
    # people to ignore it. The question is whether the legs were built together, so the
    # spread is what matters.
    vintages = sorted(r[18] for r in book if r[18])
    if not vintages:
        add("BOOK", "every leg carries a build vintage", False, "positions.as_of is empty")
    else:
        spread = (vintages[-1] - vintages[0]).total_seconds()
        add("BOOK", "every leg carries one build vintage", spread <= 60,
            f"as_of {vintages[-1]:%Y-%m-%d %H:%M} UTC (spread {spread:.1f}s over {len(book)} legs)")

    missing = [f"{r[1]} {r[4]:g}{r[5]}" for r in book if r[7] is None or r[9] is None]
    add("BOOK", "every leg has a spot and a mark", not missing,
        "all present" if not missing else f"missing on {missing[:4]}")

    # GREEKS TOO. Checked here, at the top, so a NULL is a NAMED finding -- every
    # arithmetic below has to defend itself against one, and three separate checks were
    # crashing on the same leg before this existed.
    nogreek = [f"{r[1]} {r[4]:g}{r[5]}" for r in book
               if r[2] == "OPT" and None in (r[10], r[11], r[12], r[13])]
    add("BOOK", "every option leg carries all four greeks", not nogreek,
        "all present" if not nogreek else f"NULL greeks on {nogreek[:4]}")


def check_greeks(book, quiet):
    """Each leg's greeks must reproduce from ITS OWN mark, spot and IV.

    This is the check that would have caught the Dec-18/Nov-20 mix-up: that leg's greeks
    were internally consistent with a mark and a spot that did not belong to it, and the
    only way to see it is to re-derive them from the row's own fields and compare.
    """
    bad = []
    for r in book:
        b, u, st, e, k, cp, q, s, mult, m, du, gu, th, v = r[:14]
        if st != "OPT" or is_cn(b):
            continue
        if s is None or m is None:
            bad.append(f"{u} {k:g}{cp}: no spot/mark")
            continue
        # T AT THE LEG'S OWN VINTAGE, not at today's date. The greeks were computed when the
        # book was built, and T enters them as both sqrt(T) and 1/sqrt(T): on a 45-day option
        # one day of decay moves theta 2.3%, past this check's 2% tolerance -- so reproducing
        # against a LATER T went red at every UTC midnight while the stored numbers were
        # exactly right (CRWD 230P 2026-10-07: vintage T 0.00%, today's T 2.34%).
        T = T_years(e, r[18].date() if r[18] else None)
        iv = implied_vol(m, s, k, T, R_US, cp == "C")
        if iv is None:
            bad.append(f"{u} {k:g}{cp}: no IV from mark {m} at spot {s}")
            continue
        d, g, th_, v_ = bs_greeks(s, k, T, R_US, iv, cp == "C")
        for name, got, want in (("delta", du, d), ("gamma", gu, g),
                                ("theta", th, th_), ("vega", v, v_)):
            want_tot = None if want is None else want * q * 100
            if got is None or want_tot is None:
                # NULL IS A FINDING, NOT A CRASH. This comparison reaches the subtraction
                # below and the `:.4g` in the message, and both raise on None -- so a leg
                # with no delta turned the whole gate into a traceback instead of a
                # verdict, and a traceback reports nothing about the other 24 checks. It
                # is the same `qty * None` that once killed an entire build_positions run.
                bad.append(f"{u} {k:g}{cp} {name}: stored {got!r}, expected {want_tot!r}")
                continue
            if abs(got - want_tot) > max(1e-4, abs(want_tot) * 0.02):
                bad.append(f"{u} {k:g}{cp} {name}: stored {got:.4g} vs {want_tot:.4g}")
    add("GREEKS", "every stored greek reproduces from mark+spot+IV", not bad,
        "all legs" if not bad else f"{len(bad)} mismatched: " + "; ".join(bad[:3]))
    if bad and not quiet:
        for x in bad[:8]:
            print(f"      {x}")

    # delta_notional must be du*spot, FX-converted for China. A leg that fails this has a
    # delta notional describing a different position size than the one beside it.
    def not_multiplied(r):
        # NULL delta, spot or notional cannot satisfy du*spot, and doing the arithmetic
        # on one raises instead of reporting -- the same crash as above, at the other end
        # of the check. A missing greek IS a mismatch here.
        if r[10] is None or r[7] is None or r[14] is None:
            return True
        return abs(r[10] * r[7] / fx_of(r[0]) - r[14]) > max(1.0, abs(r[14]) * 0.001)

    nbad = [f"{r[1]} {r[4]:g}{r[5]}" for r in book if not_multiplied(r)]
    add("GREEKS", "delta_notional == delta_units * spot", not nbad,
        "all legs" if not nbad else f"{len(nbad)} off: {nbad[:4]}")

    # A leg whose IV could not be solved is written with ALL greeks zero rather than being
    # dropped, and build_positions says so. Here it must not pass silently: a zero delta on
    # a short call understates the position.
    dead = [f"{r[1]} {r[4]:g}{r[5]}" for r in book
            if r[2] == "OPT" and not is_cn(r[0])
            and not any((r[10], r[11], r[12], r[13]))]
    add("GREEKS", "no leg is silently all-zero greeks", not dead,
        "none" if not dead else f"{dead[:4]} — risk UNDERSTATED", warn=bool(dead))


def check_spots(con, book, quiet):
    unstamped = sorted({r[1] for r in book if r[15] is None})
    add("SPOT", "every spot records where it came from", not unstamped,
        "all stamped" if not unstamped else f"no spot_source on {unstamped}")

    stale = sorted({(r[1], r[15] or "?", r[16] or "?") for r in book if not r[17]})
    n_all = len({r[1] for r in book})
    detail = ("every underlying priced in real time" if not stale else
              f"{len({u for u, _, _ in stale})}/{n_all} NOT real time: "
              + ", ".join(f"{u} ({s}, {c})" for u, s, c in stale))
    # WARN, not FAIL: outside RTH this is the normal state when TWS is down, and MA701 has
    # no quote feed on this box at all. The user's rule is "real-time by default", and a
    # default that cannot be met must be visible rather than fatal.
    add("SPOT", "spots are real-time unless named", not stale, detail, warn=bool(stale))

    # THE STALENESS CHECK, and the reason --live exists: a book built hours ago and a book
    # built a minute ago verify identically from the rows alone.
    vint = max((r[18] for r in book if r[18]), default=None)
    if vint is None:
        add("SPOT", "book vintage is recent vs its quotes", False, "no vintage to compare")
        return
    # ASK THIS ONLY ABOUT SPOTS THAT WERE NOT LIVE. `extended_hours_quotes` is written by
    # fetch_extended_hours_prices.py, a DIFFERENT job, and `build_positions` does not read
    # it -- it takes its US spots straight from TWS at build time. So comparing the build
    # clock against that table measures the OTHER job's lag, not this book's freshness: on
    # 2026-10-06 it warned that CRWD, EWZ, META and TLT were "priced up to 45 min before
    # the build" when every one of their spots was a live TWS read taken AT the build
    # (`spot_source='TWS'`, `spot_is_realtime=True`, stamped seconds before `as_of`).
    #
    # The rows carry their own answer, and the check above already reports it. What this
    # adds is a MAGNITUDE, for the underlyings that genuinely were not live -- which is
    # exactly when the age of the last capture is worth knowing.
    unsure = sorted({r[1] for r in book if r[6] is not None and not r[17]})
    if not unsure:
        add("SPOT", "book vintage is recent vs its quotes", True,
            "every spot was live at the build")
        return
    rows = con.execute("""
        SELECT ticker, max(timestamp_utc) FROM extended_hours_quotes
        WHERE ticker IN (SELECT DISTINCT underlying FROM positions WHERE qty <> 0)
        GROUP BY 1""").fetchall()
    if not rows:
        add("SPOT", "book vintage is recent vs its quotes", True,
            f"{len(unsure)} not live, but no capture to age them against")
        return
    gaps = {t: (vint - ts).total_seconds() / 60 for t, ts in rows if ts and t in unsure}
    worst = max(gaps.values()) if gaps else 0.0
    add("SPOT", "book vintage is recent vs its quotes", True,
        f"{', '.join(unsure)} not live; last capture up to {worst:.0f} min before the build"
        if gaps else f"{', '.join(unsure)} not live; no capture for them",
        warn=bool(gaps))


def check_iv(book, quiet):
    """IV must be solvable, sane, and near its expiry's ATM IV.

    The ATM comparison is the one that catches a mark belonging to a different contract:
    a single leg whose vol sits far off the smile of its own expiry is either a bad mark or
    the wrong row entirely, and both price the leg wrongly.
    """
    legs = [r for r in book if r[2] == "OPT" and not is_cn(r[0]) and r[7] and r[9]]
    ivs = {}
    for r in legs:
        iv = implied_vol(r[9], r[7], r[4], T_years(r[3]), R_US, r[5] == "C")
        if iv is not None:
            ivs[(r[0], r[1], r[3], r[4], r[5])] = iv
    unsolvable = [f"{r[1]} {r[4]:g}{r[5]}" for r in legs
                  if (r[0], r[1], r[3], r[4], r[5]) not in ivs]
    add("IV", "every US leg has a solvable IV", not unsolvable,
        f"{len(legs)} legs" if not unsolvable else f"no IV on {unsolvable[:4]}")

    insane = [f"{u} {k:g}{c} {v*100:.0f}%" for (b, u, e, k, c), v in ivs.items()
              if not (0.01 <= v <= 4.0)]
    add("IV", "IV is inside a plausible band (1-400%)", not insane,
        "all inside" if not insane else f"outside: {insane[:4]}")

    outliers = []
    for (b, u, e, k, c), v in ivs.items():
        smile = [iv2 for (b2, u2, e2, k2, c2), iv2 in ivs.items()
                 if u2 == u and e2 == e and b2 != "浙商期货"]
        if len(smile) < 3:
            continue
        # A REAL MEDIAN. The first version was `sorted(smile, key=lambda x: abs(x-0.4))[len//2]`
        # -- the middle element when ordered by distance from 40%, which is not a median of
        # anything and on a 4-leg expiry picks an essentially arbitrary member.
        atm = statistics.median(smile)
        if abs(v - atm) > 0.25:          # 25 vol points off the expiry's own smile
            outliers.append(f"{u} {k:g}{c} {v*100:.0f}% vs expiry median {atm*100:.0f}%")
    add("IV", "no leg's IV is far off its expiry's smile", not outliers,
        "none" if not outliers else f"{outliers[:3]} — mark may belong to another contract",
        warn=bool(outliers))
    if outliers and not quiet:
        for x in outliers:
            print(f"      {x}")


def check_report(book, quiet):
    """The markdown report must describe THIS book.

    It is a separate artifact written by a separate script, so it can lag the book it names.
    Reading it is not enough -- the headline and the whole scenario ladder are recomputed
    here from `positions` and compared.
    """
    # `clock.today()`, not `dt.date.today()`. Both return the UTC date IN THIS PROCESS
    # only because bootstrap pins TZ=UTC at import -- `risk_profile` writes the report
    # with clock.today(), this looks for it by name, and two files that name one artifact
    # must ask the same clock. The rule is clock.py's own: use it for anything STORED,
    # COMPARED against a stored stamp, or used to NAME an artifact.
    today = clock.today().isoformat()
    path = ROOT / "reports" / f"risk_profile_{today}.md"
    if not path.exists():
        add("REPORT", "today's risk profile report exists", False, f"missing {path.name}")
        return
    text = path.read_text()

    def leg_pnl(r, shock):
        b, spot, du, gu = r[0], r[7], r[10], r[11]
        if spot is None or du is None:
            return 0.0
        dS = spot * shock
        return (du * dS + 0.5 * (gu or 0) * dS * dS) / fx_of(b)

    # `or 0`: a leg whose delta_notional is NULL contributes nothing to the sum, and
    # BOOK below names it. Without the guard this is the THIRD crash of the same shape --
    # `sum()` over a book containing one None reports a TypeError instead of 24 verdicts.
    want_delta = sum(r[14] or 0 for r in book)
    want_gross = sum(abs(r[14] or 0) for r in book)
    # THE FRACTION IS PART OF THE NUMBER: fmt() prints one decimal below $1,000, so a flat
    # book renders "$988.1" — unmatched by an integer-only pattern (2026-10-07, TLT roll).
    m = re.search(r"Delta notional: \$(-?[\d,]+(?:\.\d+)?)\*\* \(gross \$([\d,]+(?:\.\d+)?)\)", text)
    if not m:
        add("REPORT", "report headline matches the book", False, "no headline found")
    else:
        got_delta = float(m.group(1).replace(",", ""))
        got_gross = float(m.group(2).replace(",", ""))
        ok = (abs(got_delta - want_delta) < 1.0 and abs(got_gross - want_gross) < 1.0)
        add("REPORT", "report headline matches the book", ok,
            f"delta {got_delta:,.0f} vs {want_delta:,.0f}, gross {got_gross:,.0f} vs {want_gross:,.0f}")

    row = [l for l in text.splitlines() if l.startswith("| P&L $ |")]
    if not row:
        add("REPORT", "report scenario ladder matches the book", False, "no ladder found")
        return
    got = [float(x.replace(",", "")) for x in
           row[0].replace("| P&L $ |", "").replace("|", "").split()]
    want = [sum(leg_pnl(r, s) for r in book) for s in SHOCKS]
    off = [(g, w) for g, w in zip(got, want) if abs(g - w) > 1.0]
    # The header's claim about what its option prices ARE -- the one line in the report
    # no arithmetic covers. See check_mark_provenance.py.
    check_mark_provenance.check(text, book, add, mark_provenance)
    # What closing would cost against the mid every P&L above is measured at.
    check_close_cost.check(text, book, add, fx_of)

    add("REPORT", "report scenario ladder matches the book", not off,
        f"all {len(SHOCKS)} points" if not off else f"{len(off)} off: {off[:3]}")
    if off and not quiet:
        print(f"      report {[round(x) for x in got]}")
        print(f"      book   {[round(x) for x in want]}")


def check_leg_table(book, quiet):
    """The report must carry a PER-LEG profit table, and its numbers must be the book's.

    Asked for on 2026-10-06. The aggregate tables cannot be acted on: an order goes to one
    broker for one contract, and the >=50% close rule is read per leg. Until this table
    existed, the per-leg profit was recomputed by hand every time it was wanted -- and the
    hand-written query filtered sec_type='OPT', which silently dropped BOTH China legs
    ('FUT_OPT') from every leg table given for an entire session.

    Presence alone is not the check: a table of wrong numbers is present. Each row's profit
    is recomputed from `positions` (entry, mark, qty, and the row's OWN multiplier, so a
    CZCE leg at 10 is not scored as a 100) and compared as a multiset, which is robust to
    the report's ordering.
    """
    path = ROOT / "reports" / f"risk_profile_{clock.today().isoformat()}.md"
    if not path.exists():
        add("LEGS", "report carries a per-leg profit table", False, f"missing {path.name}")
        return
    text = path.read_text()
    marker = "## Legs — profit and estimate"
    if marker not in text:
        add("LEGS", "report carries a per-leg profit table", False,
            f"no '{marker}' section — the leg profit is not reported")
        return
    section = text.split(marker, 1)[1]
    for stop in ("\n### ", "\n## "):
        if stop in section:
            section = section.split(stop, 1)[0]

    # Columns: 0 Broker · 1 Leg · 2 Qty · 3 Entry · 4 Mark(observed) · 5 P&L % ·
    #          6 Est. mark · 7 Est. P&L % · 8 Est. P&L $ · 9 flag
    got = []
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| Broker"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 9:
            continue
        try:
            got.append((float(cells[2]), float(cells[3].replace(",", "")),
                        float(cells[4].replace(",", "")), float(cells[6].replace(",", "")),
                        float(cells[5].rstrip("%")), float(cells[7].rstrip("%")),
                        float(cells[8].replace(",", ""))))
        except ValueError:
            continue

    want = []
    for r in book:
        # `load_book`'s indices, not the report's: qty 6, multiplier 8, mark 9, avg_price 19,
        # mark_obs 20.
        entry, mult, mark, obs, qty = r[19], r[8] or 100, r[9], r[20], r[6]
        if entry is None or mark is None:
            continue
        obs = mark if obs is None else obs
        fx = fx_of(r[0])
        pnl = ((entry - mark) if qty < 0 else (mark - entry)) * abs(qty) * mult / fx
        pct = lambda m: (entry - m) / entry * 100 if qty < 0 else (m - entry) / entry * 100
        want.append((float(qty), round(entry, 3), round(obs, 3), round(mark, 3),
                     round(pct(obs), 1), round(pct(mark), 1), round(pnl, 1)))

    if len(got) != len(want):
        add("LEGS", "every leg appears in the report's table", False,
            f"{len(got)} rows in the report, {len(want)} legs in the book"
            + (" — the hand-written version of this table dropped the China legs" if len(got) < len(want) else ""))
    else:
        add("LEGS", "every leg appears in the report's table", True, f"{len(got)} legs")

    # BOTH marks and BOTH percentages, because each is a separate claim about the same leg:
    # the observed one is what the contract traded at, the estimated one is that repriced at
    # today's spot. Checking only the second would pass while the report printed a stale
    # observed mark, and "P&L % and estimated P&L %" is the pair that has to hold.
    #
    # Sorted-then-zipped: if the two multisets are equal, sorting each the same way aligns
    # them exactly, and any difference shows up as a reported mismatch rather than silently.
    FIELDS = [(1, "entry", 0.001), (2, "observed mark", 0.001), (3, "estimated mark", 0.001),
              (4, "P&L %", 0.15), (5, "estimated P&L %", 0.15), (6, "Est. P&L $", 1.0)]
    A, B = sorted(got), sorted(want)
    for idx, label, tol in FIELDS:
        bad = [f"qty {g[0]:g} entry {g[1]:g}: report {g[idx]:g} vs book {w[idx]:g}"
               for g, w in zip(A, B) if abs(g[idx] - w[idx]) > tol]
        add("LEGS", f"every row's {label} reproduces from the book", not bad,
            f"all {len(got)} rows" if not bad else f"{len(bad)} off: " + "; ".join(bad[:3]))
        if bad and not quiet:
            for x in bad[:3]:
                print(f"      {x}")


def check_leg_estimates(con, book):
    """leg_estimates is an INDEPENDENT estimate path. It must agree with positions.

    It did not on 2026-10-06: build_positions changed what `mark` means (a live-spot
    estimate rather than a source mark) while leg_estimates still anchored the IV at a
    chain-snapshot spot, so it valued EWZ's 43 call at 77% IV and $4.83 against a mark of
    2.47 -- a 1.80 mean disagreement. Only a cross-path comparison shows that.
    """
    try:
        rows = con.execute("""
            SELECT underlying, strike, call_put, mark, est_price FROM leg_estimates
            WHERE run_ts = (SELECT max(run_ts) FROM leg_estimates) AND sec_type = 'OPT'""").fetchall()
    except duckdb.Error as e:
        add("CONSIST", "leg_estimates agrees with positions", False, repr(e)[:80], warn=True)
        return
    if not rows:
        add("CONSIST", "leg_estimates agrees with positions", False,
            "no leg_estimates run recorded", warn=True)
        return
    # ONLY COMPARE LIKE WITH LIKE. leg_estimates is a separate run that reads the book, so
    # if the book has been REBUILT since (a new live spot, a new mark), every leg differs --
    # correctly. Comparing across the two vintages failed 12 legs at up to 0.21 and called
    # it a defect, when it was one script being 40 minutes older than the other. The
    # comparison is only meaningful when leg_estimates ran at or after this book was built.
    run_ts = con.execute("SELECT max(run_ts) FROM leg_estimates").fetchone()[0]
    vint = max((r[18] for r in book if r[18]), default=None)
    if run_ts and vint and run_ts < vint:
        add("CONSIST", "leg_estimates agrees with positions", False,
            f"leg_estimates ran {run_ts:%H:%M} but the book was rebuilt {vint:%H:%M} — "
            f"re-run it against the current book", warn=True)
        return
    pos = {(r[1], r[4], r[5]): r[9] for r in book if r[2] == "OPT" and r[9] is not None}
    diffs = [(u, k, c, m, e, pos.get((u, k, c)))
             for u, k, c, m, e in rows
             if pos.get((u, k, c)) is not None and e is not None
             and abs(e - pos[(u, k, c)]) > 0.05]
    add("CONSIST", "leg_estimates agrees with positions", not diffs,
        f"{len(rows)} legs agree within 0.05"
        if not diffs else f"{len(diffs)} legs disagree, worst "
                          f"{max(abs(d[4] - d[5]) for d in diffs):.2f}: "
                          + ", ".join(f"{d[0]} {d[1]:g}{d[2]}" for d in diffs[:3]))


def report_profit_legs(book, quiet):
    """Profitable short legs, ranked by how little profit sits in front of the risk.

    Informational, never a verdict: this is the table the close-or-hold decision is read
    off, and on this book the answer has been the same three legs every run. Printed rather
    than asserted, because "risky" is a judgement and a threshold here would be an invention.
    """
    rows = []
    for r in book:
        b, u, st, e, k, cp, q, s, mult, m, entry = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[19]
        if q >= 0 or st != "OPT" or not s or not m or not entry:
            continue
        T = T_years(e)
        iv = implied_vol(m, s, k, T, R_US, cp == "C")
        if iv is None:
            continue
        fx = fx_of(b)
        mult = mult or 100
        profit = (entry - m) * abs(q) * mult / fx       # short: profit when the mark falls
        if profit <= 0:
            continue
        # A short PUT is hurt by a FALL, a short CALL by a RISE. Getting this backwards
        # makes the safest leg in the book look like the riskiest -- it did, in the first
        # version of this table.
        sign = -1 if cp == "P" else 1
        cushion = (s - k) / s * 100 if cp == "P" else (k - s) / s * 100
        adv = {mv: (entry - bs_price(s * (1 + sign * mv / 100), k, T, R_US, iv, cp == "C"))
               * abs(q) * mult / fx for mv in (3, 5, 10)}
        rows.append((profit / max(abs(adv[5]), 1e-9), u, e, k, cp, profit, iv, cushion, sign, adv))

    if not rows:
        add("PROFIT", "profitable short legs (informational)", True, "none in profit")
        return
    rows.sort()
    add("PROFIT", "profitable short legs (informational)", True,
        f"{len(rows)} legs; most exposed: " + ", ".join(
            f"{u} {k:g}{cp}" for _, u, e, k, cp, *_ in rows[:3]))
    if quiet:
        return
    print(f"\n  {'profitable short leg':26}{'profit':>9}{'IV':>7}{'cushion':>9}"
          f"{'@3%':>9}{'@5%':>9}{'@10%':>10}  profit/5%loss")
    for ratio, u, e, k, cp, profit, iv, cushion, sign, adv in rows:
        d = "v" if sign < 0 else "^"
        print(f"  {u + ' ' + e.strftime('%m-%d') + ' ' + format(k, 'g') + cp:26}"
              f"{profit:>9,.0f}{iv*100:>7.1f}{cushion:>8.1f}%"
              f"{adv[3]:>8,.0f}{d}{adv[5]:>8,.0f}{d}{adv[10]:>9,.0f}{d}{ratio:>13.2f}")
    print("  v = a FALL hurts (short put) · ^ = a RISE hurts (short call) · "
          "ratio is profit per $1 of 5% adverse loss")


# ── modes ────────────────────────────────────────────────────────────────────────────────

def live_refresh():
    """Refresh quotes and rebuild the book. This is the part that needs a real-time price."""
    # THE REPORT IS PART OF THE REFRESH, and leaving it out made --live fail every time --
    # correctly. Rebuilding the book from new quotes without regenerating the report leaves
    # the two describing different books, and the REPORT checks caught that immediately
    # (headline -54,970 against a book of -57,040). That is the same class of defect the
    # checks exist for, so the fix belongs here rather than in the checks: refresh, rebuild,
    # REGENERATE, then verify.
    steps = [
        ("quotes", [ROOT / "apps/data_ops/fetch_extended_hours_prices.py"]),
        ("book", [ROOT / "apps/plan/build_positions.py"]),
        ("report", [ROOT / "apps/trade_profile/risk_profile.py"]),
        # leg_estimates too, so the CONSIST check compares two paths over the SAME book. It
        # is an independent implementation (its own IV anchoring, its own reprice), which is
        # the only reason comparing it to `positions` means anything -- it found the
        # regression of 2026-10-06 that no self-consistency check could see. Left stale it
        # warns forever and the warn stops being read.
        # Via the shim, not the package path: `uv run python <dir>` does not work, and the
        # shim is the stable entry point for every split module. See scripts/leg_estimates.py.
        ("leg estimates", [ROOT / "scripts/leg_estimates.py"]),
    ]
    ok = True
    for name, argv in steps:
        cmd = ["uv", "run", "--with-editable", str(bootstrap.ROOT.parent / "data_providers"), "--no-project", "--with", "duckdb", "--with", "ib_async",
               "--with", "yfinance", "--with", "futu-api", "--with", "alpaca-py",
               "--with", "requests", "python", str(argv[0])]
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            print(f"  !! {name} step failed (exit {r.returncode})")
            ok = False
            break
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="refresh quotes and rebuild the book first (needs the market data "
                         "sources; this is the mode that uses a real-time price)")
    ap.add_argument("--quiet", action="store_true", help="verdicts only")
    args = ap.parse_args()

    if args.live:
        print("refreshing quotes and rebuilding the book (real-time)…")
        if not live_refresh():
            print("  live refresh FAILED — verifying the existing book instead")

    db_path = bootstrap.DATA_ROOT / "trades.duckdb"
    if not db_path.exists():
        print("  SKIP — no trades.duckdb in this checkout, so there is no book to recheck.")
        print("         This is the normal state in CI: the databases are gitignored and a")
        print("         runner has the code and none of the data. Run it on the box that")
        print("         holds the book, or with --live where the market data is reachable.")
        return 0

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.IOException as e:
        # DuckDB allows ONE writer per file, and a read-only open of a file a writer holds
        # does not attach -- it raises. --fast exists precisely to be safe while a download
        # holds a database, so a blocked read must SKIP: failing here would make the gate
        # red every time a download runs, which is exactly when someone wants to run it.
        print(f"  SKIP — trades.duckdb is locked by another process ({str(e)[:60]}…).")
        print("         A writer holds it; this is not a defect. Re-run when it is quiet.")
        return 0
    book = load_book(con)

    check_book(book)
    if book:
        check_greeks(book, args.quiet)
        check_spots(con, book, args.quiet)
        check_iv(book, args.quiet)
        check_broker_list.check(con, book, add)
        check_report(book, args.quiet)
        check_leg_table(book, args.quiet)
        check_leg_estimates(con, book)
        report_profit_legs(book, args.quiet)
    con.close()

    if not args.quiet:
        print()
    for group, check, verdict, detail in results:
        print(f"[{verdict:4}] {group:8} {check:44} {detail}")

    # COUNT THE VERDICT FIELD, and count it the same way `add` does. The first version
    # unpacked the tuple as `for *_, v in [...]` against a list of 4-tuples, so `v` was the
    # DETAIL string -- n_fail was always 0, the summary printed "0 fail" while FAIL lines
    # scrolled past above it, and the script exited 0. A gate that cannot fail is the exact
    # shape scripts/check_all.sh documents at the top of its own file (the pipefail bug).
    n_fail = fail_count
    n_warn = sum(1 for r in results if r[2] == "WARN")
    print(f"\n{len(results)} checks · {len(results) - n_fail - n_warn} pass · "
          f"{n_warn} warn · {n_fail} fail")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
