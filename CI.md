# Validation and deployment

GitHub Actions checks JavaScript syntax, 10-second risk polling behavior, draft preservation, screening handoff and stale-request/account isolation, Python imports, shell syntax and the offline unit suite. Actions and the public sibling provider source are pinned to commits. The workflow has read-only permissions, does not retain Git credentials, and uses no broker credentials, market-data downloads or running services.

For the equivalent local check, place this project beside the pinned `data_providers` checkout shown in `.github/workflows/ci.yml`, install Node 22 and uv, then run `uv sync --locked`, `node tests/browser/risk_refresh.cjs`, and `CHECK_NATIVE_REQUIRED=0 make check` from this project.

Private historical reports, runtime watchlists and the native QuantLib shared library are not shipped. Tests requiring them explicitly skip when unavailable. Synthetic evidence tests remain active. Integration with live broker accounts, source freshness, canonical data audits and native pricing require separate local validation; a green CI run does not establish those properties.

No CD deployment is configured. This repository does not publish a trading site, submit orders or restart local services from CI.

The native check remains required by default when provider QuantLib source exists. Public CI explicitly sets `CHECK_NATIVE_REQUIRED=0` because it does not build or ship the native library; native model tests report skips.

Credential persistence regression tests use synthetic secrets and fake brokers. Submission, rejection and recovery receipt writes strip credential fields and labelled secret text. Credentials are loaded from private files/environment, never from this application database.

Run the headless UI regressions with `for suite in tests/apps/trading_web/*.test.cjs; do node "$suite"; done`. These tests use fake APIs and do not launch a browser or connect to a broker. CI runs every suite after checking JavaScript syntax.

Maintained documentation is checked offline with `uv run --locked python scripts/check_docs.py`; CI runs this after dependency installation. For canonical setup, complete test commands and limitations, see [development](docs/DEVELOPMENT.md). Dated verification records are not substitutes for the exact commit's CI outcome.
