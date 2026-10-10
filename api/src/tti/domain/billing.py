"""Pure rule: whether a new timesheet line is billable (decision 0011).

Billability is decided at three levels. Ops sets the project default and may
override it per task; the approver may override a single line afterwards, in
Odoo, which is not this function's business. In Odoo "billable" means exactly
one thing — `so_line` is set — so the answer is the order line to write, or
None for an unbillable line.

No I/O. The task's Odoo value ("Same as project" / "Billable" / "Not
billable", read from `profile.task_billable_*_value`) is mapped to
`TaskOverride` at the Odoo boundary; the domain never compares raw strings.
"""

from __future__ import annotations

from enum import Enum

BILLABLE_WITHOUT_ORDER_LINE = "billable_without_order_line"


class TaskOverride(Enum):
    SAME_AS_PROJECT = "same_as_project"
    BILLABLE = "billable"
    NOT_BILLABLE = "not_billable"


def resolve_billing(
    project_billable: bool,
    task_override: TaskOverride,
    mapped_so_line_id: int | None,
) -> tuple[int | None, str | None]:
    """Return (so_line_id or None, warning or None).

    A line that resolves billable but has no mapped order line to bill
    against is written unbillable and flagged — the employee is not blocked
    (decision 0011, assumption 2).
    """
    if task_override is TaskOverride.SAME_AS_PROJECT:
        billable = project_billable
    else:
        billable = task_override is TaskOverride.BILLABLE
    if not billable:
        return None, None
    if mapped_so_line_id is None:
        return None, BILLABLE_WITHOUT_ORDER_LINE
    return mapped_so_line_id, None
