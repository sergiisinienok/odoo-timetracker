"""Pure rule: hours must be a positive multiple of 0.25 (steps 1.5/2.1).

Decimal, not float: a quarter-hour grid is exactly representable in
decimal but not in binary floating point (0.25 itself is fine, but sums
like 3.3 drift), so there's no epsilon-fudging needed the way there would
be with float arithmetic — callers just need to construct the Decimal
from a string/JSON-number representation, not from an existing float
(`Decimal(str(hours))`, never `Decimal(hours)` if `hours` started as a
float).
"""

from __future__ import annotations

from decimal import Decimal

from tti.domain.errors import InvalidIncrement

_QUARTER_HOUR = Decimal("0.25")


def validate_increment(hours: Decimal) -> None:
    if hours <= 0 or hours % _QUARTER_HOUR != 0:
        raise InvalidIncrement(f"{hours} is not a positive multiple of 0.25")
