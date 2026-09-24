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
import logging
from dataclasses import dataclass
from datetime import date

from tti.config import OdooProfile
from tti.domain.period import PeriodState, resolve_period_state
from tti.lastknown import LastKnownCache
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooUncertain, OdooUnavailable
from tti.periods.errors import PeriodLocked

_CACHE_TTL_SECONDS = 5 * 60

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonthSummary:
    month: str  # "YYYY-MM"
    state: PeriodState


class PeriodService:
    def __init__(self, odoo: OdooClient, profile: OdooProfile) -> None:
        self._odoo = odoo
        self._profile = profile
        # The value can legitimately be None (nothing validated yet), so the
        # cache holds a 1-tuple to tell "cached None" from "not cached".
        self._cache: LastKnownCache[tuple[date | None]] = LastKnownCache(ttl=_CACHE_TTL_SECONDS)

    def invalidate(self, employee_id: int) -> None:
        self._cache.invalidate(employee_id)

    async def state_for(self, employee_id: int, entry_date: date, *, allow_last_known: bool = True) -> PeriodState:
        employee_validated_through = await self._validated_through(employee_id, allow_last_known=allow_last_known)
        return resolve_period_state(entry_date, employee_validated_through, None)

    async def guard(self, employee_id: int, entry_date: date, *, allow_last_known: bool = True) -> None:
        """`allow_last_known=False` is for the moment of writing to Odoo: a
        last-known lock state is fine for accepting input during an outage,
        never for deciding a write may go ahead."""
        if await self.state_for(employee_id, entry_date, allow_last_known=allow_last_known) is PeriodState.LOCKED:
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

    async def _validated_through(self, employee_id: int, *, allow_last_known: bool = True) -> date | None:
        cached = self._cache.fresh(employee_id)
        if cached is not None:
            return cached[0]

        try:
            [record] = await self._odoo.execute_kw(
                "hr.employee", "read", [[employee_id]], {"fields": [self._profile.employee_validated_through]}
            )
        except (OdooUnavailable, OdooUncertain):
            last_known = self._cache.last_known(employee_id) if allow_last_known else None
            if last_known is None:
                raise
            logger.warning("odoo unreachable — serving last-known lock state", extra={"employee_id": employee_id})
            return last_known[0]
        raw = record[self._profile.employee_validated_through]
        value = date.fromisoformat(raw) if raw else None
        self._cache.put(employee_id, (value,))
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
