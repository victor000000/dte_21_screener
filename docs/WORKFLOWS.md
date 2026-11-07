# User and analysis workflows

## Screening to a paper draft

1. Open Research → Screening and load saved results. Check report date, input date, release, rule and coverage gaps.
2. Choose full matches, high-IVR rows including failed gates, or all coverage. Searches filter instrument names; pages contain at most 100 rows.
3. An eligible equity/fund ticker offers Open option chain. The handoff transfers only a one-to-six-letter uppercase ticker, clears old expiry/strike filters and leaves the draft intact. Futures, indices and unknown classifications do not use this shortcut.
4. Request listed expiries, then a chain. Select exact contracts to add to the draft; they are never synthesized from saved IVR.
5. Open the trade ticket, confirm action, expiry, strike, call/put, quantity, debit/credit and limit. Adding a listed contract opens the editor. Collapsing it preserves in-memory state.

A saved screen is historical evidence, not a current entry clearance. `make screen` runs the general all-US saved-data pipeline and writes report bundles. It is not equivalent to the private dated strict 252-session/two-year research pipelines. General futures/index liquidity is unconfigured and cannot produce full MATCH status. See [contracts](DATA_CONTRACTS.md).

## Portfolio risk

US CVaR supports IBKR paper and modeled USD stocks/standard equity options. With Alpaca selected the panel explains the requirement and offers an explicit account switch, which clears the draft. Refresh actual holdings or compare a proposed ticket. Keep unsupported inputs and partial fills visible. The 21-trading-session horizon is primary, alongside 1/5/10/15/20; 5% and 10% bands are warning/limit labels rather than guaranteed account-loss bounds.

CN risk uses provider-delivered holdings/export evidence and timestamped quotes. An export is not a continuous live broker-position feed. Broker Greeks, model Greeks and futures exposures must stay distinguishable. An unavailable risk estimate must never be read as zero loss.

## Paper order lifecycle

Review validates the paper identity, contract units, holdings, working orders, broker preparation and quote warnings. For IBKR it also attaches risk evidence. Review expires after two minutes. Submission requires explicit account confirmation and any quote-quality acknowledgement. The service revalidates before transmission.

These are real orders in a paper account. No documentation example submits, cancels or places a live trade. After transmission, inspect Orders and the local receipt. A cancel button requests cancellation; the broker must confirm it. Holdings differences and journal notes do not establish executions.

## Command boundaries

| Command | Purpose and side effects |
| --- | --- |
| `make help` | Print available targets |
| `uv run --locked python -m apps.trading_web.server --help` | Print server usage without starting it |
| `uv run --locked python -m apps.screener.screen_all_us --help` | Print strict/inclusive IVR flags without running a screen |
| `make screen` | Read provider snapshot, write application reports |
| `make plan` | Analyze stored holdings, write management outputs |
| `make risk` / `make risk-check` | May refresh network inputs and persist snapshots; coordinate provider ownership |
| `make trade-log` | Broker lifecycle collection; not an offline check |

Run only help and test commands to validate documentation. Missing inputs should be resolved through provider-owned workflows, without starting a second collector or replaying a protected request.
