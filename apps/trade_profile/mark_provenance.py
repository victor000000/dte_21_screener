"""mark_provenance.py — say what a book's option marks actually ARE.

WHY THIS EXISTS. The profile's header used to carry one hardcoded sentence: "model
prices (not live option quotes)". That was true while every US mark came from a
chain snapshot, and it became a lie on 2026-10-06, when the US legs started being
priced off the broker's live two-sided book. Nothing failed: the leg table showed
`P&L %` equal to `Est. P&L %` on every row -- the signature of a mark observed at
the current spot, so nothing repriced -- while the sentence directly above it said
the prices were models. A reader believes the sentence.

`build_positions` now stores `mark_source` per row, the same way it has always
stored `spot_source`. These are the two sentences that turn those values into
something a reader can act on, in one place so they can be tested without a
database and a book.

The distinction the wording has to preserve: `broker_book` and `chain_book` are
OBSERVATIONS at the current spot; `model` is a stale last trade repriced at it;
`snapshot` and `cn_snapshot` are observations that are NOT current; `fill` is the
price this very leg traded at, which is neither.
"""

#: Mark sources that are a TWO-SIDED quote -- see the _LABEL note above for why this is
#: not the same claim as "live", and why the report must not make that one.
LIVE = ("broker_book", "chain_book")

# "TWO-SIDED", NOT "LIVE". Both book sources are fetched at build time, so the build can
# say the quote HAD two sides -- which is what it checks -- but not that the market is
# still moving. Equity options stop trading at 16:15 ET while the shares trade on, so a
# chain book read at 17:20 ET is the session's LAST book: measured 2026-10-06, yfinance
# served bid 10.45 / ask 10.95 for META's Nov-20 850C at both 20:20 and 21:20 UTC,
# byte-identical, an hour apart. The price is right -- a frozen book IS the truth for a
# closed market, and the build re-prices nothing on it -- but calling it "live" tells a
# reader the market is open when it has been shut for an hour. The spot line above already
# reports what is and is not real-time; this line should not assert it a second time.
_LABEL = {
    "broker_book": "two-sided broker quote",
    "chain_book": "two-sided chain quote",
    "model": "repriced at today's spot (a model)",
    "snapshot": "stored chain snapshot",
    "fill": "this leg's own fill",
    "cn_snapshot": "broker 快期 snapshot",
    "spot": "the underlying's spot",
}


def counts(sources):
    """{mark_source: n} for a book, dropping the None/empty bucket's label later."""
    out = {}
    for s in sources:
        out[s or "unknown"] = out.get(s or "unknown", 0) + 1
    return out


def n_live(sources):
    return sum(n for s, n in counts(sources).items() if s in LIVE)


def sentence(sources):
    """One clause for the header line: are the option prices quotes or models?

    Phrased as a count, not a verdict, whenever the book is mixed -- a book where nine of
    ten marks are two-sided is neither "quotes" nor "models", and rounding it to either is
    how the header came to be wrong in the first place.
    """
    c = counts(sources)
    total = sum(c.values())
    if not total:
        return "no option marks"
    n = n_live(sources)
    if n == total:
        return "every option mark is a two-sided quote"
    if n:
        return f"{n} of {total} option marks are two-sided quotes, the rest are not"
    return ("no option mark is a two-sided quote — every option price is a model "
                "or a snapshot")


def detail(sources):
    """The breakdown, always -- or None for an empty book.

    Printed even when every mark is live. The failure this module exists to stop
    was a report being confident about its own provenance, so the provenance is
    shown rather than summarised.
    """
    c = counts(sources)
    if not c:
        return None
    parts = [f"{n}× {_LABEL.get(s, s)}" for s, n in sorted(c.items(), key=lambda kv: -kv[1])]
    return "Option marks: " + " · ".join(parts)
