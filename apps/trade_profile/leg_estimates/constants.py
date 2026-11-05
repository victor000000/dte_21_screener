"""Thresholds for the per-leg read, in one place.

These are the numbers that decide what the narrative CALLS a leg -- past the
target, approaching it, or a loss that matters -- so they are the difference
between a report and an opinion. They were module-level in a 289-line file;
they are the same values, named here so the report and the narrative cannot
drift apart.
"""
from shared.rates import R_US as R

HARVEST = 50.0        # the 50% profit target, the user's own rule
NEAR = 10.0           # "approaching" = within this many points of it
STALE = 5.0           # mark/model gap worth naming, in percentage points
