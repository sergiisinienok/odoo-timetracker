"""Errors raised by entry mutation that aren't pure domain rules — these
need Odoo I/O (the employee's actual project list, a task's project and
state, or the target line's actual owner and billing marker), so they can't
live in tti.domain."""

from __future__ import annotations

from tti.errors import AppError


class ProjectNotHeld(AppError):
    """Replaces assignment_not_held (decision 0011)."""

    code = "project_not_held"


class TaskRequired(AppError):
    code = "task_required"


class TaskNotInProject(AppError):
    code = "task_not_in_project"


class TaskNotOpen(AppError):
    code = "task_not_open"


class BillingSetByApprover(AppError):
    """The line carries an approver's Sales Order Item override; moving it to
    another project or task would drop it or carry it to work it was never
    meant for (decision 0011)."""

    code = "billing_set_by_approver"


class EntryNotOwned(AppError):
    """Stable code per docs/implementation-plan.md Appendix B — extended
    here: the plan's own error-code list has nothing for "this line isn't
    yours" (step 2.4's "editing another employee's line returns 403"),
    only project_not_held, which is a different failure."""

    code = "entry_not_owned"
