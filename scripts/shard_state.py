"""shard_state.py — COMPATIBILITY SHIM. Maintenance is owned by data-providers."""
import importlib
import pathlib
import runpy
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    runpy.run_module("data_providers.ops.shard_state", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("data_providers.ops.shard_state")
