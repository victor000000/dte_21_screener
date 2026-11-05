# DTE 21 Screener

Options screening, trading-journal analysis, position risk and a local trading workspace.
The web application includes exact-contract CN risk, source freshness labels, and US CVaR scenario analysis.
CN risk requests fresh quotes every 10 seconds while visible and auto-refresh is enabled.

## Setup

Use Python 3.11+ and uv in Linux/WSL. Place the separately maintained `data_providers` project beside this checkout; `pyproject.toml` references it as an editable dependency. Run `uv sync --locked` and consult the CLI help for each application entry point. The local workspace starts with `uv run --locked python -m apps.trading_web --help`.

Provider services own credentials, market acquisition, broker connections and canonical datasets. This repository contains application source, not those credentials or data. Broker integrations require your own accounts and entitlements. Recent receipts do not certify real-time quotes. Models are estimates, not guaranteed loss caps.

## Publication scope

This is a fresh, sanitized source snapshot, not a copy of the original Git history. Private trading logs, account exports, reports, runtime state, generated sites, credentials, binaries, archived analysis and source modules embedding personal portfolio studies are omitted. Account identifiers in remaining source/tests use placeholders. The legacy transcribed CN book is empty; use provider-delivered holdings.

The original private working checkout passed 967 tests and code checks during preparation. This public snapshot independently passes 899 tests with 22 explicit skips for unavailable native/private integration evidence, plus offline code checks and JavaScript refresh tests. See [CI.md](CI.md) for the workflow scope and local commands. No deployment is configured. None of these checks establishes current holdings, market-data completeness or broker access.
