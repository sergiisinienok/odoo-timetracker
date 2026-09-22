"""Period state — one place answers "may this employee edit this date?"
(step 2.2).

Reads the employee's validated-through date from Odoo
(`profile.employee_validated_through`), cached 5 minutes per employee.
The company-level fallback `resolve_period_state()` supports is never
read here — `odoo_profile.json`'s `company_validated_through` is `null`,
confirmed genuinely absent on this instance (see
docs/decisions/0003-no-company-validated-through-field.md), not merely
unconfirmed — so it's always passed as `None`.

Cache invalidation: any `OdooRejected` while attempting a write is
treated as a signal the cached validated-through date might be stale (an
approver could have validated the month moments after our last read),
so the write path invalidates eagerly rather than waiting out the TTL —
see entries/service.py.
"""

from __future__ import annotations

import calendar
import time
from dataclasses import dataclass
from datetime import date

from tti.config import OdooProfile
from tti.domain.period import PeriodState, resolve_period_state
from tti.odoo.client import OdooClient
from tti.periods.errors import PeriodLocked

_CACHE_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class MonthSummary:
    month: str  # "YYYY-MM"
    state: PeriodState


class PeriodService:
    def __init__(self, odoo: OdooClient, profile: OdooProfile) -> None:
        self._odoo = odoo
        self._profile = profile
        self._cache: dict[int, tuple[float, date | None]] = {}

    def invalidate(self, employee_id: int) -> None:
        self._cache.pop(employee_id, None)

    async def state_for(self, employee_id: int, entry_date: date) -> PeriodState:
        employee_validated_through = await self._validated_through(employee_id)
        return resolve_period_state(entry_date, employee_validated_through, None)

    async def guard(self, employee_id: int, entry_date: date) -> None:
        if await self.state_for(employee_id, entry_date) is PeriodState.LOCKED:
            raise PeriodLocked(f"{entry_date} is locked for employee {employee_id}")

    async def months_for(self, employee_id: int, today: date, count: int = 12) -> list[MonthSummary]:
        employee_validated_through = await self._validated_through(employee_id)
        months = _last_n_months(today, count)
        summaries = []
        for year, month in months:
            last_day = date(year, month, calendar.monthrange(year, month)[1])
            state = resolve_period_state(last_day, employee_validated_through, None)
            summaries.append(MonthSummary(month=f"{year:04d}-{month:02d}", state=state))
        return summaries

    async def _validated_through(self, employee_id: int) -> date | None:
        cached = self._cache.get(employee_id)
        if cached is not None:
            expires_at, value = cached
            if time.monotonic() < expires_at:
                return value

        [record] = await self._odoo.execute_kw(
            "hr.employee", "read", [[employee_id]], {"fields": [self._profile.employee_validated_through]}
        )
        raw = record[self._profile.employee_validated_through]
        value = date.fromisoformat(raw) if raw else None
        self._cache[employee_id] = (time.monotonic() + _CACHE_TTL_SECONDS, value)
        return value


def _last_n_months(anchor: date, count: int) -> list[tuple[int, int]]:
    """The `count` months ending with `anchor`'s month, oldest first."""
    year, month = anchor.year, anchor.month
    months: list[tuple[int, int]] = []
    for _ in range(count):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))
