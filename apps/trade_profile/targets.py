"""targets.py — the 50% profit-target arithmetic, in one place.

WHY THIS EXISTS. Five files each implemented "how far is this leg from its 50%
target", and a review of all five found they agreed -- but only by luck of
repetition, and two of them (hit_probability, risk_profile_with_profit_targets)
implemented only the SHORT half while the other three implemented both. A sixth
copy, or an edit to one of the five, would have introduced a disagreement that no
test would catch: the numbers would simply differ, quietly, between two reports
describing the same book.

The direction rule, which is the thing worth stating once:

  short leg   you sold it, so profit is the mark FALLING. Target is half the
              credit received: target = 0.5 * entry.
  long leg    you paid for it, so profit is the mark RISING. +50% on the debit:
              target = 1.5 * entry.

`distance` is always "percent the mark still has to move to reach the target",
signed so that positive means room remaining.
"""
from __future__ import annotations


def target_price(entry: float, qty: int) -> float:
    """Option price at which the leg is 50% to target. See the direction rule above."""
    return entry * 0.5 if qty < 0 else entry * 1.5


def pnl_pct(entry: float, mark: float, qty: int) -> float:
    """P&L as a percentage of the entry price, signed so positive is profit."""
    if not entry:
        return 0.0
    if qty < 0:
        return (entry - mark) / entry * 100.0
    return (mark - entry) / entry * 100.0


def distance_to_target(mark: float, target: float, qty: int) -> float:
    """Percent the mark still has to move to reach `target`. Positive = room left."""
    if not mark:
        return 0.0
    if qty < 0:
        return (mark - target) / mark * 100.0
    return (target - mark) / mark * 100.0


def analyze(entry: float, mark: float, qty: int) -> dict:
    """Everything the reports need for one leg, from one implementation."""
    tgt = target_price(entry, qty)
    return {
        "target_50": tgt,
        "pnl_pct": pnl_pct(entry, mark, qty),
        "distance": distance_to_target(mark, tgt, qty),
        "reached": pnl_pct(entry, mark, qty) >= 50.0,
    }


def days_to_target(mark: float, target: float, qty: int, theta_day: float | None,
                   n_contracts: int, multiplier: float = 100) -> float | None:
    """Rough days for theta alone to carry the leg to target.

    theta_day is the POSITION theta in $/day (build_positions stores qty*theta*mult),
    so it is divided by the contract count to get a per-contract figure, matching
    the per-contract dollar gap. Returns None when theta is absent or points the
    wrong way -- a leg whose theta does not help has no theta-based estimate, and
    returning a number there would be inventing one.

    `multiplier` is the contract size from the book: 100 for US options, **10 for CZCE
    methanol**, 1 for stock. It was hardcoded to 100, which is a tenfold error the day a
    MA701 leg reaches here -- the same mistake that was live in complete_risk_analysis.py
    and live_profit_targets.py. Defaulted rather than required so existing callers keep
    working. NB: as of 2026-10-06 this function has no callers anywhere in the repo; it is
    kept because deleting someone else's API is their call, not mine.
    """
    if not theta_day or not n_contracts or not qty:
        return None
    per_contract = theta_day / abs(qty)
    gap = abs(mark - target) * (multiplier or 100)
    if per_contract == 0 or (qty < 0 and per_contract > 0) or (qty > 0 and per_contract < 0):
        return None
    return gap / abs(per_contract)
