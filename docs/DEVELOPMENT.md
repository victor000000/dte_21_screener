# Development and verification

## Reproducible environment

Follow the [README setup](../README.md#start-here). CI checks out this repository and exact public Data Providers commit into adjacent directories, then runs `uv sync --locked`. The root project is not installed as a package; module entry points use bootstrap/working-directory imports. Keep acquisition and canonical schema implementations in the provider; add application analysis under `apps/`.

Python >=3.11 is declared, with 3.14 selected and verified by CI. UI VM tests use Node 22 and only built-in modules. No broker login, browser process or market data is needed for unit checks. The public native bridge is absent; explicit offline mode preserves skips instead of pretending a Python reference solver is native production evidence.

## Checks

Run this block from the screener root after placing the pinned provider beside it. It follows the [GitHub Actions job](../.github/workflows/ci.yml), including JavaScript files that CI parses without executing.

```bash
(
  set -eu
  uv sync --locked
  uv run --locked python scripts/check_docs.py
  for script in apps/trading_web/static/*.js tests/browser/*.cjs tests/apps/trading_web/*.test.cjs; do
    node --check "$script"
  done
  node tests/browser/risk_refresh.cjs
  for suite in tests/apps/trading_web/*.test.cjs; do
    node "$suite"
  done
  CHECK_NATIVE_REQUIRED=0 make check
)
```

For a disconnected run, use `export UV_OFFLINE=1` before the block. Python, Node, the pinned provider and the locked packages and build dependencies must already be available locally. The documentation checker verifies local links, anchors, source references and guide inventory. Use the server or screener `--help` commands for entry-point examples. [Command boundaries](WORKFLOWS.md#command-boundaries)

`make check` compiles and imports Python modules, verifies shim aliases, checks shell syntax and runs the full Python unit suite. Use `make test` alone for a shorter Python-only run. Job-process tests use a temporary provider runtime. Tests requiring private reports or a native library report skips.

`make check-full` adds provider data and risk audits and requires a quiet runtime with the relevant stores. `make check-build` invokes the sibling provider's QuantLib build, which needs its vendored source, CMake, a C++ compiler and Boost headers. The harness checks native loading before the build step. For a first native build, run `bash scripts/build_qliv.sh` from the screener root with the provider build prerequisites installed, then run `CHECK_NATIVE_REQUIRED=1 make check`.

## Source release

Workspace 0.5.3 discards late underlying quotes and errors after a ticker or source change. Paper execution requires a [private account binding](CONFIGURATION.md#paper-account-binding) loaded at startup. The job-process test keeps temporary markers in its own runtime.

The release owner packages a reviewed commit from the public source checkout. Confirm the workspace version in `apps/trading_web/__init__.py`, check the staged source for private files, commit the intended changes, and run the [offline checks](#checks) on that commit. The root project's packaging version is separate.

Build from the Git checkout with tar, gzip and GNU coreutils available. The command stops if tracked files differ from the commit. It writes the archive to a fresh directory, prints the packaged commit and produces a SHA-256 checksum.

```bash
(
  set -euo pipefail
  git diff --quiet HEAD --
  release_sha=$(git rev-parse HEAD)
  version=$(uv run --locked python -c 'from apps.trading_web import VERSION; print(VERSION)')
  archive="$(mktemp -d)/dte_21_screener-$version.tar.gz"
  git archive --format=tar.gz --prefix=dte_21_screener/ --output="$archive" "$release_sha"
  tar -tzf "$archive" >/dev/null
  printf 'Source commit %s\n' "$release_sha"
  sha256sum "$archive"
)
```

Keep the checksum with the archive in the chosen release location. Coordinate with the existing release owner and branch before pushing. After publication, check the `offline-checks` job on the exact GitHub commit, including a merge commit if one was created. Record the commit, pinned provider revision, checksum, test result and skips. Runtime recovery is a separate local operation. [Operations guide](OPERATIONS.md#release-and-migration)

## Review and contribution

Inspect the checkout before editing, stage only owned changes and review staged source for secret values and runtime artifacts. Preserve dated evidence; place current behavior in canonical guides and link historical designs as historical. Report source version, exact provider pin, full test outcome/skips, commit/tree and hosted-CI status separately. A local pass is not a hosted pass or deployment.

The workflow has read-only permissions, pinned Actions/provider revisions and no deployment job. [CI.md](../CI.md) is the concise CI contract. Changes to a sibling provider's version require deliberate lock review in each consumer; do not pin an unpublished provider SHA in hosted CI.
