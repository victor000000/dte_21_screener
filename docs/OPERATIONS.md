# Operations and recovery

## State and service boundaries

The application runs natively. The server binds loopback; provider services and gateways are independently operated. Starting the server creates `.local/trading-web/orders.sqlite` with mode 0600. Canonical market data and credentials remain under provider runtime. Saved screens/analysis live under application `reports/`; public source ships neither live state nor the native pricing library.

`make trading-web` starts a foreground local server. This is an operational command, not a documentation check. The public repository supplies no deployment unit, automation registration or automatic rollback service. Do not restart an existing process or provider job just to verify a command in a guide.

## Submission recovery

1. Open **Orders**, select the original paper broker and refresh. Preserve the original client reference. A local receipt in `submitting` or `unknown` blocks further submissions for that broker. The receipt list contains its latest 100 submissions.
2. The refreshed snapshot checks the orders returned by that broker for the same reference. A match changes the local receipt to `submitted`. Read the broker's order status and fills to determine whether it was working, rejected, canceled or filled. An acknowledged transmission can still have a rejected broker status.
3. If the snapshot has no matching reference, check order history directly with the same broker and account. Compare the reference, contract, side and quantity. The snapshot covers a limited history, so absence leaves the receipt unresolved. Preserve the database and obtain operator reconciliation before another submission. A new review, a restart or deleting the receipt cannot establish the outcome.

Review tokens live in memory for two minutes. Receipt evidence persists across process restarts when the service uses the same application database. A cancellation request also needs broker confirmation. [Paper order lifecycle](WORKFLOWS.md#paper-order-lifecycle)

### Back up receipts before maintenance

The live store belongs to the **application checkout**, even when `DATA_PROVIDERS_HOME` points elsewhere. From the running service's source root, set `RECEIPT_BACKUP_DIR` to an existing private backup directory outside the checkout. This example opens the source read-only and uses SQLite's online backup API so committed WAL data is included. It creates a new backup and verifies its integrity without printing receipt contents.

```bash
uv run --locked python - <<'PY'
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

os.umask(0o077)
source = Path(".local/trading-web/orders.sqlite").resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(source, uri=True)) as live:
    folder = Path(tempfile.mkdtemp(prefix="trading-web-", dir=os.environ["RECEIPT_BACKUP_DIR"]))
    backup = folder / "orders.sqlite"
    with closing(sqlite3.connect(backup)) as saved:
        live.backup(saved)
        if saved.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SystemExit("Receipt backup failed verification")
print(backup)
PY
```

## Troubleshooting

| Symptom | Inspect | Correct next step |
| --- | --- | --- |
| `uv` reports stale lock | Provider metadata vs CI/public pin and editable path | Restore intended matching source or review an authorized lock update; avoid dependency-wide upgrades |
| No saved candidates | Saved JSON/CSV report date, status filter, source gaps | Inspect failed gates and provider coverage; zero qualified is not zero inventory |
| Wrong account or paper unavailable | Private paper settings, account reported by the broker, execution port | Verify the configured binding and follow the authorized restart procedure. |
| Risk unavailable | Unsupported holdings/currency, timestamps, source history | Resolve missing inputs; do not interpret as zero risk |
| Quotes missing/stale | Entitlement, feed/session, event time vs receipt | Keep the quality label; a reconnect or fresh receipt alone does not certify the book |
| Auto-refresh stopped | Background switch, per-panel switch, visibility, in-flight request/backoff | Check these controls before treating timer inactivity as an upstream outage |
| Review expired | Two-minute lifetime or account/draft edit | Deliberately review the current draft again |
| Submission uncertain | Persistent receipt and original reference | Reconcile existing broker order before any further submission |

## Release and migration

Workspace v0.5.3 clears an underlying quote request when the ticker or catalog source changes. It also requires [private paper account bindings](CONFIGURATION.md#paper-account-binding) before broker review or order operations. Versions 0.5.2 and 0.5.3 use the same submissions schema. Browser reloads discard the in-memory ticket draft. [Source release procedure](DEVELOPMENT.md#source-release)

For an authorized update or source rollback, record the current source commit, reconcile open submissions and take a private receipt backup. Restore the reviewed source in the service checkout with its pinned provider dependency, preserving `.local/trading-web/`. `Service` resolves `.local/trading-web/orders.sqlite` relative to its checkout, so starting a second checkout with an empty `.local` creates a new order history and loses sight of existing submission blocks. If moving the service, stop the original instance during the maintenance window and verify the new checkout uses the reconciled receipt store before paper operations resume. An older backup may predate later submissions. Broker orders and provider publications keep their own histories.

After an authorized restart, compare the reviewed source version with the running loopback service. This check prints only the version field. Set the port to the configured value if it differs from 8765.

```bash
uv run --locked python - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8765/api/session", timeout=3) as response:
    print(json.load(response)["version"])
PY
```

Use the archive checksum and GitHub commit to identify the exact source revision. The version endpoint identifies the running workspace version. The native installation has no retained application container for rollback.
