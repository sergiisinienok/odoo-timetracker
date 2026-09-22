"""The write path — step 2.3.

Enqueue as pending, then attempt the Odoo write inline. Success marks it
synced and stores odoo_line_id. OdooUnavailable or OdooUncertain leaves
it pending (the caller returns 202, not-yet-synced). OdooRejected marks
it failed immediately, because retrying a rejected write only produces
the same rejection.

The outbox row's own id doubles as the Odoo-side app entry id
(profile.app_entry_id_field) — see outbox/models.py.

`attempt_row` takes an already-open session with the row already locked
(`SELECT ... FOR UPDATE`) by the caller, and commits within that same
transaction — the lock has to be held for the whole attempt, Odoo call
included, or two workers could both pass the "is this still pending"
check before either commits. See outbox/worker.py for the
SKIP LOCKED dequeue that acquires it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.config import OdooProfile
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooRejected, OdooUncertain, OdooUnavailable
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState
from tti.periods.service import PeriodService

logger = logging.getLogger(__name__)

# 10s, 30s, 2m, 10m, 30m, capped at 1h — the delay *before* the Nth retry,
# N being how many attempts have already been made (the inline attempt at
# enqueue time counts as the first).
_BACKOFF_SCHEDULE_SECONDS = [10, 30, 120, 600, 1800, 3600]


def backoff_seconds(attempts_made: int) -> int:
    index = min(max(attempts_made, 1), len(_BACKOFF_SCHEDULE_SECONDS)) - 1
    return _BACKOFF_SCHEDULE_SECONDS[index]


@dataclass(frozen=True)
class EnqueueResult:
    outbox_id: UUID
    state: OutboxState
    odoo_line_id: int | None
    last_error: str | None


class OutboxService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        odoo: OdooClient,
        profile: OdooProfile,
        periods: PeriodService,
    ) -> None:
        self._session_factory = session_factory
        self._odoo = odoo
        self._profile = profile
        self._periods = periods

    async def enqueue_create(
        self,
        *,
        employee_id: int,
        entry_date: date,
        hours: Decimal,
        assignment_id: str,
        project_id: int,
        so_line_id: int | None,
        note: str,
    ) -> EnqueueResult:
        outbox_id = uuid4()
        async with self._session_factory() as session:
            row = OutboxRow(
                id=outbox_id,
                employee_id=employee_id,
                op=OutboxOp.CREATE.value,
                entry_date=entry_date,
                hours=hours,
                assignment=assignment_id,
                project_id=project_id,
                so_line_id=so_line_id,
                note=note,
                state=OutboxState.PENDING.value,
                attempts=0,
            )
            session.add(row)
            await session.commit()

        # This is the first attempt ever made for this row — the inline
        # attempt, made synchronously within the same request that
        # created it. No lock contention is realistically possible yet
        # (nothing else knows this row exists), but still go through a
        # locking SELECT so there's exactly one code path for "lock, then
        # attempt, then commit," shared with the worker's retries.
        async with self._session_factory() as session:
            row = (
                await session.execute(select(OutboxRow).where(OutboxRow.id == outbox_id).with_for_update())
            ).scalar_one()
            await attempt_row(session, row, self._odoo, self._profile, self._periods, reconcile_first=False)

        async with self._session_factory() as session:
            row = await session.get(OutboxRow, outbox_id)
            assert row is not None
            return EnqueueResult(
                outbox_id=row.id,
                state=OutboxState(row.state),
                odoo_line_id=row.odoo_line_id,
                last_error=row.last_error,
            )


def _odoo_vals(row: OutboxRow, app_entry_id_field: str) -> dict[str, object]:
    return {
        "date": row.entry_date.isoformat(),
        "employee_id": row.employee_id,
        "project_id": row.project_id,
        "unit_amount": float(row.hours) if row.hours is not None else None,
        "name": row.note or " ",
        "so_line": row.so_line_id if row.so_line_id is not None else False,
        app_entry_id_field: str(row.id),
    }


async def attempt_row(
    session: AsyncSession,
    row: OutboxRow,
    odoo: OdooClient,
    profile: OdooProfile,
    periods: PeriodService,
    *,
    reconcile_first: bool,
) -> None:
    """One write attempt against Odoo for one already-locked outbox row,
    committing within the caller's transaction. `reconcile_first` is the
    only thing that differs between the inline attempt and a worker
    retry: the inline attempt is always the first attempt ever made for
    this row, so nothing could exist in Odoo yet; every attempt after
    that must check first, because a prior attempt's outcome could have
    been genuinely uncertain rather than a real failure.
    """
    if row.state != OutboxState.PENDING.value:
        return  # already resolved

    if reconcile_first and row.op == OutboxOp.CREATE.value:
        existing = await odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[(profile.app_entry_id_field, "=", str(row.id))]],
            {"fields": ["id"]},
        )
        if existing:
            row.state = OutboxState.SYNCED.value
            row.odoo_line_id = existing[0]["id"]
            row.attempts += 1
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info("outbox row reconciled to existing Odoo line", extra={"outbox_id": str(row.id)})
            return

    vals = _odoo_vals(row, profile.app_entry_id_field)
    try:
        line_id = await odoo.execute_kw("account.analytic.line", "create", [vals])
    except (OdooUnavailable, OdooUncertain) as exc:
        row.attempts += 1
        row.last_error = str(exc)
        row.next_attempt = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(row.attempts))
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return
    except OdooRejected as exc:
        row.attempts += 1
        row.state = OutboxState.FAILED.value
        row.last_error = str(exc)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        periods.invalidate(row.employee_id)
        return

    row.attempts += 1
    row.state = OutboxState.SYNCED.value
    row.odoo_line_id = line_id
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
