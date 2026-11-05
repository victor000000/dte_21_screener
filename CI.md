# Validation and deployment

GitHub Actions checks JavaScript syntax, 10-second risk polling behavior, Python imports, shell syntax and the offline unit suite. Actions and the public sibling provider source are pinned to commits. The workflow has read-only permissions, does not retain Git credentials, and uses no broker credentials, market-data downloads or running services.

For the equivalent local check, place this project beside the pinned `data_providers` checkout shown in `.github/workflows/ci.yml`, install Node 22 and uv, then run `uv sync --locked`, `node tests/browser/risk_refresh.cjs`, and `make check` from this project.

Private historical reports, runtime watchlists and the native QuantLib shared library are not shipped. Tests requiring them explicitly skip when unavailable. Synthetic evidence tests remain active. Integration with live broker accounts, source freshness, canonical data audits and native pricing require separate local validation; a green CI run does not establish those properties.

No CD deployment is configured. This repository does not publish a trading site, submit orders or restart local services from CI.
