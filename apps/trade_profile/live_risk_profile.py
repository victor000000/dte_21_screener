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

"""live_risk_profile.py — always refresh positions with real-time prices, then show risk.

This is the ONE command to run for current risk: it chains build_positions.py (real prices)
-> risk_profile.py (compute profile), ensuring you never see stale marks.

Run: uv run python apps/trade_profile/live_risk_profile.py
"""
import subprocess
import sys

def main():
    root = bootstrap.ROOT

    # Refreshing the quotes has to come FIRST. build_positions prices every leg from
    # extended_hours_quotes, and the refresh lived inside complete_risk_analysis -- which
    # runs after it -- so the book was always built one fetch behind. Measured: book
    # built 13:08:07, quotes landed 13:09:50, leaving EWZ at 41.86 in `positions` while
    # the newest quote was 42.79. Every greek and every delta_notional in the book was
    # computed at that stale spot, and the leg table then displayed the FRESH one -- so
    # the two disagreed inside one report.
    print("Step 0/3: Refreshing real-time quotes (build_positions reads these)...")
    print("=" * 80)
    result = subprocess.run(
        ["uv", "run", "--with-editable", str(bootstrap.ROOT.parent / "data_providers"), "--no-project", "--with", "duckdb", "--with", "ib_async",
         "--with", "yfinance", "--with", "futu-api", "--with", "requests",
         "python", str(root / "apps/data_ops/fetch_extended_hours_prices.py")],
        cwd=str(root)
    )
    if result.returncode != 0:
        print("\n!! quote refresh failed -- build_positions will price off the PREVIOUS "
              "quotes, which may be hours old")

    print("\nStep 1/3: Rebuilding positions from those quotes...")
    print("=" * 80)
    result = subprocess.run(
        ["uv", "run", "--with-editable", str(bootstrap.ROOT.parent / "data_providers"), "--no-project", "--with", "duckdb", "--with", "yfinance",
         "python", str(root / "apps/plan/build_positions.py")],
        cwd=str(root)
    )
    if result.returncode != 0:
        print("\n!! build_positions.py failed -- cannot generate risk profile")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("Step 2/3: Computing risk profile with current prices...")
    print("=" * 80)
    result = subprocess.run(
        ["uv", "run", "--with-editable", str(bootstrap.ROOT.parent / "data_providers"), "--no-project", "--with", "duckdb",
         "python", str(root / "apps/trade_profile/risk_profile.py")],
        cwd=str(root)
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
