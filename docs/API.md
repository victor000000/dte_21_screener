# Local HTTP interface

This interface is for the loopback workspace. It has no remote-user authentication contract. Server routes are allowlisted; arbitrary source/runtime files are not exposed. Host must match `localhost:<port>` or `127.0.0.1:<port>`. POST also requires an exact allowed Origin, `X-Workspace-Token` from GET `/api/session`, Content-Type `application/json`, and a JSON object body of 1–20,000 bytes. A session token rotates when the process restarts. Do not save it in docs or logs.

## GET routes

| Route | Query / result | Effects |
| --- | --- | --- |
| `/api/session` | version, token, mode=paper | Local session information |
| `/api/snapshot` | broker=alpaca (default) or ibkr; account/positions/orders/fills | Broker I/O; may reconcile local uncertain receipts against broker references |
| `/api/receipts` | broker | Read filtered local submission receipts |
| `/api/screening` | mode=matches/high_ivr/all, search, offset 0–100000 | Saved reports, 100-row pages; no acquisition |
| `/api/attribution` | optional day | Saved attribution evidence; no regeneration |
| `/api/data/status` | provider status | Provider operations status interface |
| `/api/data/plan` | action, default all | Provider job preview and digest |
| `/api/market/connections` | connection evidence | Can query connection status |
| `/api/market/underlying` | symbol | Provider-backed observations and timestamped reference context |
| `/api/market/expiries` | source=alpaca/ibkr, symbol | Listed expiries; may fetch upstream |
| `/api/market/chain` | source, symbol, expiry, right=P/C, optional low/high/cursor/feed/delayed/multi | Bounded listed chain and quote evidence |
| `/api/market/quotes` | symbols (1–20 comma-separated standard OCC symbols), source=auto/alpaca/ibkr, feed=auto/opra/indicative, delayed=true | Provider-backed exact-leg quotes |
| `/api/cn/catalog`, `/api/cn/screen`, `/api/cn/positions` | provider catalog, derived screen or positions/risk | Cached provider reads |
| `/api/cn/chain` | venue, product, month, live=true | Provider-backed chain request |
| `/api/cn/leg-risk` | refresh=true requests an update | May acquire quotes and write application evidence |

A GET is not necessarily side-effect-free: snapshot can reconcile receipts, quote routes can acquire data and CN leg risk can persist analysis. Do not use endpoint calls merely as prose validation.

## POST routes

| Route | Body keys | Meaning |
| --- | --- | --- |
| `/api/risk` | broker=ibkr, optional ticket | Broker holdings and modeled risk request; no order submission |
| `/api/review` | broker, legs, limit, effect; optional quote_source/quote_feed/quote_delayed | Validated review token, ticket and broker/quote/risk evidence |
| `/api/submit` | token, account, quote_ack boolean | Real paper transmission with persistent idempotent receipt |
| `/api/cancel` | broker, id | Broker cancellation request |
| `/api/data/start` | action, request_id, digest | Provider-owned job execution following preview |

A ticket contains 1–4 legs with underlying, expiry (ISO date), right (P/C), strike, qty and intent. Intents are buy_to_open/sell_to_open/buy_to_close/sell_to_close. Roots use 1–6 uppercase letters; quantities are 1–100 whole contracts. The limit must be positive, <=10000 and at most two decimal places; effect is debit or credit. Other identity/ratio/holding guards live in `tickets.normalize` and broker validation. A valid JSON shape alone does not establish eligibility.

Expected failures include 400 for validation, 403 for origin/token/host checks, 404 for unknown ordinary routes and 502 for upstream/service failures. Do not assume every unknown nested route is 404; market/provider dispatch can return validation errors. Generic failures redact raw exception detail. After a failed submit response, inspect its existing reference and broker evidence rather than creating a replacement order.
