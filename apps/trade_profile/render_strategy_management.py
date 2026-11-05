"""Render strategy management."""


def render_strategy_management(b):
    b.append('<h2>4 · Daily management (five minutes before the close)</h2>')
    b.append('<table><tr><th>Measure</th><th>Computation</th><th>Action threshold</th></tr>'
             '<tr><td>|delta| per leg</td><td>broker display</td><td>above 0.35 → act</td></tr>'
             '<tr><td>Distance to strike</td><td>difference ÷ daily σ, where daily σ = IV/√252</td>'
             '<td>below 0.5 → act</td></tr></table>')
    b.append('<p>Never in percent: the same 3% is 3.7 daily σ on TLT and 0.87 on CRWD, a factor of '
             'four. A percentage rule cannot be applied across names.</p>')

    b.append('<h2>5 · Stop<span class="tag t-x">untested</span></h2>')
    b.append('<div class="rule q"><p>Close the <b>whole strangle</b> on either trigger, without '
             'waiting for 21 DTE: tested leg |delta| above 0.35, or spot within 0.5 daily σ of a '
             'strike. No single-leg adjustments, no re-centring, no adding legs.</p>'
             '<p><b>Stated honestly:</b> both thresholds are conventions, and the direction may be '
             'wrong — these prices mean-revert (VR(20) of 0.73–0.92), so stopping at delta 0.35 can '
             'sell the position at its worst point. A stop cuts the tail and may also cut the '
             'expectation; the net effect is not measured. <a href="evidence.html#unknown">E9</a></p></div>')

    b.append('<h2>6 · Exit<span class="tag t-d">derived</span></h2>')
    b.append('<div class="rule ok"><p><b>Close everything at 21 DTE.</b> The probability a leg is '
             'tested falls from 40% to 25%, a 37% relative reduction, at the cost of one extra round '
             'trip. <a href="evidence.html#exit">E5</a></p>'
             '<p>Compute the exit date from the calendar, not approximately: expiry minus 21 days, '
             'moved earlier to the last full session if it lands on a holiday or half day. Do not open '
             'a new position the same day; open the next.</p></div>')

    b.append('<h2>7 · No rolling<span class="tag t-m">measured</span></h2>')
    b.append('<div class="rule ok"><p>No re-centring, and no "roll the untested leg back to 0.16–0.22 '
             'once it is 50% profitable". Measured: after that trigger a 20-delta strike placed at the '
             'trigger close was touched <b>38%</b> of the time against <b>35%</b> unconditionally '
             '(n=318). The trigger carries no information and the action pays a spread. Tested legs run '
             'to 21 DTE or to the stop; <b>the risk is absorbed by size, not by management</b>.</p>'
             '<p>One optional exception, untested: once the untested leg is 50% profitable, roll it to '
             'a <b>further month at the same strike</b>, which preserves strike distance.</p></div>')

    b.append('<h2>8 · Standing tail budget</h2>')
    b.append('<div class="rule q"><p>Paid every cycle, sized to the gap between the p5 and the median. '
             'Implemented as whichever is cheaper: far out-of-the-money protection, or simply selling '
             'less. <b>Buying protection only after a loss has started is not a hedge</b> — it is a '
             'second trade at worse prices.</p>'
             '<p><span class="tag t-x">undefined</span>The gap is not converted into a dollar amount, a '
             'hedge ratio or a size reduction anywhere in this document. This is the vaguest section of '
             'the specification, and it is the one labelled "black swan control".</p></div>')

    b.append('<h2>9 · Events</h2>')
    b.append('<div class="rule"><p><b>Default: cut or close before the event.</b> To hold the exposure '
             'deliberately, size it as a separate event trade, only when the expected move is likely to '
             'exceed the move implied by that day\'s peak IV, and record the implied move at entry.</p>'
             '<p>Cost reference: EWZ front-month IV went from 43.4% to 89.4%; buying at 89% with two '
             'sessions left needs a <b>7.9%</b> move to break even, and a retreat to 60% costs 29 vols '
             'of vega even with spot unchanged. Single-name events on the name; macro events on SPY, '
             'VIX or VXX.</p></div>')

    b.append('<h2>10 · Records (mandatory per trade)</h2>')
    b.append('<p>Entry date and expiry; underlying and price; both strikes and deltas; credit; vega per '
             'contract; the p5 assumption used; budget consumed; exit date, price and P&amp;L; and '
             '<b>the exit reason</b> (21 DTE / delta / σ distance / event). October left only 23 '
             'measurable adjustments, which is why "did rolling help" could not be answered at all — '
             'the missing column was the reason.</p>')
