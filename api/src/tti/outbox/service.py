"""The write path — steps 2.3 and 2.4.

Enqueue as pending, then attempt the Odoo write inline. Success marks it
synced (and, for a create, stores odoo_line_id). OdooUnavailable or
OdooUncertain leaves it pending (the caller returns 202, not-yet-synced).
OdooRejected marks it failed immediately, because retrying a rejected
write only produces the same rejection.

The outbox row's own id doubles as the Odoo-side app entry id
(profile.app_entry_id_field) — see outbox/models.py.

`attempt_row` takes an already-open session with the row already locked
(`SELECT ... FOR UPDATE`) by the caller, and commits within that same
transaction — the lock has to be held for the whole attempt, Odoo call
included, or two workers could both pass the "is this still pending"
check before either commits. See outbox/worker.py for the
SKIP LOCKED dequeue that acquires it.

Reconcile-before-act on any retry (attempts > 0), for create *and*
delete — not just create. A create retry needs to check whether a prior,
genuinely-uncertain attempt already created the line (search by app
entry id) before creating a second one. A delete retry needs the mirror
image: check whether a prior uncertain attempt already deleted it,
because retrying unlink() on an already-gone id raises
odoo.exceptions.MissingError — an OdooRejected, which would wrongly mark
an already-successful delete as failed. Update doesn't need this:
re-applying the same field values to a line that still exists is already
idempotent.
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
        row = OutboxRow(
            id=uuid4(),
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
        return await self._enqueue_and_attempt(row)

    async def enqueue_update(
        self,
        *,
        employee_id: int,
        odoo_line_id: int,
        entry_date: date,
        hours: Decimal,
        assignment_id: str,
        project_id: int,
        so_line_id: int | None,
        note: str,
    ) -> EnqueueResult:
        row = OutboxRow(
            id=uuid4(),
            employee_id=employee_id,
            op=OutboxOp.UPDATE.value,
            entry_date=entry_date,
            hours=hours,
            assignment=assignment_id,
            project_id=project_id,
            so_line_id=so_line_id,
            note=note,
            odoo_line_id=odoo_line_id,
            state=OutboxState.PENDING.value,
            attempts=0,
        )
        return await self._enqueue_and_attempt(row)

    async def enqueue_delete(self, *, employee_id: int, odoo_line_id: int, entry_date: date) -> EnqueueResult:
        row = OutboxRow(
            id=uuid4(),
            employee_id=employee_id,
            op=OutboxOp.DELETE.value,
            entry_date=entry_date,
            odoo_line_id=odoo_line_id,
            state=OutboxState.PENDING.value,
            attempts=0,
        )
        return await self._enqueue_and_attempt(row)

    async def _enqueue_and_attempt(self, row: OutboxRow) -> EnqueueResult:
        outbox_id = row.id
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

        # This is the first attempt ever made for this row — the inline
        # attempt, made synchronously within the same request that
        # created it. No lock contention is realistically possible yet
        # (nothing else knows this row exists), but still go through a
        # locking SELECT so there's exactly one code path for "lock, then
        # attempt, then commit," shared with the worker's retries.
        async with self._session_factory() as session:
            locked = (
                await session.execute(select(OutboxRow).where(OutboxRow.id == outbox_id).with_for_update())
            ).scalar_one()
            await attempt_row(session, locked, self._odoo, self._profile, self._periods, reconcile_first=False)

        async with self._session_factory() as session:
            final = await session.get(OutboxRow, outbox_id)
            assert final is not None
            return EnqueueResult(
                outbox_id=final.id,
                state=OutboxState(final.state),
                odoo_line_id=final.odoo_line_id,
                last_error=final.last_error,
            )

    async def pending_hours_for(self, employee_id: int, entry_date: date) -> Decimal:
        """Sum of pending *create* rows' hours for this employee+date —
        the daily cap needs this so an Odoo outage doesn't let someone
        exceed it (Appendix D). Pending update/delete rows aren't
        included: their hours describe a change to a line already
        counted on the Odoo side, not new hours on top of it."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OutboxRow.hours).where(
                    OutboxRow.employee_id == employee_id,
                    OutboxRow.entry_date == entry_date,
                    OutboxRow.state == OutboxState.PENDING.value,
                    OutboxRow.op == OutboxOp.CREATE.value,
                )
            )
            total = Decimal("0")
            for hours in result.scalars():
                if hours is not None:
                    total += hours
            return total

    async def rows_for_month(self, employee_id: int, start_date: date, end_date: date) -> list[OutboxRow]:
        """Pending and failed rows overlapping [start_date, end_date] —
        for GET /api/entries's outbox overlay (step 2.4)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OutboxRow).where(
                    OutboxRow.employee_id == employee_id,
                    OutboxRow.entry_date >= start_date,
                    OutboxRow.entry_date <= end_date,
                    OutboxRow.state.in_([OutboxState.PENDING.value, OutboxState.FAILED.value]),
                )
            )
            return list(result.scalars())


def _create_vals(row: OutboxRow, app_entry_id_field: str) -> dict[str, object]:
    return {
        "date": row.entry_date.isoformat(),
        "employee_id": row.employee_id,
        "project_id": row.project_id,
        "unit_amount": float(row.hours) if row.hours is not None else None,
        "name": row.note or " ",
        "so_line": row.so_line_id if row.so_line_id is not None else False,
        app_entry_id_field: str(row.id),
    }


def _update_vals(row: OutboxRow) -> dict[str, object]:
    return {
        "date": row.entry_date.isoformat(),
        "project_id": row.project_id,
        "unit_amount": float(row.hours) if row.hours is not None else None,
        "name": row.note or " ",
        "so_line": row.so_line_id if row.so_line_id is not None else False,
    }


async def _mark_pending_retry(session: AsyncSession, row: OutboxRow, exc: Exception) -> None:
    row.attempts += 1
    row.last_error = str(exc)
    row.next_attempt = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(row.attempts))
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()


async def _mark_failed(session: AsyncSession, row: OutboxRow, periods: PeriodService, exc: Exception) -> None:
    row.attempts += 1
    row.state = OutboxState.FAILED.value
    row.last_error = str(exc)
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    # Odoo itself rejecting a write is a signal our cached validated-through
    # date might be stale — invalidate eagerly rather than waiting out the TTL.
    periods.invalidate(row.employee_id)


async def _mark_synced(session: AsyncSession, row: OutboxRow, odoo_line_id: int) -> None:
    row.attempts += 1
    row.state = OutboxState.SYNCED.value
    row.odoo_line_id = odoo_line_id
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()


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
    this row, so nothing could have happened in Odoo yet; every attempt
    after that must check first, because a prior attempt's outcome could
    have been genuinely uncertain rather than a real failure.
    """
    if row.state != OutboxState.PENDING.value:
        return  # already resolved

    if row.op == OutboxOp.CREATE.value:
        await _attempt_create(session, row, odoo, profile, periods, reconcile_first=reconcile_first)
    elif row.op == OutboxOp.UPDATE.value:
        await _attempt_update(session, row, odoo, periods)
    elif row.op == OutboxOp.DELETE.value:
        await _attempt_delete(session, row, odoo, periods, reconcile_first=reconcile_first)
    else:
        raise ValueError(f"unknown outbox op {row.op!r}")


async def _attempt_create(
    session: AsyncSession,
    row: OutboxRow,
    odoo: OdooClient,
    profile: OdooProfile,
    periods: PeriodService,
    *,
    reconcile_first: bool,
) -> None:
    if reconcile_first:
        existing = await odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[(profile.app_entry_id_field, "=", str(row.id))]],
            {"fields": ["id"]},
        )
        if existing:
            await _mark_synced(session, row, existing[0]["id"])
            logger.info("outbox create reconciled to existing Odoo line", extra={"outbox_id": str(row.id)})
            return

    try:
        line_id = await odoo.execute_kw("account.analytic.line", "create", [_create_vals(row, profile.app_entry_id_field)])
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
        return
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
        return
    await _mark_synced(session, row, line_id)


async def _attempt_update(session: AsyncSession, row: OutboxRow, odoo: OdooClient, periods: PeriodService) -> None:
    assert row.odoo_line_id is not None
    try:
        await odoo.execute_kw("account.analytic.line", "write", [[row.odoo_line_id], _update_vals(row)])
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
        return
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
        return
    await _mark_synced(session, row, row.odoo_line_id)


async def _attempt_delete(
    session: AsyncSession, row: OutboxRow, odoo: OdooClient, periods: PeriodService, *, reconcile_first: bool
) -> None:
    assert row.odoo_line_id is not None

    if reconcile_first:
        existing = await odoo.execute_kw(
            "account.analytic.line", "search_read", [[("id", "=", row.odoo_line_id)]], {"fields": ["id"]}
        )
        if not existing:
            # Already gone — a prior attempt's outcome was uncertain but it
            # actually succeeded. Unlinking again would raise MissingError
            # (OdooRejected), which would wrongly report an
            # already-successful delete as failed.
            await _mark_synced(session, row, row.odoo_line_id)
            logger.info("outbox delete reconciled: already gone", extra={"outbox_id": str(row.id)})
            return

    try:
        await odoo.execute_kw("account.analytic.line", "unlink", [[row.odoo_line_id]])
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
        return
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
        return
    await _mark_synced(session, row, row.odoo_line_id)
