"""Stable error codes per docs/implementation-plan.md Appendix B."""

from __future__ import annotations


class EntryError(Exception):
    code: str = "entry_error"


class AssignmentNotHeld(EntryError):
    code = "assignment_not_held"


class InvalidIncrement(EntryError):
    code = "invalid_increment"


class AssignmentNotValidOnDate(EntryError):
    code = "assignment_not_valid_on_date"
