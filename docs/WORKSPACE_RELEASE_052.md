# Options workspace v0.5.2 — design and review

## Baseline and scope

Reviewed 7 November 2026. The workspace version source is
`apps/trading_web/__init__.py` (0.5.1); the root pyproject 0.0.0 is application
packaging metadata. Preserve the established workspace sequence: target 0.5.2.
Continue the existing grouped navigation, optional draft editor, ticker handoff
and refresh-label work documented in WORKSPACE_DESIGN_20261107.md.

The active “Check IVR data readiness” chat owns report regeneration, provider
coordination and the current report pointer. This release leaves those artifacts
and source acquisition to that owner. No deployment or service restart is part
of release preparation. Runtime Python version remains loaded until its owner
chooses to restart; preparing source does not establish runtime deployment.

## Design

Preserve account-scoped risk estimation across navigation, rendering and late
responses. A pending estimate disables the ticket estimate button on every
render, not only when the request begins. Completion derives button availability
from the current account, so an old IBKR request cannot enable Alpaca controls.
Error responses obey the same generation and account/draft scope guard as
successful responses. Editing or switching accounts must discard both stale
successes and stale errors.

Expose a read-only `isLoading()` UI method, retaining RiskUI as the sole owner of
its request state. Keep server authorization and order review independent.
Regression cases cover account changes, a late failure after a draft edit, pending
state and normal completion. Use fake APIs only; headless checks must not acquire
quotes, calculate live account risk, submit orders or restart services.

## Critical self-review before implementation

Accepted: the existing success path already checks generation and scope, but its
error path checks only generation. Its finally block unconditionally enables the
ticket button, and app.render only checks broker compatibility. Fix all three
paths together so rendering cannot contradict request state. Do not clear the
loading flag on invalidation: that would permit concurrent requests before the
old request settles. Preserve existing generation invalidation and retry timing.
No new model claims, risk budgets or provider interfaces are justified here.

## Acceptance and limits

Run both JS regression suites, syntax-check changed scripts, run native trading
web unit tests, make test and make check. Review the final source changes and
record actual results below. Existing repository-wide failures must be identified
without changing baselines or unrelated Python files. Browser visual evidence
from the earlier pass is limited by minimized Ego Lite; this release adds
headless state regression evidence, not a fresh visual acceptance claim.

## Final review and verification results

Source prepared at 0.5.2. Reviewed the final app.render availability condition,
RiskUI success/error/finally paths and exported loading state. Loading remains
owned by the in-flight request; invalidation continues to discard old results.
No further correction was required after the regression run. Existing usability
changes are retained. No provider report, report pointer, live account or service
was changed by this release pass.

- Both Node VM suites pass, including late success/error account isolation,
  pending state, invalidated drafts and ticker handoff guards. Syntax checks pass
  for app.js, risk-ui.js, market-ui.js and screen-ui.js.
- `uv run --locked --no-sync python -m unittest discover -s tests/apps/trading_web -t .`:
  69 tests pass, including page/session version consistency on a temporary server
  backed by fake brokers. No production service restart was needed.
- Installed-environment source version and QuantLib bridge assertions pass.
- `make test` and `make check` stop at lock validation: this checkout's lock
  records editable data-providers 0.1.0 while the sibling pyproject now declares
  0.2.0.dev0. Dependency reconciliation was not attempted during parallel owner
  work; the lock and provider metadata were not edited in this release pass.
- Full installed-environment suite via `uv run --locked --no-sync` ran 981 tests:
  two failures, both previously observed repository gates. Uncovered modules are
  31 versus baseline 30; existing manual_strangle_risk.py and trading_web/server.py
  exceed the 100-line gate at 150 and 104 lines. No baselines were relaxed.

Evidence logs from this pass are under /tmp/workspace-052-{js,targeted-nosync,
installed-suite,test,check}.log (local temporary evidence, not durable artifacts).
The installed environment pass does not prove a fresh locked installation works.
The production process was not restarted; do not interpret the source version
as proof that the running Python session endpoint now reports 0.5.2. Existing
static assets can be served immediately by the old process, as in the prior pass.
Visual acceptance remains limited to the earlier browser checks.

## Integration follow-up — lock reconciliation

After the provider owner completed stage 1, the coordinator authorized native
lock reconciliation. `uv lock --offline` changed exactly one line relative to
the immediate pre-run snapshot: editable data-providers version 0.1.0 became
0.2.0.dev0. All other lock content and dependency pins were preserved. This
supersedes the lock blocker above; `uv lock --check --offline` now passes.

Reran the normal native commands with synchronization enabled:

- `make test`: 981 tests in 27.046s, same two existing gate failures.
- `make check`: compilation (435 modules), imports (319), shim aliases (192)
  and native QuantLib checks pass. Its 981-test suite ran in 26.559s and fails
  only the same uncovered-module and line-limit gates described above.

No baselines were changed. No service restart, broker I/O or report publication
was used to validate this reconciliation. Local logs:
`/tmp/workspace-052-reconciled-test.log` and
`/tmp/workspace-052-reconciled-check.log`.

## Public source commit preparation and CI — 7 November 2026

The native working tree contains substantial unrelated/untracked work. To avoid
committing it, this release was transferred to a clean clone of the established
public repository `victor000000/dte_21_screener`, base
`2c19ac3ff69f3098fdb9c870313c606edb6cc8d3`, on branch
`codex/workspace-0.5.2`. Existing public account placeholders were preserved;
private report pointers, generated reports and runtime artifacts were excluded.
The publication source path is
`/home/vic/.local/share/project-publications/dte_21_screener-20261105`.

Public CI continues to pin published Data Providers
`c32b218385d999fbeb4052c1d70bdb7ebae3b21f` (0.1.0), matching its unchanged public
lockfile. The native 0.2.0.dev0 lock reconciliation above remains in the native
workspace; it is not a claim that provider 0.2 is publicly available. This UI
release needs no new provider API. An exact checkout of the CI provider pin was
used for final publication verification:

- `uv sync --locked --offline` and `uv lock --check --offline` pass.
- `make test`: 917 tests, 22 explicit native/private-evidence skips, pass.
- `CHECK_NATIVE_REQUIRED=0 make check`: full code/import/shim checks and the full
  917-test suite pass. Neither coverage nor size baselines were relaxed.
- Four headless Node suites pass, covering refresh cadence, late responses/errors,
  account isolation, unsupported ticker/asset guards, draft and review preservation
  through collapse and Research navigation, and pending state during rendering.
  CI now syntax-checks and runs all these suites. No browser is launched.

Final source review removed a native-only report link during transfer because
its publication endpoint is outside this release's public baseline. No other
native report work was imported. JavaScript tests were rerun after that edit.
The new test code uses synthetic values and fake APIs; live service, broker and
provider operations were not used for release acceptance.

Hosted status is **not verified for these changes**. The coordinator audited
existing write routes: connector mutation returned 403 (Resource not accessible
by integration), the noninteractive Git credential helper supplied no usable
credentials, and both existing SSH keys were rejected by GitHub. No new keys,
permission changes or login UI were used. Local commits can be prepared, but
pushing and exact-SHA hosted CI remain blocked until write authentication is
restored. Earlier public CI results must not be attributed to this release.
