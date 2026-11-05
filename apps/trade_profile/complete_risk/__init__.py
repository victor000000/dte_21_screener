"""complete_risk — the complete risk workflow (package).

Split out of a single 1,096-line module. The bootstrap header lives HERE rather
than in every submodule: importing any submodule imports this package first, so
the repo root is on sys.path before anything else runs.

A layer subpackage gets an __init__.py even though PEP 420 would let it work
without one -- see the note in apps/trade_profile/__init__.py: anything that
enumerates packages by the presence of this file (setuptools, several linters)
would otherwise silently drop the whole package.

Re-exports the symbols still reached by their old flat path, so callers and the
eventual shim keep working.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root
import bootstrap  # noqa: F401

from ._state import _DISPUTED_REPORTED                  # noqa: F401
from .session import is_market_hours                    # noqa: F401
from .refresh import fetch_extended_hours_prices        # noqa: F401
from .quotes import get_latest_price                    # noqa: F401
from .broker_quotes import get_real_option_quotes        # noqa: F401
from .canonical import canonical_snapshot_spots         # noqa: F401
from .theta_eod import fetch_theta_eod, _table_exists   # noqa: F401

__all__ = ["_DISPUTED_REPORTED", "is_market_hours", "fetch_extended_hours_prices",
           "get_latest_price", "get_real_option_quotes", "canonical_snapshot_spots",
           "fetch_theta_eod", "_table_exists"]
