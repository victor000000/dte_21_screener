"""COMPATIBILITY SHIM — implementation is maintained in the data-providers package."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import bootstrap  # noqa: F401

if __name__ == "__main__":
    import runpy
    runpy.run_module("data_providers.jobs.trades.fetch_tws_executions", run_name="__main__")
else:
    import importlib
    sys.modules[__name__] = importlib.import_module("data_providers.jobs.trades.fetch_tws_executions")
