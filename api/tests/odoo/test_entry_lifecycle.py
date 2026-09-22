"""Step 2.4's own test list: edit changes the Odoo line rather than
creating a new one; delete removes it; editing another employee's line
returns 403 even though the integration user has the rights to do it;
the cap counts pending rows; a locked period refuses all three
operations; the month view matches Odoo exactly once the queue is
empty."""

from __future__ import annotations

import datetime
import socket
from decimal import Decimal

import pytest
from sqlalchemy import delete

from tti.entries.errors import EntryNotOwned
from tti.domain.errors import DailyCapExceeded
from tti.odoo.client import OdooClient
from tti.outbox.models import OutboxRow
from tti.outbox.service import OutboxService
from tti.periods.errors import PeriodLocked

pytestmark = pytest.mark.odoo

TM_EMPLOYEE_ID = 1  # Sergii — mapped to project 2 (S00001), sale line 1
OTHER_EMPLOYEE_ID = 2  # Polina
TODAY = datetime.date.today()


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _cleanup_entry(odoo_client, session_factory, entry):
    if entry.id is not None:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [[entry.id]])
    if entry.outbox_id is not None:
        async with session_factory() as session:
            await session.execute(delete(OutboxRow).where(OutboxRow.id == entry.outbox_id))
            await session.commit()


async def test_edit_changes_the_line_not_creates_a_new_one(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="internal", date=TODAY.isoformat(), hours=1.0, note="before edit"
    )
    try:
        before_count = len(
            await odoo_client.execute_kw(
                "account.analytic.line",
                "search_read",
                [[("employee_id", "=", TM_EMPLOYEE_ID), ("date", "=", TODAY.isoformat())]],
                {"fields": ["id"]},
            )
        )

        edited = await entry_service.update_entry(
            employee_id=TM_EMPLOYEE_ID,
            odoo_line_id=entry.id,
            assignment_id="internal",
            date=TODAY.isoformat(),
            hours=2.5,
            note="after edit",
        )
        assert edited.id == entry.id  # same line, not a new one
        assert edited.hours == 2.5
        assert edited.note == "after edit"

        after_count = len(
            await odoo_client.execute_kw(
                "account.analytic.line",
                "search_read",
                [[("employee_id", "=", TM_EMPLOYEE_ID), ("date", "=", TODAY.isoformat())]],
                {"fields": ["id"]},
            )
        )
        assert after_count == before_count
    finally:
        await _cleanup_entry(odoo_client, session_factory, entry)


async def test_delete_removes_it(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="internal", date=TODAY.isoformat(), hours=1.0, note="to delete"
    )
    sync_state = await entry_service.delete_entry(employee_id=TM_EMPLOYEE_ID, odoo_line_id=entry.id)
    assert sync_state == "synced"

    remaining = await odoo_client.execute_kw(
        "account.analytic.line", "search_read", [[("id", "=", entry.id)]], {"fields": ["id"]}
    )
    assert remaining == []

    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.employee_id == TM_EMPLOYEE_ID, OutboxRow.odoo_line_id == entry.id))
        await session.commit()


async def test_editing_another_employees_line_is_refused(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="internal", date=TODAY.isoformat(), hours=1.0, note="owned by TM"
    )
    try:
        with pytest.raises(EntryNotOwned):
            await entry_service.update_entry(
                employee_id=OTHER_EMPLOYEE_ID,
                odoo_line_id=entry.id,
                assignment_id="internal",
                date=TODAY.isoformat(),
                hours=3.0,
                note="hijacked",
            )
        with pytest.raises(EntryNotOwned):
            await entry_service.delete_entry(employee_id=OTHER_EMPLOYEE_ID, odoo_line_id=entry.id)

        # Untouched — the integration user could have done either, the app refused anyway.
        [record] = await odoo_client.execute_kw(
            "account.analytic.line", "read", [[entry.id]], {"fields": ["unit_amount", "name"]}
        )
        assert record["unit_amount"] == 1.0
        assert record["name"] == "owned by TM"
    finally:
        await _cleanup_entry(odoo_client, session_factory, entry)


async def test_daily_cap_counts_pending_rows(odoo_client, entry_service, period_service, profile, session_factory):
    port = _unused_port()
    unreachable_client = OdooClient(url=f"http://127.0.0.1:{port}", db="x", user="x", api_key="x", timeout=3.0)
    try:
        outbox_on_broken_client = OutboxService(session_factory, unreachable_client, profile, period_service)
        pending_result = await outbox_on_broken_client.enqueue_create(
            employee_id=TM_EMPLOYEE_ID,
            entry_date=TODAY,
            hours=Decimal("9.0"),
            assignment_id="internal",
            project_id=1,
            so_line_id=None,
            note="cap test: pending 9h",
        )
        assert pending_result.state.value == "pending"

        try:
            with pytest.raises(DailyCapExceeded):
                await entry_service.create_entry(
                    employee_id=TM_EMPLOYEE_ID,
                    assignment_id="internal",
                    date=TODAY.isoformat(),
                    hours=2.0,
                    note="cap test: should be refused",
                )
        finally:
            async with session_factory() as session:
                await session.execute(delete(OutboxRow).where(OutboxRow.id == pending_result.outbox_id))
                await session.commit()
    finally:
        await unreachable_client.aclose()


@pytest.fixture
async def validated_through_prev_month(odoo_client):
    [before] = await odoo_client.execute_kw(
        "hr.employee", "read", [[TM_EMPLOYEE_ID]], {"fields": ["last_validated_timesheet_date"]}
    )
    original = before["last_validated_timesheet_date"] or False
    first_of_this_month = TODAY.replace(day=1)
    last_of_prev_month = first_of_this_month - datetime.timedelta(days=1)
    await odoo_client.execute_kw(
        "hr.employee", "write", [[TM_EMPLOYEE_ID], {"last_validated_timesheet_date": last_of_prev_month.isoformat()}]
    )
    try:
        yield last_of_prev_month
    finally:
        await odoo_client.execute_kw(
            "hr.employee", "write", [[TM_EMPLOYEE_ID], {"last_validated_timesheet_date": original}]
        )


async def test_locked_period_refuses_all_three_operations(
    odoo_client, entry_service, validated_through_prev_month
):
    locked_date = validated_through_prev_month

    with pytest.raises(PeriodLocked):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID,
            assignment_id="internal",
            date=locked_date.isoformat(),
            hours=1.0,
            note="should be locked",
        )

    # A line that already existed in the locked month, created directly
    # (bypassing our own guards) — the realistic scenario is "created
    # before the period was locked."
    line_id = await odoo_client.execute_kw(
        "account.analytic.line",
        "create",
        [{"employee_id": TM_EMPLOYEE_ID, "project_id": 1, "date": locked_date.isoformat(), "unit_amount": 1.0, "name": "pre-existing, now locked"}],
    )
    try:
        with pytest.raises(PeriodLocked):
            await entry_service.update_entry(
                employee_id=TM_EMPLOYEE_ID,
                odoo_line_id=line_id,
                assignment_id="internal",
                date=locked_date.isoformat(),
                hours=2.0,
                note="edit should be locked",
            )
        with pytest.raises(PeriodLocked):
            await entry_service.delete_entry(employee_id=TM_EMPLOYEE_ID, odoo_line_id=line_id)

        # Untouched.
        [record] = await odoo_client.execute_kw(
            "account.analytic.line", "read", [[line_id]], {"fields": ["unit_amount"]}
        )
        assert record["unit_amount"] == 1.0
    finally:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [[line_id]])


async def test_month_view_matches_odoo_exactly_once_queue_is_empty(odoo_client, entry_service, session_factory):
    entries = []
    for i, hours in enumerate([1.0, 1.5]):
        entry = await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID,
            assignment_id="internal",
            date=TODAY.isoformat(),
            hours=hours,
            note=f"month view test {i}",
        )
        assert entry.sync_state == "synced"  # queue empty for these by construction
        entries.append(entry)

    try:
        app_view = await entry_service.list_for_employee_month(TM_EMPLOYEE_ID, TODAY.year, TODAY.month)
        odoo_view = await odoo_client.execute_kw(
            "account.analytic.line",
            "search_read",
            [
                [
                    ("employee_id", "=", TM_EMPLOYEE_ID),
                    ("date", ">=", TODAY.replace(day=1).isoformat()),
                    ("date", "<=", TODAY.isoformat()),
                ]
            ],
            {"fields": ["id", "unit_amount", "name"]},
        )

        app_by_id = {e.id: e for e in app_view if e.id is not None}
        odoo_by_id = {r["id"]: r for r in odoo_view}

        assert set(app_by_id) == set(odoo_by_id)
        for line_id, odoo_record in odoo_by_id.items():
            assert app_by_id[line_id].hours == odoo_record["unit_amount"]
            assert app_by_id[line_id].note == odoo_record["name"]
            assert app_by_id[line_id].sync_state == "synced"
    finally:
        for entry in entries:
            await _cleanup_entry(odoo_client, session_factory, entry)
