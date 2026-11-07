# Development and verification

## Reproducible environment

Follow the [README setup](../README.md#start-here). CI checks out this repository and exact public Data Providers commit into adjacent directories, then runs `uv sync --locked`. The root project is not installed as a package; module entry points use bootstrap/working-directory imports. Keep acquisition and canonical schema implementations in the provider; add application analysis under `apps/`.

Python >=3.11 is declared, with 3.14 selected and verified by CI. UI VM tests use Node 22 and only built-in modules. No broker login, browser process or market data is needed for unit checks. The public native bridge is absent; explicit offline mode preserves skips instead of pretending a Python reference solver is native production evidence.

## Checks

```bash
uv sync --locked
uv run --locked python scripts/check_docs.py
for suite in tests/apps/trading_web/*.test.cjs; do node "$suite"; done
node tests/browser/risk_refresh.cjs
make test
CHECK_NATIVE_REQUIRED=0 make check
```

`make check` compiles/imports owned modules, verifies compatibility aliases, checks shell syntax, handles native mode and runs the complete Python unittest suite. `make test` runs the same unit discovery alone. Do not change test-count or size baselines merely to silence a failure. Synthetic broker/data fixtures isolate submission and analysis tests; private/native-evidence skips remain explicit.

Documentation checking validates relative Markdown file links/anchors and current guide inventory. It does not fetch external websites or prove command side effects safe. Verify executable examples with help or a fixture rather than launching a service. Run JavaScript syntax checks as CI does; browser scripts in `tests/browser/` that require a real browser/module are optional, separate integration evidence and are not automatically run by the unit suite.

`make check-full` adds shared data audits and runtime reconciliation; `make check-build` can build the native bridge. These are not clean-source CI targets and need provider-owned data/build prerequisites and coordination. Do not execute them to verify documentation.

## Review and contribution

Inspect the checkout before editing, stage only owned changes and review staged source for secret values and runtime artifacts. Preserve dated evidence; place current behavior in canonical guides and link historical designs as historical. Report source version, exact provider pin, full test outcome/skips, commit/tree and hosted-CI status separately. A local pass is not a hosted pass or deployment.

The workflow has read-only permissions, pinned Actions/provider revisions and no deployment job. [CI.md](../CI.md) is the concise CI contract. Changes to a sibling provider's version require deliberate lock review in each consumer; do not pin an unpublished provider SHA in hosted CI.
