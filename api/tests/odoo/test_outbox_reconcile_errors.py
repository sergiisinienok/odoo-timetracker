"""Docs/decisions/0010, gap 3: the reconcile search that precedes a retry
(any row with attempts > 0) must go through the same unavailable/uncertain/
rejected handling as the writes below it. Uses a stub Odoo, so this needs
Postgres but no live sandbox."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete

from tti.odoo.errors import OdooRejected, OdooUnavailable, OdooUncertain
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState
from tti.outbox.worker import process_one_pending_row

pytestmark = pytest.mark.odoo

EMP = 1


class FailingOdoo:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        raise self.exc


async def _seed_retry_row(session_factory, op: str) -> uuid.UUID:
    """A row that has already been attempted once and is due again."""
    row = OutboxRow(
        id=uuid.uuid4(),
        employee_id=EMP,
        op=op,
        entry_date=datetime.date.today(),
        hours=Decimal("1.0") if op == OutboxOp.CREATE.value else None,
        project_id=1 if op == OutboxOp.CREATE.value else None,
        note="gap 3 reconcile test",
        odoo_line_id=None if op == OutboxOp.CREATE.value else 999999,
        state=OutboxState.PENDING.value,
        attempts=1,
        next_attempt=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1),
    )
    async with session_factory() as s:
        s.add(row)
        await s.commit()
    return row.id


async def _drain_one(session_factory, odoo, profile, period_service):
    return await process_one_pending_row(session_factory, odoo, profile, period_service)


async def _row(session_factory, row_id) -> OutboxRow:
    async with session_factory() as s:
        return await s.get(OutboxRow, row_id)


async def _forget(session_factory, row_id):
    async with session_factory() as s:
        await s.execute(delete(OutboxRow).where(OutboxRow.id == row_id))
        await s.commit()


@pytest.mark.parametrize("op", [OutboxOp.CREATE.value, OutboxOp.DELETE.value])
@pytest.mark.parametrize("exc", [OdooUnavailable("down"), OdooUncertain("lost")])
async def test_retry_while_odoo_is_down_backs_off_instead_of_raising(session_factory, profile, period_service, op, exc):
    row_id = await _seed_retry_row(session_factory, op)
    try:
        before = await _row(session_factory, row_id)
        odoo = FailingOdoo(exc)
        assert await _drain_one(session_factory, odoo, profile, period_service) is True  # no exception escaped

        after = await _row(session_factory, row_id)
        assert after.state == OutboxState.PENDING.value
        assert after.attempts == before.attempts + 1
        assert after.next_attempt > datetime.datetime.now(datetime.UTC), "backoff must push the next attempt out"
        assert str(exc) in after.last_error
        assert odoo.calls == [("account.analytic.line", "search_read")], (
            "only the reconcile search, never a blind write"
        )
    finally:
        await _forget(session_factory, row_id)


@pytest.mark.parametrize("op", [OutboxOp.CREATE.value, OutboxOp.DELETE.value])
async def test_a_rejected_reconcile_search_fails_the_row_and_frees_the_queue(
    session_factory, profile, period_service, op
):
    row_id = await _seed_retry_row(session_factory, op)
    try:
        assert (
            await _drain_one(session_factory, FailingOdoo(OdooRejected("access denied")), profile, period_service)
            is True
        )
        row = await _row(session_factory, row_id)
        assert row.state == OutboxState.FAILED.value and "access denied" in row.last_error
        # Failed rows are never picked again: the next poll finds nothing due.
        assert await _drain_one(session_factory, FailingOdoo(OdooRejected("unused")), profile, period_service) is False
    finally:
        await _forget(session_factory, row_id)
