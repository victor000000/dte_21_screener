"""Price provider-delivered CN holdings; run in the native WSL environment.

Raw broker sides independently determine signed quantity. Chain midpoints are
indicative when the provider omits option event timestamps. No acquisition or
canonical data writes occur here.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compute import bs
import duckdb

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--fx-report", type=Path, required=True,
                        help="Saved provider-backed risk report containing dated FX")
    args = parser.parse_args()
    assert bs.USING_QUANTLIB, "Native QuantLib required"
    folder = args.handoff.parent
    manifest = json.loads(args.handoff.read_text())
    for item in manifest.get("files", []):
        assert hashlib.sha256((folder / item["name"]).read_bytes()).hexdigest() == item["sha256"], item["name"]
    fx_meta = json.loads(args.fx_report.read_text())["fx"]
    fx = float(fx_meta["CNY_per_USD"])
    assert math.isfinite(fx) and fx > 0
    connection = duckdb.connect(str(folder / manifest["duckdb"]), read_only=True)

    def records(table):
        result = connection.execute("select * from " + table)
        keys = [col[0] for col in result.description]
        return [dict(zip(keys, row)) for row in result.fetchall()]

    held = records("held_legs")
    quotes = {row["canonical_id"]: row for row in records("option_quotes")}
    underlyings = {row["underlying_contract"]: row for row in records("underlying_quotes")}
    connection.close()
    raw_bytes = (folder / "cn_tracker_positions.raw").read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            raw_text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Cannot decode raw holdings")
    raw = {row["持仓合约"]: row for row in csv.DictReader(io.StringIO(raw_text))
           if row.get("持仓合约") and not row["持仓合约"].startswith("合计")}
    assert len(raw) == len(held)
    legs, errors, differences = [], [], []
    for holding in held:
        symbol = holding["contract_source"]
        try:
            from apps.trade_profile.value_handoff_leg import value_handoff_leg
            value_handoff_leg(args, differences, fx, holding, legs, quotes, raw, symbol, underlyings)
        except (ValueError, TypeError, KeyError, AssertionError) as exc:
            errors.append(dict(symbol=symbol, error=str(exc), type=type(exc).__name__))
    totals = defaultdict(lambda: dict(dollar_delta_usd=0., gamma_pnl_1pct_usd=0., legs=0))
    for leg in legs:
        aggregate = totals[(leg["broker"], leg["account"], leg["future"])]
        for field in ("dollar_delta_usd", "gamma_pnl_1pct_usd"):
            aggregate[field] += leg[field]
        aggregate["legs"] += 1
    report = dict(valuation_date=args.date.isoformat(), source_handoff=str(args.handoff),
                  status="indicative; option event times absent; holdings are older exports",
                  engine="Native QuantLib European Black76; calendar-day maturity; rate 2% assumed",
                  fx=fx_meta, sign_discrepancies=differences, errors=errors,
                  legs=sorted(legs, key=lambda r: (r["broker"], r["ticker"], r["future"], r["symbol"])),
                  futures=[dict(broker=k[0], account=k[1], future=k[2], **v) for k, v in sorted(totals.items())],
                  validation="Each modeled mark and finite-difference delta/gamma checked",
                  limitations=manifest["blockers"])
    out = ROOT / "reports" / ("cn_risk_legs_" + args.date.isoformat())
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    if legs:
        with out.with_suffix(".csv").open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(report["legs"][0]))
            writer.writeheader()
            writer.writerows(report["legs"])
    print(json.dumps(dict(report=str(out.with_suffix(".json")), legs=len(legs),
                          errors=errors, sign_discrepancies=differences,
                          validation=report["validation"], futures=report["futures"]),
                     ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit("Missing/invalid inputs: see errors in saved report")

if __name__ == "__main__":
    main()
