# Validation and deployment

GitHub Actions runs the `offline-checks` job on pushes, pull requests and manual dispatch. It checks out the screener and a pinned public Data Providers commit into adjacent directories, installs locked dependencies with uv on Python 3.14, then runs the following checks.

| Check | Coverage |
| --- | --- |
| Documentation | Maintained local Markdown links, heading anchors, source references and required guides |
| Node.js 22 | Syntax of the workspace scripts, browser test scripts and UI suites. The risk polling test and all workspace `*.test.cjs` suites run with fake APIs |
| `CHECK_NATIVE_REQUIRED=0 make check` | Shell parsing, Python compilation and imports, compatibility shims and full unit discovery |

Use the [local CI commands](docs/DEVELOPMENT.md#checks) to reproduce every step. `make test` runs just the Python unit suite. The workflow pins its actions, uses read-only GitHub permissions and discards checkout credentials. [Workflow definition](.github/workflows/ci.yml)

The public suite uses synthetic brokers and receipts. Missing private reports or the native solver can produce skips. Native pricing, live source freshness and broker connectivity need separate local evidence. The workflow performs verification only. The release owner publishes verified source separately. [Source release](docs/DEVELOPMENT.md#source-release)
