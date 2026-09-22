"""Errors raised by entry mutation that aren't pure domain rules — these
need Odoo I/O (the employee's actual assignment list, or the target
line's actual owner), so they can't live in tti.domain."""

from __future__ import annotations

from tti.errors import AppError


class AssignmentNotHeld(AppError):
    code = "assignment_not_held"


class EntryNotOwned(AppError):
    """Stable code per docs/implementation-plan.md Appendix B — extended
    here: the plan's own error-code list has nothing for "this line isn't
    yours" (step 2.4's "editing another employee's line returns 403"),
    only assignment_not_held, which is a different failure."""

    code = "entry_not_owned"
