# Configuration

## Dependency and runtime paths

The public lock records Data Providers 0.1.0. CI checks out exact provider commit `c32b218385d999fbeb4052c1d70bdb7ebae3b21f`. An independent native working environment has a 0.2.0.dev0 integration; do not replace the public pin with an unpublished commit. A sibling metadata change can cause `uv run --locked` to stop. Reconcile only with the intended provider version and review lock changes; do not use `--no-sync` as proof of reproducible setup.

Provider `data_home()` resolves these in order:

| Setting | Meaning and default |
| --- | --- |
| `DATA_PROVIDERS_HOME` | Explicit runtime directory, resolved from an environment value |
| `DATA_PROVIDERS_CONFIG` | Optional TOML path; default is provider `config.local.toml` |
| `[storage].home` | Runtime path in that TOML; relative paths resolve from the config directory |
| Source-tree fallback | Provider `runtime/`; installed-package fallback is `~/.local/share/data-providers` |
| `TRADING_LOGS_DIR` | Export-folder override; otherwise provider platform-specific discovery applies |

These names belong to the pinned provider runtime module. Do not put credentials, databases or broker exports in source control. This project's `.local/trading-web/orders.sqlite` is an application receipt store, not a canonical trade database.

## Server and broker settings

| Setting | Implemented behavior |
| --- | --- |
| `--port` | Server CLI argument, default 8765; binds `127.0.0.1` only |
| `TRADING_IB_PORT` | Execution-port override; takes precedence over saved paper configuration |
| `.local/trading-web/ibkr-paper.json` | If present, must contain matching `account` and integer `port` in 1–65535 |
| Execution port fallback | 4002, then 7497, when no override or saved config exists |
| `IB_MARKET_PORT` | Provider read-only IBKR quote connection port, default 4001; independent of execution |
| Execution host/client | IBKR adapter uses loopback and client ID 71 |
| `CHECK_NATIVE_REQUIRED=0` | Explicit public offline check mode; native pricing evidence is not established |

Public IBKR expected identity is `PRIVATE_ACCOUNT`; the code does not provide an environment variable to replace its account guard. Alpaca also checks a source-defined expected paper identity. An authorized operator must align the account guards and UI identity in a private configuration of the source before broker use. Changing a port alone does not authorize a different account. Never substitute the live gateway for a missing paper login.

The Alpaca adapter reads `secrets/alpaca_paper.json` from provider runtime. Required keys are `environment`, `base_url`, `key_id` and `secret`. It requires `environment="paper"` and the public paper API URL `https://paper-api.alpaca.markets/v2`. Secret values are intentionally not illustrated. Redirects are disabled. Credential loading and provider quote configuration are separate concerns.

`bootstrap` defaults `IB_HOST` and `FUTU_HOST` to loopback in native WSL only when no explicit override exists. This does not override the execution adapter's fixed loopback connection. Other provider settings must be checked in the exact pinned provider source rather than inferred from similarly named application settings.

## Browser refresh state

Enable background refresh gates page timers while the tab is visible. Broker holdings refresh on a 30-second timer in Positions/Orders/Trade logs with backoff after failure. Ticket/chain quotes and visible risk have separate 10-second controls; CN leg risk also uses a 10-second visible-page timer. Saved screening results are explicitly reloaded. Timer cadence is a request schedule, not a guarantee of fresh upstream observations.
