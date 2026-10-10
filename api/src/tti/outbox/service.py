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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.config import OdooProfile
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooRejected, OdooUnavailable, OdooUncertain
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState
from tti.periods.errors import PeriodLocked
from tti.periods.service import PeriodService

logger = logging.getLogger(__name__)

# A row failed because its month locked while it waited — recorded as the
# start of last_error so the digest and the entry service can tell it from an
# Odoo rejection. See docs/decisions/0010.
PERIOD_LOCKED_PREFIX = "period_locked: "

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
        project_id: int,
        task_id: int | None,
        so_line_id: int | None,
        note: str,
    ) -> EnqueueResult:
        row = OutboxRow(
            id=uuid4(),
            employee_id=employee_id,
            op=OutboxOp.CREATE.value,
            entry_date=entry_date,
            hours=hours,
            project_id=project_id,
            task_id=task_id,
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
        project_id: int,
        task_id: int | None,
        so_line_id: int | None,
        write_billing: bool,
        note: str,
    ) -> EnqueueResult:
        row = OutboxRow(
            id=uuid4(),
            employee_id=employee_id,
            op=OutboxOp.UPDATE.value,
            entry_date=entry_date,
            hours=hours,
            project_id=project_id,
            task_id=task_id,
            so_line_id=so_line_id,
            write_billing=write_billing,
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
            total = Decimal(0)
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
    vals: dict[str, object] = {
        "date": row.entry_date.isoformat(),
        "employee_id": row.employee_id,
        "project_id": row.project_id,
        "unit_amount": float(row.hours) if row.hours is not None else None,
        "name": row.note or " ",
        "so_line": row.so_line_id if row.so_line_id is not None else False,
        app_entry_id_field: str(row.id),
    }
    # Only when there is one: a pre-2b row has no task, and a task-less line
    # must be created exactly as it always was.
    if row.task_id is not None:
        vals["task_id"] = row.task_id
    return vals


def _update_vals(row: OutboxRow) -> dict[str, object]:
    vals: dict[str, object] = {
        "date": row.entry_date.isoformat(),
        "unit_amount": float(row.hours) if row.hours is not None else None,
        "name": row.note or " ",
    }
    # Billing is written only when the entry service said to: never over an
    # approver's override, and never when project and task did not change
    # (Odoo leaves so_line alone on hours and note edits, decision 0013).
    if row.write_billing:
        vals["project_id"] = row.project_id
        vals["so_line"] = row.so_line_id if row.so_line_id is not None else False
        if row.task_id is not None:
            vals["task_id"] = row.task_id
    return vals


async def _mark_pending_retry(session: AsyncSession, row: OutboxRow, exc: Exception) -> None:
    row.attempts += 1
    row.last_error = str(exc)
    row.next_attempt = datetime.now(UTC) + timedelta(seconds=backoff_seconds(row.attempts))
    row.updated_at = datetime.now(UTC)
    await session.commit()


async def _mark_failed(session: AsyncSession, row: OutboxRow, periods: PeriodService, exc: Exception) -> None:
    row.attempts += 1
    row.state = OutboxState.FAILED.value
    row.last_error = str(exc)
    row.updated_at = datetime.now(UTC)
    await session.commit()
    # Odoo itself rejecting a write is a signal our cached validated-through
    # date might be stale — invalidate eagerly rather than waiting out the TTL.
    periods.invalidate(row.employee_id)


async def _mark_synced(session: AsyncSession, row: OutboxRow, odoo_line_id: int) -> None:
    row.attempts += 1
    row.state = OutboxState.SYNCED.value
    row.odoo_line_id = odoo_line_id
    row.updated_at = datetime.now(UTC)
    await session.commit()


async def _period_open_for_write(
    session: AsyncSession,
    row: OutboxRow,
    odoo: OdooClient,
    periods: PeriodService,
    *,
    existing_line_id: int | None = None,
) -> bool:
    """The lock check at the moment of writing, not just at save time.

    Odoo accepts writes into a validated month (the profile's
    `validated_line_writable`), so the app is the only guard — and a row queued
    while the month was open can be drained after an approver locks it. Reads
    the validated-through date fresh, bypassing the 5-minute cache: this runs
    once per write attempt, not per request.

    Returns True if the write may go ahead. Otherwise the row has already been
    resolved here (failed if locked, back to pending if Odoo couldn't answer)
    and the caller must return without writing.
    """
    periods.invalidate(row.employee_id)
    try:
        dates = [row.entry_date]
        if existing_line_id is not None:
            # An edit touches the line's current date as well as its new one.
            [line] = await odoo.execute_kw("account.analytic.line", "read", [[existing_line_id]], {"fields": ["date"]})
            dates.append(date.fromisoformat(line["date"]))
        for d in dates:
            await periods.guard(row.employee_id, d, allow_last_known=False)
    except PeriodLocked as exc:
        await _mark_failed(session, row, periods, RuntimeError(PERIOD_LOCKED_PREFIX + str(exc)))
        logger.warning("outbox write refused: month locked", extra={"outbox_id": str(row.id), "op": row.op})
        return False
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
        return False
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
        return False
    return True


async def _reconcile_search(
    session: AsyncSession, row: OutboxRow, odoo: OdooClient, periods: PeriodService, domain: list
) -> list[dict] | None:
    """The look-before-you-act search that precedes a retry. Handled like the
    writes it guards — an unreachable Odoo backs the row off, a rejection
    fails it — so nothing escapes to the worker loop, where it would roll the
    transaction back, skip the backoff and, if rejected every time, block the
    queue behind this row (docs/decisions/0010, gap 3).

    Returns the matching records, or None if the row has already been resolved
    here and the caller must return without acting."""
    try:
        return await odoo.execute_kw("account.analytic.line", "search_read", [domain], {"fields": ["id"]})
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
    return None


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
        existing = await _reconcile_search(
            session, row, odoo, periods, [(profile.app_entry_id_field, "=", str(row.id))]
        )
        if existing is None:
            return
        if existing:
            await _mark_synced(session, row, existing[0]["id"])
            logger.info("outbox create reconciled to existing Odoo line", extra={"outbox_id": str(row.id)})
            return

    if not await _period_open_for_write(session, row, odoo, periods):
        return

    try:
        line_id = await odoo.execute_kw(
            "account.analytic.line", "create", [_create_vals(row, profile.app_entry_id_field)]
        )
    except (OdooUnavailable, OdooUncertain) as exc:
        await _mark_pending_retry(session, row, exc)
        return
    except OdooRejected as exc:
        await _mark_failed(session, row, periods, exc)
        return
    await _mark_synced(session, row, line_id)


async def _attempt_update(session: AsyncSession, row: OutboxRow, odoo: OdooClient, periods: PeriodService) -> None:
    assert row.odoo_line_id is not None
    if not await _period_open_for_write(session, row, odoo, periods, existing_line_id=row.odoo_line_id):
        return
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
        existing = await _reconcile_search(session, row, odoo, periods, [("id", "=", row.odoo_line_id)])
        if existing is None:
            return
        if not existing:
            # Already gone — a prior attempt's outcome was uncertain but it
            # actually succeeded. Unlinking again would raise MissingError
            # (OdooRejected), which would wrongly report an
            # already-successful delete as failed.
            await _mark_synced(session, row, row.odoo_line_id)
            logger.info("outbox delete reconciled: already gone", extra={"outbox_id": str(row.id)})
            return

    if not await _period_open_for_write(session, row, odoo, periods):
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
