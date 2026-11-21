# DTE 21 Screener

Options screening, position and trade-log analysis, management reports, and a local paper-trading workspace. Workspace version **0.5.3** comes from `apps/trading_web/__init__.py`; the root package's `0.0.0` is packaging metadata.

## Start here

Run the commands from the screener repository root or the extracted `dte_21_screener/` directory. Use Linux or WSL with Git, Bash, GNU Make and uv. CI uses Python 3.14 (selected by `.python-version`) and Node.js 22 for JavaScript checks. The first install needs access to the Python distribution and locked packages, or a populated uv cache.

The lockfile installs Data Providers from the sibling directory `../data_providers`. The setup below clones it when absent and checks the revision of an existing checkout before installing dependencies. If your working provider is on another revision, use a separate parent directory for the public screener and its pinned sibling.

```bash
(
  set -eu
  provider_rev=c32b218385d999fbeb4052c1d70bdb7ebae3b21f
  if [ ! -e ../data_providers ]; then
    git clone --no-checkout https://github.com/victor000000/data_providers.git ../data_providers
    git -C ../data_providers checkout --detach "$provider_rev"
  fi
  if [ "$(git -C ../data_providers rev-parse HEAD)" != "$provider_rev" ]; then
    echo "Existing provider checkout differs from the public CI revision." >&2
    exit 1
  fi
  uv sync --locked
  uv run --locked python -m apps.trading_web.server --help
)
```

The help command verifies the entry point without starting the service. For offline verification, follow the [CI commands](docs/DEVELOPMENT.md#checks).

To use the workspace, run `make trading-web` and open the [loopback workspace](http://localhost:8765). Startup creates the local receipt database. Loading Positions requests the selected broker's snapshot. Broker use requires a valid [private paper account binding](docs/CONFIGURATION.md#paper-account-binding).

## Guides

- [Documentation index](docs/README.md): scope, design, configuration, workflows and API.
- [Development and CI](docs/DEVELOPMENT.md): complete offline verification.
- [Operations and recovery](docs/OPERATIONS.md): state, diagnostics and unresolved submissions.
- [Release and verification](docs/DEVELOPMENT.md#source-release): source archive and version checks.
- [v0.5.2 design and evidence](docs/WORKSPACE_RELEASE_052.md): dated release review.

## Ownership and publication scope

Data Providers owns acquisition, source credentials, broker ingestion, canonical stores and shared pricing primitives. This repository owns analysis, screening and the paper-order interface. Use provider runtime interfaces; do not copy its stores or duplicate acquisition here.

Paper-account identities come from private broker configuration. The public workspace can run offline checks without those files. Keep private holdings, historical reports, generated sites, runtime state, credentials and native binaries outside the public source. The maintained working project can contain additional dated analysis and unpublished report routes; those are not implicitly supported by this public release. Application execution runs natively; no application Docker rollback environment is retained. Provider deployment is independently managed.

Unit tests and offline CI do not establish broker access, current market coverage, profitability, full-account risk coverage or production readiness. CVaR is a conditional model estimate; quote receipts do not prove fresh executable prices. See [data contracts and limitations](docs/DATA_CONTRACTS.md).
