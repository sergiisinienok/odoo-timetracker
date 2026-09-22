"""Pure rule: is a date open for editing, or locked.

Locking is date-based, not line-based: a date is locked if it falls on
or before the employee's validated-through date, falling back to the
company's when the employee has none.

**No-signal default, made explicit (docs/decisions/0003):** this
instance has no company-level validated-through field at all
(`company_validated_through` is null in odoo_profile.json — confirmed
absent, not merely unconfirmed). When *neither* signal exists — an
employee nobody has ever validated, on an instance with no company
fallback either — every date resolves OPEN rather than LOCKED. Decision
0003 flagged this exact default as "plausibly yes: an employee nobody
has validated yet should stay editable" and left it for whoever
implemented this function; the alternative (locked with no signal) would
mean a brand-new employee could never log a first month until an
approver validates them once, which is clearly wrong.
"""

from __future__ import annotations

from datetime import date
from enum import Enum


class PeriodState(Enum):
    OPEN = "open"
    LOCKED = "locked"


def resolve_period_state(
    entry_date: date,
    employee_validated_through: date | None,
    company_validated_through: date | None,
) -> PeriodState:
    validated_through = employee_validated_through or company_validated_through
    if validated_through is not None and entry_date <= validated_through:
        return PeriodState.LOCKED
    return PeriodState.OPEN
