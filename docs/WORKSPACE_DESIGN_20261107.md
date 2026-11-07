# Workspace usability design — 7 November 2026

## Goal and acceptance

Help a user move from saved screening evidence to listed contracts, a draft,
portfolio comparison and explicit paper-order review. Keep existing broker,
quote provenance and order confirmation rules. This change concerns presentation
and navigation; it does not change risk calculations or provider acquisition.

## Information architecture

Keep all ten existing URLs and hash destinations. Arrange navigation into three
labelled groups: Trading (Positions, Option chain, Orders, Trade logs, US CVaR),
Research (Screening, CN markets, CN risk profile, Daily P&L attribution), and Data
(Data & maintenance). Show group labels on desktop and allow wrapping on narrow
screens so the last destination remains discoverable. Preserve keyboard buttons,
focus outlines and aria-current on the active destination.

## Draft workspace

Start with the ticket closed and give the main view full width. A persistent
“Open trade ticket” control on trading pages opens the existing editor. A close
control collapses it without clearing legs, quotes or review. Opening a new trade
explicitly resets the draft; startup initialization and account changes reset it
without forcing it open. Adding a chain leg, closing/rolling a position or adding
a closing leg opens the ticket automatically. Research hides the editor while
retaining the user's draft and open state for their return. At mobile widths the
editor follows main content; opening it scrolls it into view. Collapse changes
must never call review, submit, cancel or refresh APIs.

## Account compatibility

For Alpaca, show an IBKR requirement on US CVaR with a direct “Switch to IBKR
paper” action. Disable risk calculation and automatic-risk controls on that page,
and disable the ticket's risk estimate control for Alpaca. Switching uses the
existing broker-change handler, including clearing the old account's draft and
invalidating review. Retain the server-side broker guard. The action must not
submit orders or calculate risk automatically.

## Screening handoff

Each eligible US equity/ETF row gets an “Open option chain” button. Accept only
plain broker-supported ticker syntax (one to six uppercase letters), and use
explicit equity/ETF asset classification; leave futures/index/unknown identities
unlinked. Transfer only the underlying to the chain form. Clear previous expiry,
strike bounds, chain rows and pagination. Do not copy saved IVR into current quote
state, invent option legs, load providers automatically or alter a draft. The
user then requests listed expiries and chooses exact contracts normally.

## Refresh semantics

Rename the header switch “Enable background refresh” and explain that it gates
page-specific timers while the browser tab is visible. Label quote refresh as
“Ticket quotes · 10s”, chain refresh as “Chain quotes · 10s”, and positions as
“Holdings · 30s when background refresh is enabled”. Preserve existing backoff,
visibility and preview safeguards. Individual switches retain their state.

## Verification

Run JS syntax and existing browser logic tests, native unit checks, and browser
checks at desktop and mobile widths. Exercise grouping, collapse/restore with an
edited draft, research return, chain insertion, risk account gating and screening
handoff. Verify escaping and reject unsupported asset identities. Do not submit
or cancel orders as part of verification. Report unrelated baseline failures.

## Self-review before implementation

Reviewed against app.js, MarketUI, RiskUI, ScreenUI and LiveUI. Accepted with
these implementation constraints:

- Render-driven refreshes must not reset ticket visibility or draft inputs.
- Initialization must not scroll/open the ticket; user entry actions must.
- Account-switch shortcuts must dispatch the existing change handler rather
  than assigning the account and leaving a stale review behind.
- A late chain response must fail its existing form signature check after a
  screening handoff. Clear underlying context as well as old contracts.
- Ticker shape alone is insufficient: asset classification must also allow the
  handoff. Unsupported rows need a visible explanation rather than a dead button.
- Keep the background switch visible in research because it also gates provider
  status timers; do not suggest it refreshes saved screening reports.

The design is ready to implement. Browser verification remains necessary for
layout and draft preservation; source review cannot establish those behaviors.

## Implementation verification

Implemented the design in the static workspace UI. Desktop browser checks
confirmed draft preservation through collapse and Research, account-switch draft
clearing, disabled Alpaca risk controls, and TLT screening-to-chain transfer with
empty expiry/strike filters. At 390px, document and navigation widths were both
390px; screening results retain their inner horizontal table scroller.
Screenshot capture remained unavailable because Ego Lite was minimized, so visual
pixel-level review is still limited. No orders were submitted or cancelled.

All 69 trading-web Python tests passed. JavaScript syntax checks and both Node
UI suites passed, covering risk response isolation, draft-preserving handoff and
unsupported asset guards. Run Node suites using a native Node installation (this
host exposes node.exe through WSL).

`make test` ran 981 tests with two failures. `make check` reported the same two
failures: the existing uncovered-module count (31 versus baseline 30), and
existing oversized files apps/trade_profile/manual_strangle_risk.py (150 lines)
and apps/trading_web/server.py (104 lines). This work did not modify these Python
files or baseline gates. The native QuantLib check passed. Broad checks are not
fully green.
