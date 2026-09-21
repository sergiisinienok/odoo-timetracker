"""Pure rule: is this date within the assignment's validity window.

An assignment with no dates set is open-ended, not invalid (step 1.4's
own spec) — currently *every* assignment, since
assignment_start_source/assignment_end_source are null in
odoo_profile.json, see
docs/decisions/0005-no-assignment-validity-date-field.md. This still
reads real start/end values when they're not None, so it needs no
changes if that profile ever gets populated.
"""

from __future__ import annotations


def is_date_within_validity(date: str, start: str | None, end: str | None) -> bool:
    if start is not None and date < start:
        return False
    if end is not None and date > end:
        return False
    return True
