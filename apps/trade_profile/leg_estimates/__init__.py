"""leg_estimates — per-leg P&L: the mark, the model, and the read (package).

Split out of a single 289-line module. The bootstrap header lives HERE rather
than in every submodule, because importing any submodule imports this package
first, so the repo root is on sys.path before anything else runs. (A submodule
executed directly by path would not get that -- only `__main__.py` is meant to
be run that way, and it carries its own header.)

Re-exports the whole former module surface. The compatibility shim promises
identity (`sys.modules[__name__] = _m`), so a name that callers reached through
`leg_estimates.<name>` has to stay reachable here -- including the ones with a
leading underscore.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root
import bootstrap  # noqa: F401

from .constants import HARVEST, NEAR, STALE, R          # noqa: F401
from .collect import collect                            # noqa: F401
from .narrative import narrative                        # noqa: F401
from .persist import save                               # noqa: F401
from .report import console, markdown                   # noqa: F401
from .run import main, rt_moves_for                     # noqa: F401

__all__ = ["HARVEST", "NEAR", "STALE", "R", "collect", "narrative", "save",
           "console", "markdown", "main", "rt_moves_for"]
