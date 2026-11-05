"""Render vol method."""


def render_vol_method(add, validation):
    add("### The re-rating has a date on it")
    add("")
    add("The 30-Oct EWZ expiry went from 43.4% to 89.4% while the 20-Nov expiry went from "
        "39.7% to 65.1%. Same underlying, same sessions: the front month priced a dated "
        "event and the back month only part of it. That event is the 25-Oct Brazilian "
        "presidential runoff, which this repository already recorded on 5-Oct and 23-Oct "
        "(`reports/screener_2026-10-05.md`, `reports/held_review_2026-10-23/report.md`, "
        "citing the TSE calendar). A book short the front expiry was short a binary event, "
        "which is why the damage arrived on quiet days as well as on the 4-sigma ones. "
        "`event_and_rolls.md` carries the tests that separate this from an artefact of our "
        "own rolling.")
    add("")
    add("## Why the book had this shape")
    add("")
    add("The positions are almost all short strangles and short put ratios with strikes close "
        "to spot: EWZ short the 37/43 puts and the 43 call against a spot in the low 40s; CRWD "
        "short the 225/245 puts and the 270/290 calls; META short the 650/660 puts and the "
        "820/850 calls; methanol short 31 lots of the 3350 call and 2900 put; PTA short the "
        "7400 call and 5900 put. A short strike inside roughly one daily sigma of spot is "
        "short gamma by construction, so the P&L is quadratic in the move: EWZ +12.54% "
        "produced −$4,421 of gamma against −$3,457 of delta, and CRWD +8.25% produced −$2,839 "
        "of gamma against −$708 of delta. The same book sells the vol premium, so it is paid "
        "twice, by theta and by IV above realised, and it pays twice when either input moves "
        "against it.")
    add("")
    add("Theta earned $9,758 across the nine sessions, about $1,084 a day, against $31,729 of "
        "loss. On this evidence roughly six quiet sessions are needed to pay for one 16-Oct.")
    add("")

    add("## Method, price basis and limits")
    add("")
    add("- **Legs.** The dated reconstruction in "
        "`reports/loss_audit_2026-10-24/revision2/position_leg_daily.csv`: exact contracts, "
        "signed quantities, multipliers, currencies and observed closes. Its ticker totals "
        "reproduce the nine Combined P&L figures in your screenshot to the dollar, so this "
        "report explains your numbers rather than a parallel estimate.")
    add("- **Bridge.** Each held leg is repriced four times: at (S0, σ0, T0), then T1, then "
        "S1, then σ1. The three differences are theta, spot and vega. Because σ0 and σ1 are "
        "each solved from that leg's own observed close, the three sum to the observed carried "
        "P&L exactly; the Check column is 0.00 on every row.")
    add("- **Delta and gamma.** Gamma is the spot bucket minus the first-order delta term, so "
        "it absorbs convexity and the cross terms. Both are reported instead of folded into "
        "one spot number because their ratio is the diagnostic.")
    add("- **Pricing.** Black-Scholes on spot for US legs; Black-76 on the exact future for CN "
        "legs, implemented as the shared provider primitive at zero carry discounted at the "
        "CNY rate, so there is no second Black-76 implementation to drift. No dividend yield; "
        "r = 4.0% USD and 1.5% CNY, documented assumptions whose effect largely cancels "
        "because the spot and vol steps hold T fixed. Calendar days to expiry over 365.")
    add("- **Price basis.** Option closes are last trades (Alpaca for US, Sina for CN), not "
        "midpoints. On the five contracts that also have an IBKR closing midpoint, last trade "
        "and midpoint differ by 1.3% of premium on average, worth well under a vol point on an "
        "ATM option and rather more on the cheapest wings. Vega is therefore the noisiest "
        "bucket, which is why every ticker-day also reports the per-strike dispersion of its "
        "vol change: on 15-Oct six of the seven EWZ contracts in the observed chain repriced "
        "up together (median +8.5 vols) while the account traded only three of them, and "
        "`event_and_rolls.md` shows the move persisted for eight sessions and reached strikes "
        "the account had not yet traded. It was not our own prints.")
    add("- **Not attributed.** Cash FX, interest on cash, fees beyond those already in the leg "
        "P&L, and anything the holdings reconstruction missed. The IBKR NAV difference is "
        "shown explicitly rather than distributed.")
    add("- **Validation.** " + str(validation["legs"]) + " legs and " + str(validation["days"])
        + " sessions; bridge worst native gap " + str(validation["worst_native_gap"]) + "; "
        + str(validation["unsolvable_iv"]) + " legs with no solvable implied vol.")
    add("")
