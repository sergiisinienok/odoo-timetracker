"""Pure rule: hours must be a positive multiple of 0.25 (step 1.5)."""

from __future__ import annotations

_QUARTER_HOUR_HUNDREDTHS = 25


def is_valid_increment(hours: float) -> bool:
    if hours <= 0:
        return False
    # Work in hundredths to sidestep float representation noise
    # (3.3 * 100 == 330.00000000000006 in plain IEEE-754 arithmetic).
    return round(hours * 100) % _QUARTER_HOUR_HUNDREDTHS == 0
