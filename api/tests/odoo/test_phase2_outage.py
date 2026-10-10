"""Phase 2 gate: outage test — input survives, queue drains, exactly one line
per entry. See docs/decisions/0010 (gap 2)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from switchable import SwitchableOdoo

from tti.assignments.service import AssignmentService
from tti.config import Settings
from tti.domain.errors import DailyCapExceeded
from tti.entries.service import EntryService
from tti.odoo.errors import OdooUnavailable
from tti.outbox.models import OutboxRow, OutboxState
from tti.outbox.service import OutboxService
from tti.outbox.worker import process_one_pending_row
from tti.periods.service import PeriodService

pytestmark = pytest.mark.odoo

EMP = 1
TODAY = datetime.date.today()


async def _forget_outbox(session_factory, ids):
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id.in_(ids)))
        await session.commit()


async def _lines_named(odoo, prefix):
    return await odoo.execute_kw("account.analytic.line", "search", [[("name", "like", prefix)]])


async def test_input_survives_an_outage_and_drains_to_exactly_one_line_each(odoo_client, session_factory, profile):
    """The employee has the app open (assignments and period cached), Odoo goes
    away, they save three entries; Odoo comes back. Nothing may be refused or
    lost, and the drain must leave exactly one Odoo line per entry."""
    settings = Settings.from_env()
    switch = SwitchableOdoo(odoo_client)
    assignments = AssignmentService(switch, profile, settings.internal_project_id)
    periods = PeriodService(switch, profile)
    outbox = OutboxService(session_factory, switch, profile, periods)
    service = EntryService(
        switch, profile, assignments, periods, outbox, settings.internal_project_id, settings.daily_hour_cap
    )
    # Warm, as after loading the page: the month view, the assignment picker
    # and the period state are what the UI reads before anyone saves.
    await service.list_for_employee_month(EMP, TODAY.year, TODAY.month)
    await assignments.list_for_employee(EMP)
    await periods.guard(EMP, TODAY)

    prefix = f"phase2-gate outage {datetime.datetime.now().timestamp():.0f}"
    switch.down = True
    entries = []
    try:
        for i, hours in enumerate([1.0, 1.5, 2.0]):
            entries.append(
                await service.create_entry(
                    employee_id=EMP, assignment_id="internal", date=TODAY.isoformat(), hours=hours, note=f"{prefix} {i}"
                )
            )
        assert [e.sync_state for e in entries] == ["pending"] * 3, "input must be accepted as pending, not refused"

        async with session_factory() as s:
            rows = (
                (await s.execute(select(OutboxRow).where(OutboxRow.id.in_([e.outbox_id for e in entries]))))
                .scalars()
                .all()
            )
        assert len(rows) == 3 and all(r.state == OutboxState.PENDING.value for r in rows)
        assert await _lines_named(odoo_client, prefix) == []

        switch.down = False  # Odoo returns
        for e in entries:
            async with session_factory() as s:
                row = await s.get(OutboxRow, e.outbox_id)
                row.next_attempt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
                await s.commit()
        while await process_one_pending_row(session_factory, odoo_client, profile, periods):
            pass

        for i in range(3):
            assert len(await _lines_named(odoo_client, f"{prefix} {i}")) == 1, f"entry {i}: not exactly one line"
        async with session_factory() as s:
            states = [(await s.get(OutboxRow, e.outbox_id)).state for e in entries]
        assert states == [OutboxState.SYNCED.value] * 3
    finally:
        for lid in await _lines_named(odoo_client, prefix):
            await odoo_client.execute_kw("account.analytic.line", "unlink", [[lid]])
        await _forget_outbox(session_factory, [e.outbox_id for e in entries if e.outbox_id])


def _stack(odoo_client, session_factory, profile):
    settings = Settings.from_env()
    switch = SwitchableOdoo(odoo_client)
    assignments = AssignmentService(switch, profile, settings.internal_project_id)
    periods = PeriodService(switch, profile)
    outbox = OutboxService(session_factory, switch, profile, periods)
    service = EntryService(
        switch, profile, assignments, periods, outbox, settings.internal_project_id, settings.daily_hour_cap
    )
    return switch, service, settings


async def test_the_daily_cap_still_holds_during_an_outage(odoo_client, session_factory, profile):
    """The page was loaded (month view warms the last-known day), Odoo goes away,
    and queued hours count toward the cap — an outage must not become a way
    round it."""
    switch, service, settings = _stack(odoo_client, session_factory, profile)
    await service.list_for_employee_month(EMP, TODAY.year, TODAY.month)  # the page load
    await service._assignments.list_for_employee(EMP)
    await service._periods.guard(EMP, TODAY)

    existing = await service._existing_hours(EMP, TODAY)
    first = settings.daily_hour_cap - existing - Decimal("1.0")
    if first <= 0:
        pytest.skip("employee 1 already has too many hours today for this test")
    prefix = "phase2-gate outage cap"
    switch.down = True
    entries = []
    try:
        entries.append(
            await service.create_entry(
                employee_id=EMP,
                assignment_id="internal",
                date=TODAY.isoformat(),
                hours=float(first),
                note=f"{prefix} a",
            )
        )
        assert entries[0].sync_state == "pending"
        with pytest.raises(DailyCapExceeded):  # 1h of room left, asking for 2
            await service.create_entry(
                employee_id=EMP, assignment_id="internal", date=TODAY.isoformat(), hours=2.0, note=f"{prefix} b"
            )
    finally:
        await _forget_outbox(session_factory, [e.outbox_id for e in entries if e.outbox_id])


async def test_with_nothing_cached_an_outage_refuses_and_says_so_plainly(odoo_client, session_factory, profile):
    """A cold cache (fresh process, or older than the ceiling) cannot check the
    limit. Refusing is right; the failure is a 503 the employee can read."""
    switch, service, _ = _stack(odoo_client, session_factory, profile)
    switch.down = True
    with pytest.raises(OdooUnavailable):
        await service.create_entry(
            employee_id=EMP, assignment_id="internal", date=TODAY.isoformat(), hours=1.0, note="phase2-gate cold"
        )
    assert await _lines_named(odoo_client, "phase2-gate cold") == []
