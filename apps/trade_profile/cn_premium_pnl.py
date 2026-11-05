"""Rank provider-held CN legs using their dated top-of-book closing prices.

No network access, native Greek assumptions, FX, or multiplier references needed.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    handoff = json.loads(args.handoff.read_text())
    folder = args.handoff.parent
    for item in handoff["files"]:
        assert hashlib.sha256((folder / item["name"]).read_bytes()).hexdigest() == item["sha256"], item["name"]

    def rows(connection, table):
        cursor = connection.execute("select * from " + table)
        keys = [col[0] for col in cursor.description]
        return [dict(zip(keys, values)) for values in cursor.fetchall()]

    with duckdb.connect(str(folder / handoff["duckdb"]), read_only=True) as connection:
        holdings = rows(connection, "held_legs")
        quotes = {row["canonical_id"]: row for row in rows(connection, "option_quotes")}
    # Resolve broker labels without treating a quote receipt as a holdings update.
    with duckdb.connect(str(folder.parents[3] / "trades.duckdb"), read_only=True) as connection:
        brokers = connection.execute("select distinct account,broker from broker_positions where currency='CNY'").fetchall()
    broker_map = {}
    for account, broker in brokers:
        assert account not in broker_map or broker_map[account] == broker
        broker_map[account] = broker
    now = dt.datetime.now(dt.timezone.utc)
    result = []
    assert len(quotes) == len(holdings)
    for holding in holdings:
        native = json.loads(holding["raw_json"])
        side = native["买卖"].strip()
        assert side in {"买", "卖"}
        qty = float(native["总仓"]) * (1 if side == "买" else -1)
        assert qty == holding["signed_contracts"] and qty != 0
        entry = float(native["开仓均价"])
        assert math.isfinite(entry) and entry > 0
        quote = quotes[holding["canonical_id"]]
        assert quote["venue"] == holding["venue"]
        assert quote["underlying_contract"] == holding["underlying_contract"]
        raw_quote = json.loads(quote["raw_json"])
        assert float(raw_quote[7]) == holding["strike"]
        for index, key in ((0, "bid_size"), (1, "bid"), (3, "ask"), (4, "ask_size")):
            assert float(raw_quote[index]) == quote[key]
        assert 0 < quote["bid"] <= quote["ask"] and min(quote["bid_size"], quote["ask_size"]) > 0
        source_time = dt.datetime.strptime(raw_quote[32], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        assert source_time == dt.datetime.fromisoformat(quote["source_quote_utc"])
        close = quote["ask"] if qty < 0 else quote["bid"]
        size = quote["ask_size"] if qty < 0 else quote["bid_size"]
        pnl_pct = 100 * (close - entry) / entry * (1 if qty > 0 else -1)
        result.append(dict(broker=broker_map[native["用户代码"]], account=native["用户代码"],
                           ticker=holding["product"], future=holding["underlying_contract"],
                           symbol=holding["contract_source"], canonical_id=holding["canonical_id"],
                           qty=qty, entry_premium=entry, close_quote=close,
                           close_side="ask" if qty < 0 else "bid", close_size=size,
                           visible_size_covers_qty=size >= abs(qty), premium_pnl_pct=pnl_pct,
                           option_bid=quote["bid"], option_ask=quote["ask"],
                           option_source_utc=quote["source_quote_utc"],
                           option_source_shanghai=source_time.isoformat(),
                           received_utc=quote["received_utc"],
                           age_seconds_at_report=(now - source_time).total_seconds(),
                           feed_mode=quote["feed_mode"],
                           holdings_file_modified_utc=holding["source_modified_utc"]))
    result.sort(key=lambda row: (row["broker"], row["account"], row["premium_pnl_pct"]))
    metadata = dict(generated_utc=now.isoformat(), source_handoff=str(args.handoff),
                    source_capture_receipt_utc=handoff["source_capture_receipt_utc"],
                    source_quote_range_utc=[min(row["option_source_utc"] for row in result),
                                            max(row["option_source_utc"] for row in result)],
                    interpretation="Latest-available dated snapshot; not verified realtime",
                    formula="Short:100*(entry-ask)/entry; long:100*(bid-entry)/entry",
                    denominator="Absolute entry premium, not margin; quantity cancels",
                    validation="All manifest hashes, raw signed quantities, entry costs, exact quote identities/strikes, native book fields and timestamps checked",
                    limitations=handoff["blockers"] + ["Top-of-book estimates exclude fees, slippage and depth beyond the displayed size"],
                    legs=result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
    args.output.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
