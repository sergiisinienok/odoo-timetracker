"""Stable code per docs/implementation-plan.md Appendix B."""

from __future__ import annotations

from tti.errors import AppError


class PeriodLocked(AppError):
    code = "period_locked"
