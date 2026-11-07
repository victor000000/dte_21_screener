# Operations and recovery

## State and service boundaries

The application runs natively. The server binds loopback; provider services and gateways are independently operated. Starting the server creates `.local/trading-web/orders.sqlite` with mode 0600. Canonical market data and credentials remain under provider runtime. Saved screens/analysis live under application `reports/`; public source ships neither live state nor the native pricing library.

`make trading-web` starts a foreground local server. This is an operational command, not a documentation check. The public repository supplies no deployment unit, automation registration or automatic rollback service. Do not restart an existing process or provider job just to verify a command in a guide.

## Submission recovery

If a submit request fails or the process exits during transmission, preserve the local SQLite receipt store and the original client reference. A `submitting`/`unknown` receipt blocks more submissions for that broker until reconciled. Refreshing a broker snapshot can match an acknowledged broker order reference and update the receipt. In-memory review tokens expire or disappear on restart; persistent submission evidence survives.

Do not recreate a ticket merely because an HTTP acknowledgement is missing. Compare the reference, exact contract, direction, quantity and broker status. An explicit rejection differs from an unknown transmission. Cancellation is a broker request, not proof of cancellation. Do not delete receipts to clear a block. Manual operator reconciliation is required when automated reference matching cannot resolve the state.

Before an independently authorized maintenance change, inspect outstanding submissions and broker working orders, preserve a consistent private SQLite backup (including WAL consistency), and coordinate a quiet window. This is a review requirement, not authorization to restart or trade. Protect backups as sensitive records and keep them outside public source.

## Troubleshooting

| Symptom | Inspect | Correct next step |
| --- | --- | --- |
| `uv` reports stale lock | Provider metadata vs CI/public pin and editable path | Restore intended matching source or review an authorized lock update; avoid dependency-wide upgrades |
| No saved candidates | Saved JSON/CSV report date, status filter, source gaps | Inspect failed gates and provider coverage; zero qualified is not zero inventory |
| Wrong account / paper unavailable | Source guard, saved paper config, port precedence | Configure authorized exact paper identity; never fall back to a live execution session |
| Risk unavailable | Unsupported holdings/currency, timestamps, source history | Resolve missing inputs; do not interpret as zero risk |
| Quotes missing/stale | Entitlement, feed/session, event time vs receipt | Keep the quality label; a reconnect or fresh receipt alone does not certify the book |
| Auto-refresh stopped | Background switch, per-panel switch, visibility, in-flight request/backoff | Check these controls before treating timer inactivity as an upstream outage |
| Review expired | Two-minute lifetime or account/draft edit | Deliberately review the current draft again |
| Submission uncertain | Persistent receipt and original reference | Reconcile existing broker order before any further submission |

## Release and migration

Public v0.5.2 changes navigation, draft visibility, ticker handoff and risk request presentation. It introduces no receipt schema migration or provider storage migration. Reloading clears an in-memory draft. Updating source does not establish which Python version an already-running process loaded; static assets may change independently. Version evidence must distinguish source, runtime endpoint and hosted CI SHA.

Historical native Docker retirement means no application container rollback is retained. Source rollback is not rollback of broker orders, provider publications or receipt evidence. No recovery command here replays protected provider requests, copies canonical stores or deletes data.
