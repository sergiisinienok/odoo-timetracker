"""Shared base for application errors carrying a stable API error code
(docs/implementation-plan.md Appendix B)."""

from __future__ import annotations


class AppError(Exception):
    code: str = "app_error"
