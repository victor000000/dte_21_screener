"""Render strategy provenance."""


def render_strategy_provenance(b):
    b.append('<h2>11 · Provenance of each parameter</h2>')
    b.append('<table><tr><th>Rule / parameter</th><th>Value</th><th>Nature</th><th>Note</th></tr>')
    rows = [
        ('No rolling', '—', 'm', '38% vs 35% after the trigger, n=318'),
        ('p5_Δσ per name', '2.5–52', 'm', 'measured, but 30-day ATM applied to 49 DTE / 20 delta; biased low'),
        ('21 DTE exit', '—', 'd', 'touch 40% → 25%; net of cost not measured'),
        ('Delta win rate', '—', 'd', 'exact arithmetic, only without drift or spread'),
        ('Tail budget', '5%', 'c', 'the most consequential number here, and a pure preference'),
        ('Delta band', '0.16–0.22', 'c', 'the sensitivity is exact; the band itself has no basis'),
        ('Entry DTE', '45 ± 5', 'c', 'unverified'),
        ('IVR threshold', '50', 'c', 'a convention; measured as a tail amplifier'),
        ('RV lookback', '60 sessions', 'm', 'set by E3: 60-day 0.227 beats 10-day 0.191'),
        ('Liquidity gates', 'OI 500 / 5%', 'c', 'conventions'),
        ('Stop thresholds', '0.35 / 0.5σ', 'c', 'no basis, and possibly the wrong sign'),
        ('N (name count)', 'undefined', 'x', 'only "1/N" is written'),
        ('Event cut size', 'undefined', 'x', 'only "cut or close" is written'),
        ('Tail budget size', 'undefined', 'x', '"size to the gap" has no formula'),
    ]
    for name, val, kind, note in rows:
        lab = {'m': ('t-m', 'measured'), 'd': ('t-d', 'derived'),
               'c': ('t-c', 'convention'), 'x': ('t-x', 'undefined')}[kind]
        b.append(f'<tr><td>{name}</td><td>{val}</td>'
                 f'<td><span class="tag {lab[0]}">{lab[1]}</span></td><td>{note}</td></tr>')
    b.append('</table>')
    b.append('<div class="note"><b>The meta-problem.</b> Nine parameters above are still unquantified, '
             'and each one\'s optimum depends on the other eight. The sample is three years, five names, '
             'roughly 100 independent observations. <b>Treat every "convention" as a frozen constant '
             'for twelve months</b> and only record during that year. Otherwise the parameters will be '
             'tuned on the same data until they look effective, and then fail out of sample.</div>')

    b.append('<h2>12 · This cycle (opens 2026-10-30, expires 2026-12-18)</h2>')
    b.append('<table><tr><th>Item</th><th>Value</th></tr>'
             '<tr><td>Close</td><td>2026-10-30 (November 20 expiry, 21 DTE)</td></tr>'
             '<tr><td>New expiry</td><td>2026-12-18 (49 DTE)</td></tr>'
             '<tr><td>Suggested entry</td><td><b>2026-11-04 or 11-05</b>, after the 11/03 midterms, or half size on 10/30</td></tr>'
             '<tr><td>Exit</td><td><b>2026-11-25 (Wednesday)</b>, because 11/27 is a half session after Thanksgiving</td></tr>'
             '<tr><td>Excluded for earnings</td><td>SWKS (11/03), CRWD (about 12/02–04)</td></tr>'
             '<tr><td>Eligible</td><td>META, EWZ, TLT, SPX-type ETFs</td></tr></table>')

    b.append('<footer>Quantitative evidence: <a href="evidence.html">evidence.html</a>. Data '
             'requirements: <code>data_providers/docs/requirements/DTE21_P5_SIZING_DATA_REQUIREMENTS_20261025.md</code>. '
             'Computation: <code>apps/trade_profile/strategy_quantification_20261025.py</code>.</footer>')
