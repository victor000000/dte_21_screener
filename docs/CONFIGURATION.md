# Configuration

## Dependency and runtime paths

The public lockfile expects Data Providers 0.1.0 as an editable sibling. Use the revision in the [setup instructions](../README.md#start-here) to reproduce CI. Changing provider package metadata can invalidate the lock even when the directory name is correct.

The provider's `data_home()` resolves storage in three steps.

1. `DATA_PROVIDERS_HOME` specifies the runtime directory directly.
2. Otherwise the provider looks for the TOML file named by `DATA_PROVIDERS_CONFIG`, or `config.local.toml` in its source root. An existing file must contain `[storage].home`. Relative storage paths resolve from the TOML file's directory.
3. If the config file is absent, a source checkout uses its own `runtime/` directory. The installed-package fallback is `~/.local/share/data-providers`.

For example, this configuration selects a `runtime` directory beside the TOML file.

```toml
[storage]
home = "runtime"
```

`TRADING_LOGS_DIR` separately selects the external broker export directory. The provider applies platform-specific discovery when it is unset. The screener keeps paper-submission evidence in `.local/trading-web/orders.sqlite` under its own source root. Keep provider configuration, exports, databases and receipt backups in private storage. [Operations and recovery](OPERATIONS.md#submission-recovery)

## Server and broker settings

| Setting | Implemented behavior |
| --- | --- |
| `--port` | Server CLI argument, default 8765. Binds `127.0.0.1`. |
| `.local/trading-web/ibkr-paper.json` | Private JSON with the IBKR paper `account` and optional integer `port` from 1 to 65535. |
| `TRADING_IB_PORT` | Overrides the saved execution port. The private account binding remains required. |
| Execution port fallback | 4002, then 7497, when an account is configured and neither port setting is present. |
| `IB_MARKET_PORT` | Provider read-only IBKR quote port, default 4001. |
| Execution host and client | IBKR uses loopback and client ID 71. |
| `CHECK_NATIVE_REQUIRED=0` | Skips the native-library assertion in public CI. Pricing still uses the installed provider library when available. |

### Paper account binding

The service loads the private settings at startup. Restart during an authorized
maintenance window after changing the account binding, credentials or execution
port. The research pages can run with neither paper account configured.

- **Alpaca.** In the provider runtime's `secrets/alpaca_paper.json`, set
  `environment` to `paper` and `base_url` to
  `https://paper-api.alpaca.markets/v2`. Supply the exact paper `account_number`,
  `key_id` and `secret`. The adapter refuses redirects and checks the account
  number returned by the paper endpoint before order submission or cancellation.
- **IBKR.** Set `account` to the exact paper account ID in
  `.local/trading-web/ibkr-paper.json`. This workspace requires a `DU` prefix
  followed by digits. It accepts a separate execution session only when the
  managed-account list contains that account alone. [IBKR native API paper example](https://www.interactivebrokers.com/campus/ibkr-quant-news/getting-started-with-the-interactive-brokers-native-api/)

Either broker refuses operations when its binding is missing, invalid or
mismatched. Keep the credential files and account identifiers in private
storage. The browser's broker labels are generic. The review and confirmation
display the account returned by the selected broker.

`bootstrap` defaults `IB_HOST` and `FUTU_HOST` to loopback in native WSL only when no explicit override exists. This does not override the execution adapter's fixed loopback connection. Other provider settings must be checked in the exact pinned provider source rather than inferred from similarly named application settings.

## Browser refresh state

The **Enable background refresh** switch controls polling while the tab is visible. Broker holdings refresh on a 30-second timer in Positions/Orders/Trade logs with backoff after failure. Ticket/chain quotes and visible risk have separate 10-second controls; CN leg risk also uses a 10-second visible-page timer. Saved screening results are explicitly reloaded. Timer cadence is a request schedule, not a guarantee of fresh upstream observations.
