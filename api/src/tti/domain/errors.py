"""Errors raised by the pure domain rules — stable codes per
docs/implementation-plan.md Appendix B."""

from __future__ import annotations

from tti.errors import AppError


class InvalidIncrement(AppError):
    code = "invalid_increment"


class DailyCapExceeded(AppError):
    code = "daily_cap_exceeded"
