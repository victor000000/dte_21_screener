# Makefile — the product entry points and the verification gate, by name.
#
# Dependencies come from pyproject.toml's dependency groups, so these recipes no
# longer carry hand-written `uv run --with a --with b --with c` chains. `uv run`
# installs the default group set (see [tool.uv] default-groups) automatically.
#
#   make            list targets
#   make check      the CI gate — safe while a downloader holds a database
#   make full       adds the data checks; needs a quiet box
#   make risk       the risk/P&L profile for the current book

.DEFAULT_GOAL := help
.PHONY: help check test check-full check-build screen plan risk risk-check trade-log \
        fingerprint-write fingerprint-diff strings-write strings-diff strings-diff-repo \
        restructure-verify

UV := uv run --locked
SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

help:  ## list targets
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── verification ────────────────────────────────────────────────────────────────────────

check:  ## code checks: compile, import both paths, shim identity, USING_QUANTLIB
	bash scripts/check_all.sh --fast

# The unit suite on its own, for the loop where you are changing code and not data. Same
# command check_all.sh runs (it runs it in EVERY mode, including --fast) -- named here so it
# can be run directly, and with the dependency list kept identical to that one on purpose:
# a `make test` that resolved different deps would be a second, drifting definition of green.
test:  ## the unit suite only (what CI runs inside check_all too)
	uv run --locked python -m unittest discover -s tests -t . 2>&1 | tail -20

check-full:  ## adds selfcheck (38 checks), IV solvers, duplicate keys. Needs a quiet box.
	bash scripts/check_all.sh --full

check-build:  ## rebuilds the vendored QuantLib + qliv.so (~10 min cold)
	bash scripts/check_all.sh --build

# ── the products ────────────────────────────────────────────────────────────────────────

screen:  ## all US asset classes -> reports/ivr_all_us_<date>.md + CSV coverage
	$(UV) python apps/screener/screen_all_us.py

plan:  ## risk navigator -> plans/risk_navigator_<date>.md
	$(UV) python apps/plan/plan_builder.py

risk:  ## risk/P&L profile: snapshot close vs live underlying
	$(UV) python apps/trade_profile/complete_risk_analysis.py

risk-check:  ## recheck the risk profile USING REAL-TIME PRICES (refresh -> rebuild -> verify)
	$(UV) python apps/audit/risk_profile_check.py --live

trade-log:  ## capture this session's IBKR order lifecycle
	$(UV) python apps/trade_log/ibkr_order_collector.py

.PHONY: trading-web
trading-web:  ## local paper options workspace v0.5.1 at localhost:8765
	$(UV) python -m apps.trading_web.server --port 8765

# ── restructure safety net (see scripts/restructure_*.py docstrings) ─────────────────────
#
# These exist because the previous layer migration silently corrupted SQL inside
# multi-line string literals and destroyed 152,304 rows elsewhere. They are here so
# they get RUN between moves rather than remembered. See
# scripts/restructure_strings.py and scripts/restructure_fingerprint.py.

fingerprint-write:  ## record per-table row counts before moving code
	$(UV) python scripts/restructure_fingerprint.py write plans/restructure_fingerprint.json

fingerprint-diff:  ## compare row counts now vs the recording — ANY diff means code wrote
	$(UV) python scripts/restructure_fingerprint.py diff plans/restructure_fingerprint.json

strings-write:  ## record hashes of every multi-line string literal
	$(UV) python scripts/restructure_strings.py write plans/restructure_strings_before.json

strings-diff:  ## compare literals per FILE — ANY loss is corruption (use for a MOVE)
	$(UV) python scripts/restructure_strings.py diff plans/restructure_strings_before.json

# The SPLIT gate. Per-basename is the wrong question for a split: relocating a
# module's literals into a package's submodules reports them LOST by construction,
# and re-baselining to silence that would launder a real corruption into the record.
# Repo-wide, relocation is a no-op while a literal whose CONTENT changed -- or one
# that vanished -- still fails. Run `make strings-diff` too, for the attribution
# record of which names lost and gained; the repo-wide result is what gates.
strings-diff-repo:  ## compare literals REPO-WIDE — ignores relocation, catches corruption
	$(UV) python scripts/restructure_strings.py diff plans/restructure_strings_before.json --scope repo --explain

restructure-verify: fingerprint-diff strings-diff-repo  ## both restructure detectors, in order
