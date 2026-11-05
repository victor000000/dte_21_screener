"""COMPATIBILITY SHIM — provider-owned database timestamp audit."""
import importlib
import pathlib
import runpy
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
if __name__ == "__main__":
    runpy.run_module("data_providers.jobs.audit.utc_repair",run_name="__main__")
else:
    sys.modules[__name__]=importlib.import_module("data_providers.jobs.audit.utc_repair")
