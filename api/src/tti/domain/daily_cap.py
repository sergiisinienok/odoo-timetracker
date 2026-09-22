"""Pure rule: an employee's total hours for one date must not exceed the
configured daily cap.

The brief is explicit this is a hard limit, not a warning (see
docs/brief.md, "On the daily cap"). `existing` is the caller's
responsibility to compute correctly — once the outbox exists (step 2.3),
that means Odoo lines *plus* pending outbox rows for that employee and
date, not Odoo lines alone (Appendix D: excluding pending rows would let
an employee exceed the cap during an outage). This function itself has
no I/O and doesn't care where `existing` came from.
"""

from __future__ import annotations

from decimal import Decimal

from tti.domain.errors import DailyCapExceeded


def validate_daily_cap(existing: Decimal, new: Decimal, cap: Decimal) -> None:
    total = existing + new
    if total > cap:
        raise DailyCapExceeded(f"{total} would exceed the daily cap of {cap}")
