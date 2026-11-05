"""Render ewz roll comparison."""


def render_ewz_roll_comparison(add, legs):
    add('')
    add('## Test 4 - what the rolling did, separately from the repricing')
    add('')
    add('Rolling cannot create a mark-to-market loss: the loss was already in the position, '
        'and closing one strike to open another only realises it. What a roll does change is '
        'the *shape* of what you carry afterwards. Two rolls in this window did exactly that.')
    add('')
    def m(value):
        return f'{value:+,.0f}'.replace('-', '\u2212')

    add('### CRWD, 20 October: rolled down 270 to 260 and went from 8 to 13 short calls')
    add('')
    call_mark = sum(float(r['spot_usd']) for r in legs
                    if r['underlying'] == 'CRWD' and r['day'] >= '2026-10-21'
                    and r['contract'].endswith(('C00260000', 'C00270000')))
    held = -sum(float(r['qty_carried']) for r in legs
                if r['underlying'] == 'CRWD' and r['day'] == '2026-10-20'
                and r['contract'].endswith('C00270000'))
    open_leg = next(r for r in legs if r['contract'].endswith('C00270000')
                    and r['day'] == '2026-10-21')
    last_leg = next(r for r in legs if r['contract'].endswith('C00270000')
                    and r['day'] == '2026-10-23' and r['broker'] == 'IBKR')
    start, finish = float(open_leg['previous_close']), float(last_leg['current_close'])
    counterfactual = -held * 100 * (finish - start)
    add(f'- Before the roll: short **{held:.0f} x 270 calls**. After: short **13 x 260 calls** '
        f'plus 5 long 270 calls, so the short-call count rose from {held:.0f} to 13 and the '
        'strike moved 10 points closer to spot.')
    add(f'- Counterfactual, holding the 20-Oct book unchanged to the 23-Oct close: '
        f'**{m(counterfactual)}** on the calls.')
    add(f'- Actual call mark, 21-23 October: **{m(call_mark)}**.')
    add('- The roll took in roughly $1,700 of credit, so it was close to neutral in cash but '
        'it put the short strike where the 23-Oct rally arrived and increased the size.')
    add('')
    add('### EWZ, 19 October: a 1x3 ratio roll into calls too far away to help')
    add('')
    ewz20 = [r for r in legs if r['underlying'] == 'EWZ' and r['day'] == '2026-10-20']
    short_call = sum(float(r['spot_usd']) for r in ewz20
                     if r['contract'].endswith(('C00043000', 'C00046000')))
    long_call = sum(float(r['spot_usd']) for r in ewz20 if r['contract'].endswith('C00050000'))
    add(f'- On the +2.41% session the short 43/46 calls lost **{m(short_call)}** while the '
        f'54 long 50 calls made **{m(long_call)}** - about '
        f'{abs(long_call / short_call) * 100:.0f}% cover.')
    add('- A 50 strike against a 43 spot is a hedge for a 15% move, not for the 2-3% moves '
        'that were generating the daily losses. It paid for itself only if EWZ ran.')
    add('')
