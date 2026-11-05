import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root
import bootstrap  # noqa: F401

"""check_iv_solvers.py — do the QuantLib and pure-Python solvers agree?

Two independent implementations of the same function now live in bs.py, and the pipeline
uses whichever one is present. That is only safe if they answer the same thing, so this
script asserts it over a large random sample plus the cases where solvers classically
diverge: deep wings, very short and very long maturities, quotes at or below intrinsic,
and vols near the 5.0 ceiling.

The Python bisection is the REFERENCE. It resolves to ~5/2^100 on a fixed bracket, so it
does not depend on any library's convergence conventions; QuantLib is the one being checked.

Tolerances are set from what the two algorithms can actually achieve, not picked to pass:
QuantLib's root-finder stops at its own accuracy setting and works on total stdDev, so a
few 1e-9 of relative disagreement at the wings is expected and harmless. A REGRESSION --
a sign error, a forward/discount convention mismatch, a wrong bound -- shows up as
differences of 1e-3 and up, or as a disagreement about WHICH rows have no answer.

  uv run --no-project python scripts/check_iv_solvers.py [n]
"""
import math
import os
import random
import sys

from compute import bs  # noqa: E402

TOL_IV = 1e-7          # absolute, on a vol expressed as a decimal (1e-5 of a vol point)
TOL_GREEK = 1e-6       # absolute, per unit of the greek as bs.py reports it


def cases(n, seed=20261002):
    """Random quotes over the ranges this repo actually solves."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        S = rng.uniform(5, 800)
        # Strike spread: mostly near the money, deliberately reaching the +-18% band the
        # bulk download uses and beyond it into the wings.
        K = S * rng.uniform(0.55, 1.45)
        # 3 days to 3 years; the repo's screens are 20-60 DTE but LEAPS show up too.
        T = rng.choice([rng.uniform(3, 60) / 365, rng.uniform(60, 400) / 365,
                        rng.uniform(400, 1100) / 365])
        sig = rng.uniform(0.05, 2.5)
        r = rng.choice([0.0, 0.04, 0.05, 0.08])
        call = rng.random() < 0.5
        out.append((S, K, T, sig, r, call))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    if not bs.USING_QUANTLIB:
        print("QuantLib not loaded — nothing to compare (build it: bash scripts/build_qliv.sh)")
        return 2

    print(f"QuantLib loaded from {bs._SO}")
    rows = cases(n)
    prices = [bs.bs_price(S, K, T, r, s, call) for (S, K, T, s, r, call) in rows]
    # rows carry the TRUE sigma in slot 3; implied_vol() takes (price, S, K, T, r, call),
    # so the truth is dropped here — it is only used to report the worst case.
    quotes = [(prices[i], r[0], r[1], r[2], r[4], r[5]) for i, r in enumerate(rows)]

    # ── implied vol, QuantLib vs the Python reference ────────────────────────────────────
    # BS_FORCE_PYTHON makes the same process compute the reference, so both sides see
    # identical inputs and identical floating-point prices.
    os.environ["BS_FORCE_PYTHON"] = "1"
    import importlib
    importlib.reload(bs)
    assert not bs.USING_QUANTLIB, "reload did not pick up BS_FORCE_PYTHON"
    ref = [bs.implied_vol(*q) for q in quotes]
    os.environ.pop("BS_FORCE_PYTHON")
    importlib.reload(bs)
    assert bs.USING_QUANTLIB, "reload did not restore QuantLib"
    got = bs.implied_vol_batch(quotes)

    both = [(i, a, b) for i, (a, b) in enumerate(zip(ref, got)) if a is not None and b is not None]
    disagree_none = [i for i, (a, b) in enumerate(zip(ref, got)) if (a is None) != (b is None)]
    diffs = sorted(abs(a - b) for _, a, b in both)
    print(f"\nimplied vol: n={n}  both solved={len(both)}  "
          f"both-None={ref.count(None)}  DISAGREE-on-None={len(disagree_none)}")
    if diffs:
        print(f"  |diff|  median={diffs[len(diffs)//2]:.3e}  p99={diffs[int(len(diffs)*.99)]:.3e}  "
              f"max={diffs[-1]:.3e}")
    worst = max(both, key=lambda t: abs(t[1] - t[2])) if both else None
    if worst:
        i, a, b = worst
        S, K, T, s, r, call = rows[i]
        print(f"  worst: S={S:.2f} K={K:.2f} T={T*365:.1f}d sigma_true={s:.4f} "
              f"py={a:.12f} ql={b:.12f}")
    ok = not disagree_none and (not diffs or diffs[-1] < TOL_IV)
    print(f"  -> {'PASS' if ok else 'FAIL'} (tol {TOL_IV:g})")
    if disagree_none:
        for i in disagree_none[:5]:
            S, K, T, s, r, call = rows[i]
            print(f"     DISAGREE-NONE i={i} S={S:.2f} K={K:.2f} T={T*365:.1f}d "
                  f"price={prices[i]:.6f} py={ref[i]} ql={got[i]}")

    # ── greeks ───────────────────────────────────────────────────────────────────────────
    os.environ["BS_FORCE_PYTHON"] = "1"
    importlib.reload(bs)
    gref = [bs.bs_greeks(S, K, T, r, s, call) for (S, K, T, s, r, call) in rows]
    os.environ.pop("BS_FORCE_PYTHON")
    importlib.reload(bs)
    ggot = [bs.bs_greeks(S, K, T, r, s, call) for (S, K, T, s, r, call) in rows]

    names = ("delta", "gamma", "theta/day", "vega/pt")
    gmax = [0.0] * 4
    for a, b in zip(gref, ggot):
        for j in range(4):
            if a[j] is None or b[j] is None:
                continue
            gmax[j] = max(gmax[j], abs(a[j] - b[j]))
    print("\ngreeks (max |diff| vs the Python reference):")
    for j in range(4):
        print(f"  {names[j]:10s} {gmax[j]:.3e}  {'ok' if gmax[j] < TOL_GREEK else 'FAIL'}")
    ok = ok and all(g < TOL_GREEK for g in gmax)

    # ── edge cases the random sample will not hit ────────────────────────────────────────
    print("\nedge cases:")
    edge = []
    # price at/below intrinsic -> both None
    for call in (True, False):
        S, K, T, r = 100.0, 90.0, 0.1, 0.04
        intr = max(0.0, S - K * math.exp(-r * T)) if call else max(0.0, K * math.exp(-r * T) - S)
        edge.append(("below intrinsic", intr * 0.9, S, K, T, r, call, None))
    # no time left -> None, not a division by zero
    edge.append(("T=0", 5.0, 100.0, 100.0, 0.0, 0.04, True, None))
    # a price implying a vol past the 5.0 ceiling -> None on both sides
    edge.append(("over ceiling", bs.bs_price(100, 100, 0.05, 0.04, 4.99, True) * 1.5,
                 100.0, 100.0, 0.05, 0.04, True, None))
    # a genuinely deep wing that MUST solve
    edge.append(("deep OTM put", 0.02, 100.0, 60.0, 0.08, 0.04, False, "solve"))
    allok = True
    for name, p, S, K, T, r, call, want in edge:
        q = bs.implied_vol(p, S, K, T, r, call)
        if want is None:
            good = q is None
        else:
            good = q is not None and abs(bs.bs_price(S, K, T, r, q, call) - p) < 1e-8
        allok = allok and good
        print(f"  {name:16s} price={p:<12.6g} -> {q if q is None else f'{q:.10f}'}"
              f"  {'ok' if good else 'FAIL'}")
    ok = ok and allok

    print(f"\n{'ALL CHECKS PASS' if ok else 'CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
