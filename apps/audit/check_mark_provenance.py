"""check_mark_provenance.py — the report must not misdescribe its own prices.

THE BUG THIS GUARDS. `risk_profile`'s header carried one hardcoded sentence,
"model prices (not live option quotes)", written when every mark came from a
chain snapshot. On 2026-10-06 the US legs moved onto the broker's live two-sided
book and the sentence stayed. Every NUMBER in the report was right -- the leg
table showed `P&L %` equal to `Est. P&L %` on every row, which is the signature
of a mark observed at the current spot -- and the one line stating what those
numbers were said the opposite. A reader with a position to manage believes the
sentence, not the arithmetic.

No other check here can see it: headline, ladder, and every leg row reproduce
from the book whether the provenance clause is true or false. It is prose, and
prose is the one claim in the report that arithmetic does not cover.

EXACT MATCH, not a keyword search. The comparison is against
`mark_provenance.sentence`, the function that generates the clause, because the
failure mode is a sentence that reads plausibly -- "every option mark is live"
passes any check looking for the word "live" while being wrong about the count.
"""
import re

LIVE = ("broker_book", "chain_book")


def check(text, book, add, mark_provenance):
    """Compare the report's provenance clause to what the book's marks actually are.

    `add` and `mark_provenance` are injected rather than imported: `add` writes into
    risk_profile_check's module-level results list, and importing it here would give
    this module its own copy and lose every verdict (the failure documented on
    `_state` in the other checks).
    """
    m = re.search(r"\*\*Book as of .*?current spot, (.*?)\.\*\*", text)
    if not m:
        add("REPORT", "report states what its option marks are", False,
            "no provenance clause in the header")
        return
    # `!= "STOCK"` -- the same rule risk_profile uses, so the check and the report
    # are counting the same rows.
    srcs = [r[21] for r in book if r[2] != "STOCK"]
    want = mark_provenance.sentence(srcs)
    got = m.group(1)
    add("REPORT", "report states what its option marks are", got == want,
        f"{mark_provenance.n_live(srcs)}/{len(srcs)} two-sided; "
        + ("agrees" if got == want else f"says {got[:55]!r}, should say {want[:55]!r}"))
