"""Errors raised by entry creation that aren't pure domain rules — this
one needs to know the employee's actual assignment list, which means
Odoo I/O, so it can't live in tti.domain. Stable code per
docs/implementation-plan.md Appendix B."""

from __future__ import annotations

from tti.errors import AppError


class AssignmentNotHeld(AppError):
    code = "assignment_not_held"
