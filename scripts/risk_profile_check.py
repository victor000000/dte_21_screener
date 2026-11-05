"""risk_profile_check.py — COMPATIBILITY SHIM. The real module is apps.audit.risk_profile_check.

Kept so both invocation styles keep working during the data/application split:

    uv run python scripts/risk_profile_check.py ...   (forwards to __main__)
    import risk_profile_check                          (aliases the real module)

Is anything still using this? `python scripts/shim_status.py` answers it.
Do NOT hand-grep for the name: the shim's own docstring contains it, so the
grep always finds this file.
"""
import pathlib
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    # Run as a script: hand over to the real module's __main__.
    runpy.run_module("apps.audit.risk_profile_check", run_name="__main__")
else:
    # Imported: ALIAS, do not copy -- see scripts/selfcheck.py for why identity matters.
    import apps.audit.risk_profile_check as _m
    sys.modules[__name__] = _m
