"""Stable code per docs/implementation-plan.md Appendix B — extended here:
the plan's own error-code list doesn't name a code for "Odoo rejected the
write," only `odoo_unavailable` (which means retryable, the opposite of
what OdooRejected means). `odoo_rejected` fills that gap."""

from __future__ import annotations

from tti.errors import AppError


class OdooWriteRejected(AppError):
    code = "odoo_rejected"
