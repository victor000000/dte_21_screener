"""Compare CN delivery codes across YMM and YYMM broker formats."""
import re


def option_key(broker, underlying, expiry, strike, call_put):
    if broker == "浙商期货":
        underlying = underlying.upper().replace(" ", "")
        match = re.fullmatch(r"([A-Z]+)(\d{4})", underlying)
        if match:
            underlying = match[1] + match[2][1:]
    # Expiry remains part of identity, including its full year.
    return underlying, expiry, strike, call_put


def valid_broker_symbol(broker, symbol, underlying, strike, call_put):
    """CN delivery codes are valid only for their broker and structured leg."""
    symbol = (symbol or "").upper().replace(" ", "")
    if re.fullmatch(r"[A-Z][A-Z0-9]+[0-9]{6}[CP][0-9]{8}", symbol):
        return True
    if re.fullmatch(r"[A-Z]{1,6}", symbol):
        return True
    if broker != "浙商期货":
        return False
    match = re.fullmatch(r"([A-Z]+[0-9]{3,4})-?([CP])-?([0-9]+(?:\.[0-9]+)?)", symbol)
    if not match or strike is None:
        return False
    if len(match[1]) == len(underlying or "") and match[1] != (underlying or "").upper():
        return False
    parsed = option_key(broker, match[1], None, float(match[3]), match[2])
    stored = option_key(broker, underlying or "", None, strike, call_put)
    return parsed == stored


def invalid_broker_symbol_count(con):
    rows = con.execute("SELECT broker,symbol,underlying,strike,call_put FROM broker_positions").fetchall()
    return sum(not valid_broker_symbol(*row) for row in rows)
