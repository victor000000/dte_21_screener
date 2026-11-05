"""session.py — see the package docstring."""
import datetime as dt
from zoneinfo import ZoneInfo

def is_market_hours():
    """Check if US equity markets are open (9:30-16:00 ET, Mon-Fri)."""
    import pytz
    et = pytz.timezone('US/Eastern')
    now_et = dt.datetime.now(et)

    # Weekend
    if now_et.weekday() >= 5:
        return False

    # Market hours 9:30-16:00 ET
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now_et <= market_close
