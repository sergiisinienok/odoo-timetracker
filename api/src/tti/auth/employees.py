"""Resolve a Google-verified email to an hr.employee. See
docs/decisions/0007-google-hosted-domain.md for the domain this is
enforced against, and step 1.3 for why zero and multiple matches are
distinct hard failures."""

from __future__ import annotations

import time
from dataclasses import dataclass

from tti.auth.errors import EmployeeAmbiguous, EmployeeNotFound
from tti.odoo.client import OdooClient

_CACHE_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ResolvedEmployee:
    employee_id: int
    name: str
    timezone: str


class EmployeeResolver:
    def __init__(self, odoo: OdooClient) -> None:
        self._odoo = odoo
        self._cache: dict[str, tuple[float, ResolvedEmployee]] = {}

    async def resolve(self, email: str) -> ResolvedEmployee:
        cached = self._cache.get(email)
        if cached is not None:
            expires_at, resolved = cached
            if time.monotonic() < expires_at:
                return resolved

        matches = await self._odoo.execute_kw(
            "hr.employee",
            "search_read",
            [[("work_email", "=", email), ("active", "=", True)]],
            {"fields": ["id", "name", "tz"]},
        )

        if not matches:
            raise EmployeeNotFound(f"No active employee with work_email {email!r}")
        if len(matches) > 1:
            raise EmployeeAmbiguous(f"{len(matches)} active employees share work_email {email!r}")

        record = matches[0]
        resolved = ResolvedEmployee(employee_id=record["id"], name=record["name"], timezone=record["tz"] or "UTC")
        self._cache[email] = (time.monotonic() + _CACHE_TTL_SECONDS, resolved)
        return resolved
