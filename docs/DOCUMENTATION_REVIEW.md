# Documentation review — 7 November 2026

## Scope and inventory

Reviewed public source on `codex/workspace-0.5.2` after implementation commit
`ec9c90ebb80db04580893c3f8245f6ae9b46f42c`, based on published
`2c19ac3ff69f3098fdb9c870313c606edb6cc8d3`. Provider source was the exact CI pin
`c32b218385d999fbeb4052c1d70bdb7ebae3b21f` (0.1.0). This phase changes
canonical documentation and adds offline documentation validation; it does not
change financial models, deployment, stores or account guards.

The publication baseline had five Markdown documents: README, CI summary,
document index and two dated workspace records. All five were reviewed. README,
CI summary and index are maintained entry points; dated workspace design/release
records remain unchanged. Seven code-backed guides and this audit close missing
architecture, configuration, workflow, API, data-contract, development and
operations coverage. The resulting public set has thirteen Markdown documents.

The native working tree was inventoried independently, excluding Git, virtual
environments, dependencies, local runtime, caches and generated package files:
366 Markdown files were classified. This is an inventory/disposition count,
not a claim of line-by-line validation of every historical report:

| Native category | Count | Review/disposition |
| --- | --- | --- |
| Top-level docs | 14 | Eight current guides checked against source; six dated review/design/retirement records retained |
| Provider requirements | 8 | Retain dated requests and acceptance criteria; not delivery proof |
| Strategy/analysis docs | 4 | Retain research/source evidence; no economic validation inferred |
| Archived guides | 3 | Historical instructions, superseded by native setup |
| Plans/design history | 22 | Preserve dated proposals; not current implementation claims |
| Saved report Markdown | 304 | Immutable analysis evidence, no regeneration or re-dating |
| Other root/subproject guides | 10 | Standing instructions/current pointers reviewed; historical root reviews already link current index |
| Test fixture document | 1 | Synthetic evidence, not user guidance |

Native-only source and private reports are not copied into the public set.
Later native report routes and stricter dated IVR pipelines are explicitly
outside the public baseline. The native inventory and audit live in the original
working checkout, whose unrelated source changes remain preserved.

## Findings and revisions

- Corrected README startup from a nonexistent package `__main__` to the real
  `apps.trading_web.server` module; checked its help without creating a server.
- Added dependency/bootstrap instructions using the exact public provider pin.
  Distinguished native provider 0.2.0.dev0 from public 0.1.0 integration.
- Documented source-defined account guards, port precedence, runtime path
  precedence and provider-owned credentials without publishing secret values.
- Described order review, persistent idempotent receipts and uncertain-outcome
  recovery. Documented GET routes with I/O or persistence rather than calling
  them universally read-only.
- Distinguished historical screening evidence, general-screen limits, native
  strict-window research and current quote/risk eligibility.
- Added code-backed architecture rationale and a component diagram. Replaced
  undated test-count/readiness wording in onboarding with scoped verification.
- Narrow native corrections: fast checks defer data reconciliation; retired
  container backup is absent; published CI provisions its sibling; CVaR timer
  is ten seconds; a former paper port observation is not current configuration;
  stock-screen example uses `uv run --locked`. Dated evidence was not rewritten.

## Verification and exclusions

`check_docs.py` validates required current guides, all root README/CI and
`docs/*.md` relative file links and Markdown anchors offline. It also checks
inline owned-source paths in current guides. Historical workspace records retain
native-only path references and are excluded only from source-path checks;
their Markdown links are still checked. External URLs are not fetched, Mermaid
is not rendered, private report contents and live endpoint behavior are not
validated. Heading slugs use the documented simple Markdown heading subset;
this is not a complete Markdown parser.

Regression tests verify valid links, duplicate heading anchors, broken files and
anchors, missing source references, fenced examples and required-guide failures.
CLI help checks cover server `--port`, general screen threshold flags and plan
`--account`. No screen, broker request, provider replay, service or browser was
started to verify prose. CI gains the same offline doc check after installation.

Full verification results and exact source-tree handoff are reported by the
owning chat/coordinator after this change is committed. Existing release records
are evidence for their original code, not claims about this final documentation
commit. Publication and final-SHA hosted CI are serialized by the coordinator;
local checks alone do not establish successful publication.

## Local acceptance results

Final offline check on 7 November: **920 Python unit tests pass, 22 skips**;
383 modules compile, 267 import and 191 compatibility aliases verify. The three
new documentation-check regressions pass. All public relative links/anchors and
current inline source references pass. Server, screen and plan help parse with
the documented flags. Version and runtime/port setting names were checked against
their owning source. The native current/root guide file-link scan checks 17 files
and reports zero missing targets. No historical external link health is claimed.

The documentation checker and CI step are the only executable changes in this
phase. No baseline was relaxed and no runtime/dependency changes were required.
The earlier workspace release records are byte-unchanged in this documentation
commit. The final Git commit/tree and path manifest are handed to the existing
coordinator for serialized publication and hosted-CI acceptance.
