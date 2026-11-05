import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root
import bootstrap  # noqa: F401

from shared import helpguard
helpguard.handle_help(__file__)   # reads the module summary from the SOURCE:
# __doc__ is None here -- the description sits after the bootstrap above, and a
# docstring must be the first statement.

"""leg_estimates.py — per-leg P&L as a percentage: the mark, the model, and the read.

TWO NUMBERS, BECAUSE THEY ANSWER DIFFERENT QUESTIONS.

  P/L% MARK   what the leg is worth at the last stored market price. Real, and the
              only number that is a fact -- but a fact about the moment it was taken.

  P/L% EST    what the leg is worth at the CURRENT underlying, priced with the native
              QuantLib solver. An estimate, and labelled as one.

They diverge exactly when the underlying has moved since the marks were taken, which
outside regular hours is most of the time: the equity feeds publish a LAST price, and
outside RTH that last price is the previous close. On 2026-10-05 EWZ sat at 38.19 on
every feed all night while the pre-market book traded near 42 -- a 9.6% gap that left
the 43 call reading -73% on its mark and -285% on the model.

THE IV IS SOLVED FROM THE CURRENT PRICE, NEVER FROM THE OBSERVATION, and that detail is
what keeps the estimate honest. IV is the invariant; the spot is what moved. Pairing a
stale observation against the LIVE spot compares two different moments and returns
nonsense -- for EWZ it gave 17% for the 43 call and 73% for the 32 put, two legs of one
strangle whose implied vols can only differ by a few points. Solved from the current
price they come back 50% and 53%. The current price is already a price at today's spot
(build_positions writes it that way), so solve there, re-price there, hold IV fixed. That
is also why the estimate is a SPOT-SENSITIVITY and not a quotable price -- it ignores the
vol move that came with the spot move, and a 9.6% move does not leave IV unchanged.

Broker and account are columns, not a footnote: the same contract is routinely held at
two brokers (CRWD 220P is -10 at IBKR and -6 at Schwab), and a per-leg P&L that merges
them cannot be acted on.

Every run is persisted to trades.leg_estimates keyed by run_ts, so "what did the book
look like when I decided that" is answerable afterwards.

    uv run python apps/trade_profile/leg_estimates.py [--account U0000000]
"""
from apps.trade_profile.leg_estimates.run import main   # ABSOLUTE import on purpose:
# this file is executed two ways -- by runpy as `__main__` (via the shim) and imported
# by the gate as `apps.trade_profile.leg_estimates.__main__`. A relative import works for
# the first and dies for the second with "attempted relative import with no known parent
# package".

if __name__ == "__main__":
    main()
