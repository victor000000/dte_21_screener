"""leg_estimates.py — COMPATIBILITY SHIM. The real module is apps.trade_profile.leg_estimates.

Kept so both invocation styles keep working during the data/application split:

    uv run python scripts/leg_estimates.py ...   (forwards to __main__)
    import leg_estimates                          (aliases the real module)

Is anything still using this? `python scripts/shim_status.py` answers it.
Do NOT hand-grep for the name: the shim's own docstring contains it, so the
grep always finds this file. That tool sees IN-REPO references only; a shim is
also an entry point a human or an external script may call by path.
"""
import pathlib
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    # Run as a script: hand over to the package's __main__.
    runpy.run_module("apps.trade_profile.leg_estimates", run_name="__main__")
else:
    # Imported: ALIAS, do not copy -- see scripts/selfcheck.py for why identity matters.
    import apps.trade_profile.leg_estimates as _m
    sys.modules[__name__] = _m
