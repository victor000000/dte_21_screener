"""profit_targets.py — COMPATIBILITY SHIM. The real module is apps.trade_profile.profit_targets.

Kept so both invocation styles keep working during the data/application split:

    uv run python scripts/profit_targets.py ...   (forwards to __main__)
    import profit_targets                                                    (aliases the real module)

Is anything still using this? `python scripts/shim_status.py` answers it.
Do NOT hand-grep for the name: the shim's own docstring contains it, so the
grep always finds this file -- and the real module's usage example names the
old path too. Both were counted as "referenced" for months.
That tool sees IN-REPO references only. A shim is also an entry point a human
or an external script may call by path, which no grep can see, so treat its
"no references" as necessary, not sufficient.
"""
import pathlib
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    # Run as a script: hand over to the real module's __main__.
    runpy.run_module("apps.trade_profile.profit_targets", run_name="__main__")
else:
    # Imported: ALIAS, do not copy. Replacing the sys.modules entry means `import profit_targets`
    # returns the REAL module object, so identity, private names and reload all behave:
    #   * `importlib.reload(profit_targets)` reloads the real module (check_iv_solvers.py relies on
    #     this to re-read BS_FORCE_PYTHON -- a copy-based shim silently ignored the reload);
    #   * `profit_targets._SO` and friends stay reachable, which a `from ... import *` copy drops
    #     because it skips underscore-prefixed names;
    #   * there is no second, stale copy of module state to drift out of sync.
    import apps.trade_profile.profit_targets as _m
    sys.modules[__name__] = _m
