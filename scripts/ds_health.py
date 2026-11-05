#!/usr/bin/env python
"""ds_health.py — probe every datasource this repo pulls from, in one pass.

Split across three files for the 100-line cap: this CLI, `ds_probe.py` (local services) and
`ds_probe_http.py` (HTTP + Alpaca entitlement).

Exit status: 0 when every REQUIRED source answers, 1 otherwise, so it can gate a run.

    uv run python scripts/ds_health.py [--json] [--quick]
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root

from scripts.ds_probe import RESULTS, probe_futu, probe_ibkr, probe_thetadata  # noqa: E402
from scripts.ds_probe_http import probe_alpaca, probe_http  # noqa: E402


def run_all(quick=False):
    """Probe everything. Returns (results, [required sources that are down])."""
    RESULTS.clear()
    probe_ibkr(quick)
    probe_futu(quick)
    probe_thetadata(quick)
    probe_alpaca()
    probe_http()
    down = [r["source"] for r in RESULTS if r["required"] and not r["ok"]]
    return list(RESULTS), down


def render(results, down, as_json=False):
    if as_json:
        return json.dumps({"when": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "results": results, "required_down": down}, indent=2)
    out = [f"=== datasource health  {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} ==="]
    for r in results:
        tag = "OK  " if r["ok"] else ("DOWN" if r["required"] else "warn")
        out.append(f"  [{tag}] {r['source']:<14} {r['secs']:>6.2f}s  {r['detail']}")
    if down:
        out.append(f"\n  REQUIRED DOWN: {', '.join(down)}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quick", action="store_true", help="skip protocol handshakes")
    args = ap.parse_args()
    results, down = run_all(args.quick)
    print(render(results, down, args.json))
    return 1 if down else 0


if __name__ == "__main__":
    sys.exit(main())
