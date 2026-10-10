"""Phase 2 gate evidence — docs/implementation-plan.md "Phase 2 gate":

  - App-enforced period locking, demonstrated independently of Odoo's behaviour
  - (Outage test: see test_phase2_outage.py)
  - App view and Odoo line list reconcile exactly for a full month

Each test states the behaviour the gate item asks for; if the app does not
have it, the test fails and says so — none is written to pass by construction.
"""

from __future__ import annotations

import calendar
import datetime
from collections import defaultdict
from decimal import Decimal

import pytest
from sqlalchemy import delete
from switchable import SwitchableOdoo

from tti.config import Settings
from tti.outbox.models import OutboxRow, OutboxState
from tti.outbox.service import OutboxService
from tti.outbox.worker import process_one_pending_row
from tti.periods.errors import PeriodLocked
from tti.periods.service import PeriodService

pytestmark = pytest.mark.odoo

EMP = 1
TODAY = datetime.date.today()
FIRST_OF_THIS_MONTH = TODAY.replace(day=1)
LAST_OF_PREV_MONTH = FIRST_OF_THIS_MONTH - datetime.timedelta(days=1)


async def _forget_outbox(session_factory, ids):
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id.in_(ids)))
        await session.commit()


async def _forget_outbox_since(session_factory, started_at):
    """Update and delete each enqueue their own outbox row, which the created
    entries' outbox_ids don't cover — sweep everything this test added."""
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.employee_id == EMP, OutboxRow.created_at >= started_at))
        await session.commit()


async def _lines_named(odoo, prefix):
    return await odoo.execute_kw("account.analytic.line", "search", [[("name", "like", prefix)]])


async def _set_validated_through(odoo, value):
    await odoo.execute_kw("hr.employee", "write", [[EMP], {"last_validated_timesheet_date": value}])


@pytest.fixture
async def locked_prev_month(odoo_client):
    [before] = await odoo_client.execute_kw(
        "hr.employee", "read", [[EMP]], {"fields": ["last_validated_timesheet_date"]}
    )
    original = before["last_validated_timesheet_date"] or False
    try:
        yield
    finally:
        await _set_validated_through(odoo_client, original)


# --- 1. locking, independent of Odoo -------------------------------------------------


async def test_app_refuses_writes_that_odoo_itself_would_accept(
    odoo_client, entry_service, locked_prev_month, unbillable_target
):
    """Odoo does not enforce the lock (validated_line_writable is true in the
    profile). So the same three writes the app refuses must succeed when made
    straight to Odoo — otherwise the refusal could be Odoo's, not the app's."""
    prefix = "phase2-gate lock independence"
    locked_day = LAST_OF_PREV_MONTH.isoformat()
    await _set_validated_through(odoo_client, locked_day)
    made: list[int] = []
    try:
        line_id = await odoo_client.execute_kw(
            "account.analytic.line",
            "create",
            [{"employee_id": EMP, "project_id": 1, "date": locked_day, "unit_amount": 1.0, "name": f"{prefix} a"}],
        )
        made.append(line_id)
        before = len(await _lines_named(odoo_client, prefix))

        # The app refuses all three...
        with pytest.raises(PeriodLocked):
            await entry_service.create_entry(
                employee_id=EMP, **unbillable_target, date=locked_day, hours=1.0, note=f"{prefix} b"
            )
        with pytest.raises(PeriodLocked):
            await entry_service.update_entry(
                employee_id=EMP, odoo_line_id=line_id, **unbillable_target, date=locked_day, hours=2.0, note="x"
            )
        with pytest.raises(PeriodLocked):
            await entry_service.delete_entry(employee_id=EMP, odoo_line_id=line_id)
        assert len(await _lines_named(odoo_client, prefix)) == before  # nothing created, nothing removed
        [rec] = await odoo_client.execute_kw("account.analytic.line", "read", [[line_id]], {"fields": ["unit_amount"]})
        assert rec["unit_amount"] == 1.0

        # ...while Odoo, asked directly in the very same locked state, accepts each of them.
        second = await odoo_client.execute_kw(
            "account.analytic.line",
            "create",
            [{"employee_id": EMP, "project_id": 1, "date": locked_day, "unit_amount": 1.0, "name": f"{prefix} c"}],
        )
        made.append(second)
        await odoo_client.execute_kw("account.analytic.line", "write", [[line_id], {"unit_amount": 3.0}])
        [rec] = await odoo_client.execute_kw("account.analytic.line", "read", [[line_id]], {"fields": ["unit_amount"]})
        assert rec["unit_amount"] == 3.0
        await odoo_client.execute_kw("account.analytic.line", "unlink", [[second]])
        made.remove(second)
    finally:
        for lid in made:
            await odoo_client.execute_kw("account.analytic.line", "unlink", [[lid]])


async def test_queued_write_is_not_applied_once_its_month_is_locked(
    odoo_client, session_factory, profile, period_service, locked_prev_month
):
    """A row queued while the month was open must not drain into it after an
    approver locks it. Odoo will not stop that write; only the app can."""
    unreachable = SwitchableOdoo(odoo_client)
    unreachable.down = True
    outbox = OutboxService(session_factory, unreachable, profile, period_service)
    day = LAST_OF_PREV_MONTH
    queued = await outbox.enqueue_create(
        employee_id=EMP,
        entry_date=day,
        hours=Decimal("1.0"),
        project_id=1,
        task_id=None,
        so_line_id=None,
        note="phase2-gate queued then locked",
    )
    assert queued.state == OutboxState.PENDING
    try:
        await _set_validated_through(odoo_client, day.isoformat())  # approver locks the month
        period_service.invalidate(EMP)
        async with session_factory() as s:  # make the retry due now
            row = await s.get(OutboxRow, queued.outbox_id)
            row.next_attempt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
            await s.commit()

        await process_one_pending_row(session_factory, odoo_client, profile, period_service)

        lines = await _lines_named(odoo_client, "phase2-gate queued then locked")
        async with session_factory() as s:
            row = await s.get(OutboxRow, queued.outbox_id)
        assert lines == [], f"the worker wrote {lines} into a locked month (row state: {row.state})"
        assert row.state == OutboxState.FAILED.value
    finally:
        for lid in await _lines_named(odoo_client, "phase2-gate queued then locked"):
            await odoo_client.execute_kw("account.analytic.line", "unlink", [[lid]])
        await _forget_outbox(session_factory, [queued.outbox_id])


async def _queue_while_down(odoo_client, session_factory, profile, period_service, **kwargs):
    down = SwitchableOdoo(odoo_client)
    down.down = True
    outbox = OutboxService(session_factory, down, profile, period_service)
    return outbox, await outbox_call(outbox, **kwargs)


async def outbox_call(outbox, *, op, **kw):
    return await getattr(outbox, f"enqueue_{op}")(employee_id=EMP, **kw)


async def _make_due_and_drain(odoo_client, session_factory, profile, period_service, outbox_id):
    async with session_factory() as s:
        row = await s.get(OutboxRow, outbox_id)
        row.next_attempt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
        await s.commit()
    await process_one_pending_row(session_factory, odoo_client, profile, period_service)
    async with session_factory() as s:
        return await s.get(OutboxRow, outbox_id)


async def test_queued_update_and_delete_are_not_applied_once_their_month_is_locked(
    odoo_client, session_factory, profile, period_service, locked_prev_month
):
    day = LAST_OF_PREV_MONTH
    line = await odoo_client.execute_kw(
        "account.analytic.line",
        "create",
        [
            {
                "employee_id": EMP,
                "project_id": 1,
                "date": day.isoformat(),
                "unit_amount": 1.0,
                "name": "phase2-gate queued edit",
            }
        ],
    )
    ids = []
    try:
        _, upd = await _queue_while_down(
            odoo_client,
            session_factory,
            profile,
            period_service,
            op="update",
            odoo_line_id=line,
            entry_date=day,
            hours=Decimal("2.0"),
            project_id=1,
            task_id=None,
            so_line_id=None,
            write_billing=False,
            note="phase2-gate queued edit (edited)",
        )
        _, dele = await _queue_while_down(
            odoo_client, session_factory, profile, period_service, op="delete", odoo_line_id=line, entry_date=day
        )
        ids = [upd.outbox_id, dele.outbox_id]
        await _set_validated_through(odoo_client, day.isoformat())  # approver locks the month

        for outbox_id in ids:
            row = await _make_due_and_drain(odoo_client, session_factory, profile, period_service, outbox_id)
            assert row.state == OutboxState.FAILED.value and row.last_error.startswith("period_locked: "), (
                row.op,
                row.state,
            )

        [rec] = await odoo_client.execute_kw(
            "account.analytic.line", "read", [[line]], {"fields": ["unit_amount", "name"]}
        )
        assert rec["unit_amount"] == 1.0 and rec["name"] == "phase2-gate queued edit"  # neither change was applied
    finally:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [[line]])
        await _forget_outbox(session_factory, ids)


async def test_a_create_that_reached_odoo_before_the_lock_is_still_reconciled_not_failed(
    odoo_client, session_factory, profile, period_service, locked_prev_month
):
    """The uncertain-outcome case: the line was written, the response was lost,
    then the month locked. Reconcile must find it and mark the row synced —
    failing it would tell the employee their (real) entry did not happen."""
    day = LAST_OF_PREV_MONTH
    down = SwitchableOdoo(odoo_client)
    down.down = True
    outbox = OutboxService(session_factory, down, profile, period_service)
    queued = await outbox.enqueue_create(
        employee_id=EMP,
        entry_date=day,
        hours=Decimal("1.0"),
        project_id=1,
        task_id=None,
        so_line_id=None,
        note="phase2-gate reconciled before lock",
    )
    try:
        # It did reach Odoo: create the line the way the worker's create would (same app entry id).
        await odoo_client.execute_kw(
            "account.analytic.line",
            "create",
            [
                {
                    "employee_id": EMP,
                    "project_id": 1,
                    "date": day.isoformat(),
                    "unit_amount": 1.0,
                    "name": "phase2-gate reconciled before lock",
                    profile.app_entry_id_field: str(queued.outbox_id),
                }
            ],
        )
        await _set_validated_through(odoo_client, day.isoformat())

        row = await _make_due_and_drain(odoo_client, session_factory, profile, period_service, queued.outbox_id)
        assert row.state == OutboxState.SYNCED.value
        assert len(await _lines_named(odoo_client, "phase2-gate reconciled before lock")) == 1
    finally:
        for lid in await _lines_named(odoo_client, "phase2-gate reconciled before lock"):
            await odoo_client.execute_kw("account.analytic.line", "unlink", [[lid]])
        await _forget_outbox(session_factory, [queued.outbox_id])


async def test_lock_check_with_odoo_down_leaves_the_row_pending_not_failed(odoo_client, session_factory, profile):
    """If Odoo cannot answer the lock check, the row waits — it is neither
    written unchecked nor failed. (First attempt only: a *retry* while Odoo is
    still down trips a separate bug in the reconcile step, docs/decisions/0010
    gap 3.)"""
    down = SwitchableOdoo(odoo_client)
    periods = PeriodService(down, profile)
    outbox = OutboxService(session_factory, down, profile, periods)
    down.down = True
    queued = await outbox.enqueue_create(
        employee_id=EMP,
        entry_date=TODAY,
        hours=Decimal("1.0"),
        project_id=1,
        task_id=None,
        so_line_id=None,
        note="phase2-gate check while down",
    )
    try:
        assert queued.state == OutboxState.PENDING
        async with session_factory() as s:
            row = await s.get(OutboxRow, queued.outbox_id)
        assert row.state == OutboxState.PENDING.value and row.attempts == 1 and "simulated outage" in row.last_error
        assert await _lines_named(odoo_client, "phase2-gate check while down") == []
    finally:
        await _forget_outbox(session_factory, [queued.outbox_id])


# --- 3. full-month reconciliation ---------------------------------------------------


async def test_app_view_reconciles_with_odoo_for_a_full_month(
    odoo_client, entry_service, session_factory, unbillable_target, make_task
):
    year, month = LAST_OF_PREV_MONTH.year, LAST_OF_PREV_MONTH.month
    last_day = calendar.monthrange(year, month)[1]
    days = [
        datetime.date(year, month, d)
        for d in range(1, last_day + 1)
        if datetime.date(year, month, d).weekday() < 5 or d in (1, last_day)  # every working day + both month edges
    ]
    # Billable, flat-rate-style and internal targets, each with a real task.
    targets = [
        {"project_id": 2, "task_id": await make_task(2, "gate T&M", "same")},
        {"project_id": 28, "task_id": await make_task(28, "gate flat", "same")},
        unbillable_target,
    ]
    hours_cycle = [0.5, 1.0, 1.5, 2.0, 4.0]
    # The sandbox is shared: the month may already hold real entries, so fill
    # each day only as far as the daily cap allows. The reconciliation below
    # compares the whole month, existing lines included.
    existing_rows = await odoo_client.execute_kw(
        "account.analytic.line",
        "search_read",
        [
            [
                ("employee_id", "=", EMP),
                ("date", ">=", f"{year}-{month:02d}-01"),
                ("date", "<=", f"{year}-{month:02d}-{last_day:02d}"),
            ]
        ],
        {"fields": ["date", "unit_amount"]},
    )
    used: dict[str, float] = defaultdict(float)
    for r in existing_rows:
        used[r["date"]] += r["unit_amount"]
    cap = float(Settings.from_env().daily_hour_cap)
    started_at = datetime.datetime.now(datetime.UTC)
    created = []
    try:
        for i, day in enumerate(days):
            target = targets[i % len(targets)]
            room = cap - used[day.isoformat()]
            hours = min(hours_cycle[i % len(hours_cycle)], (room // 0.25) * 0.25)  # quarter-hour steps
            if hours < 0.5:
                continue  # a day that is already full
            created.append(
                await entry_service.create_entry(
                    employee_id=EMP,
                    **target,
                    date=day.isoformat(),
                    hours=hours,
                    note=f"phase2-gate reconcile {day.isoformat()}",
                )
            )
        assert len(created) >= len(days) // 2, "too few free days to make the reconciliation meaningful"
        assert all(e.sync_state == "synced" for e in created)

        # Exercise edit and delete too, not just create.
        for e in created[:3]:
            await entry_service.update_entry(
                employee_id=EMP,
                odoo_line_id=e.id,
                project_id=e.project_id,
                task_id=e.task_id,
                date=e.date,
                hours=min(1.25, e.hours),  # never up on a day that may already be nearly full
                note=e.note + " (edited)",
            )
        for e in created[3:5]:
            await entry_service.delete_entry(employee_id=EMP, odoo_line_id=e.id)

        app_view = await entry_service.list_for_employee_month(EMP, year, month)
        odoo_rows = await odoo_client.execute_kw(
            "account.analytic.line",
            "search_read",
            [
                [
                    ("employee_id", "=", EMP),
                    ("date", ">=", f"{year}-{month:02d}-01"),
                    ("date", "<=", f"{year}-{month:02d}-{last_day:02d}"),
                ]
            ],
            {"fields": ["date", "unit_amount", "name", "project_id", "task_id"]},
        )

        app_by_id = {e.id: e for e in app_view if e.id is not None}
        odoo_by_id = {r["id"]: r for r in odoo_rows}
        assert not [e for e in app_view if e.id is None], "no pending rows expected: queue is empty"
        assert set(app_by_id) == set(odoo_by_id), "app and Odoo list different lines"

        for line_id, r in odoo_by_id.items():
            e = app_by_id[line_id]
            assert (e.date, e.hours, e.note, e.project_id, e.task_id) == (
                r["date"],
                r["unit_amount"],
                r["name"],
                r["project_id"][0],
                r["task_id"][0] if r["task_id"] else None,
            ), line_id

        def per_day(items):
            totals = defaultdict(Decimal)
            for date, hours in items:
                totals[date] += Decimal(str(hours))
            return dict(totals)

        assert per_day((e.date, e.hours) for e in app_view) == per_day((r["date"], r["unit_amount"]) for r in odoo_rows)
        assert sum(Decimal(str(e.hours)) for e in app_view) == sum(Decimal(str(r["unit_amount"])) for r in odoo_rows)
        assert any(e.date == f"{year}-{month:02d}-{last_day:02d}" for e in app_view), (
            "last day of the month must appear"
        )
    finally:
        for lid in await _lines_named(odoo_client, "phase2-gate reconcile"):
            await odoo_client.execute_kw("account.analytic.line", "unlink", [[lid]])
        await _forget_outbox_since(session_factory, started_at)
