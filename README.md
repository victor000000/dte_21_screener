# DTE 21 Screener

Options screening, position and trade-log analysis, management reports, and a local paper-trading workspace. Workspace version **0.5.2** comes from `apps/trading_web/__init__.py`; the root package's `0.0.0` is packaging metadata.

## Start here

Use Linux/WSL with uv, Python 3.14 (the checked-in `.python-version`) and Node 22 for UI tests. Python metadata allows >=3.11; CI validates 3.14. Place the provider source beside this checkout. For the reproducible public baseline:

```bash
git clone https://github.com/victor000000/data_providers.git ../data_providers
git -C ../data_providers checkout c32b218385d999fbeb4052c1d70bdb7ebae3b21f
uv sync --locked
uv run --locked python -m apps.trading_web.server --help
```

Do not clone over an existing provider checkout. Check its version and lock compatibility instead. The editable dependency is required even for tests; this is not a standalone source tree.

When deliberately starting the application, run `make trading-web` and open [the loopback workspace](http://localhost:8765). Startup creates a local receipt database, and opening Positions requests a broker snapshot. Public account placeholders and absent credentials are expected to block broker operations until an operator configures an authorized paper account. See [configuration](docs/CONFIGURATION.md).

## Guides

- [Documentation index](docs/README.md): scope, design, configuration, workflows and API.
- [Development and CI](docs/DEVELOPMENT.md): complete offline verification.
- [Operations and recovery](docs/OPERATIONS.md): state, diagnostics and unresolved submissions.
- [Release design and evidence](docs/WORKSPACE_RELEASE_052.md): dated v0.5.2 review.

## Ownership and publication scope

Data Providers owns acquisition, source credentials, broker ingestion, canonical stores and shared pricing primitives. This repository owns analysis, screening and the paper-order interface. Use provider runtime interfaces; do not copy its stores or duplicate acquisition here.

This is sanitized public source, with account placeholders. Private holdings, historical reports, generated sites, runtime state, credentials and native binaries are omitted. The maintained working project can contain additional dated analysis and unpublished report routes; those are not implicitly supported by this public release. Application execution runs natively; no application Docker rollback environment is retained. Provider deployment is independently managed.

Unit tests and offline CI do not establish broker access, current market coverage, profitability, full-account risk coverage or production readiness. CVaR is a conditional model estimate; quote receipts do not prove fresh executable prices. See [data contracts and limitations](docs/DATA_CONTRACTS.md).
