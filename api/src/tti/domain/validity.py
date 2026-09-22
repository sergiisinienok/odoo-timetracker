"""Pure rule: is this date within the assignment's validity window.

An assignment with no dates set is open-ended, not invalid (step 1.4's
own spec) — currently *every* assignment, since
assignment_start_source/assignment_end_source are null in
odoo_profile.json, see
docs/decisions/0005-no-assignment-validity-date-field.md. This still
enforces real start/end values when they're not None, so it needs no
changes if that profile ever gets populated.
"""

from __future__ import annotations

from datetime import date

from tti.domain.errors import AssignmentNotValidOnDate


def validate_within_assignment(entry_date: date, start: date | None, end: date | None) -> None:
    if start is not None and entry_date < start:
        raise AssignmentNotValidOnDate(f"{entry_date} is before this assignment's start date {start}")
    if end is not None and entry_date > end:
        raise AssignmentNotValidOnDate(f"{entry_date} is after this assignment's end date {end}")
