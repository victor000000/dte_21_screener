# Data contracts and analysis limits

## Evidence identity

Every saved analysis should retain provider release, source, instrument identity, observation time, receipt time, session, adjustment basis, currency and multiplier. An export time describes holdings evidence; it does not date the quote. A snapshot-update time does not necessarily date its bid/ask book. Frozen/delayed/indicative or unknown-time observations stay labelled even if fetched just now.

Use exact expiry, venue and contract month for derivatives. Do not map a futures symbol to an equity with the same root or pad a short typed IV series from unrelated legacy sources. Apply quantity and multiplier once. Broker position Greeks and model per-contract Greeks have different units. Do not infer fills from holdings changes or journal rows. Portfolio grouping and calculations must preserve broker ownership and contract identity.

## General IVR screen

The implemented general screen defaults to IVR strictly >50. `--ivr-above` is strict; `--min-ivr` is inclusive and mutually exclusive with it. Range IV rank and IV percentile are different statistics. Review `apps/screener/us_screen_rules.py`, `compute/iv_rank.py` and the report metadata for exact accepted source/history gates; coverage omissions remain in saved output.

The general screen uses up to 252 distinct daily observations with a 60-observation minimum and labels partial windows. Equity/fund gates use observed average share volume >5M/day, price >30 and capitalization/AUM >1B, with freshness and optionability evidence. Catalog discovery is not proof that all US optionable products are covered. Futures/index inventory can appear with IV, but liquidity configuration blocks full MATCH in this public pipeline. The native dated futures >10,000-contract/20-session rule is a separate research/report implementation, not silently integrated here.

Saved JSON/CSV report pairs under `reports/ivr_all_us_<date>` are loaded by `apps/screener/web_report.py`; newest matching filename wins. Missing reports yield unavailable status. Private files are not shipped. A current UI version cannot prove the report was regenerated.

## Risk model

Portfolio CVaR uses aligned historical spot scenarios and constant-IV option repricing; it is conditional on the delivered inputs and covered instruments. The public model supports USD equity holdings and standard 100-multiplier USD options; unsupported instruments or incomplete account currency information can invalidate the entire estimate. It does not silently drop unsupported holdings to claim whole-account clearance.

Volatility jumps, FX cash, assignment/exercise, American/dividend effects, liquidation, margin changes and executable combination fills require additional evidence/models. A broker buying-power figure is not an order-specific margin preview. A 95% CVaR is a modeled average of the worst 5% sampled outcomes; observed maximum loss and future worst-case loss are not the same quantity.

## Price movement and provenance

Distinguish change versus regular close from rolling 24-hour change. Preserve actual reference time and adjustment basis; an old close is not an exact 24-hour reference. Updated underlying data does not make an old option quote synchronous. Record missing option tape and any order-ladder proxy explicitly. Never label estimated prices, stale observations, missing account capacity or incomplete coverage as verified executable evidence.

No unit or historical result in this repository establishes a profitable strategy or funded release. Dated research records and requirements preserve hypotheses and delivery requests; current publication and readback evidence must independently establish delivery.
