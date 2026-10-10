import datetime

import pytest
from sqlalchemy import delete

from tti.domain.errors import InvalidIncrement
from tti.entries.errors import ProjectNotHeld, TaskRequired
from tti.outbox.models import OutboxRow

pytestmark = pytest.mark.odoo

# Live trial data: employee 1 (Sergii) is mapped to project 2 (S00001, billable,
# order line 1). Tasks are created per test (make_task) so nothing here depends
# on what ops happened to name theirs.
TM_EMPLOYEE_ID = 1
TODAY = datetime.date.today().isoformat()


async def _cleanup(odoo_client, session_factory, entry):
    await odoo_client.execute_kw("account.analytic.line", "unlink", [[entry.id]])
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id == entry.outbox_id))
        await session.commit()


async def _line(odoo_client, entry):
    [record] = await odoo_client.execute_kw(
        "account.analytic.line", "read", [[entry.id]], {"fields": ["so_line", "task_id", "project_id"]}
    )
    return record


async def test_billable_entry_lands_with_the_employees_order_line_and_the_task(
    odoo_client, entry_service, session_factory, make_task
):
    task_id = await make_task(2, "billable", "same")
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, project_id=2, task_id=task_id, date=TODAY, hours=1.0, note="billable test"
    )
    try:
        record = await _line(odoo_client, entry)
        assert record["so_line"][0] == 1
        assert record["task_id"][0] == task_id
        assert record["project_id"][0] == 2
        assert (entry.project_id, entry.task_id) == (2, task_id)
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_unbillable_entry_stays_unbillable_after_a_subsequent_unrelated_write(
    odoo_client, entry_service, session_factory, make_task
):
    task_id = await make_task(2, "rework", "no")
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, project_id=2, task_id=task_id, date=TODAY, hours=1.0, note="unbillable test"
    )
    try:
        assert (await _line(odoo_client, entry))["so_line"] is False

        # An unrelated write — just the description — shouldn't resurrect
        # so_line via any auto-fill logic on the Odoo side (re-proven with a
        # task set, step 2b.3).
        await odoo_client.execute_kw("account.analytic.line", "write", [[entry.id], {"name": "edited"}])
        assert (await _line(odoo_client, entry))["so_line"] is False
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_internal_entry_lands_on_the_internal_project(
    entry_service, odoo_client, session_factory, internal_target
):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, **internal_target, date=TODAY, hours=1.0, note="internal test"
    )
    try:
        record = await _line(odoo_client, entry)
        assert record["project_id"][0] == internal_target["project_id"]
        assert record["so_line"] is False
        assert entry.project_label == "Internal"
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_project_not_held_is_refused(entry_service, make_task):
    with pytest.raises(ProjectNotHeld):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID,
            project_id=999999,
            task_id=await make_task(2, "x"),
            date=TODAY,
            hours=1.0,
            note="",
        )


async def test_a_task_is_required(entry_service):
    with pytest.raises(TaskRequired):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID, project_id=2, task_id=None, date=TODAY, hours=1.0, note=""
        )


async def test_invalid_increment_is_refused(entry_service, make_task):
    with pytest.raises(InvalidIncrement):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID, project_id=2, task_id=await make_task(2, "x"), date=TODAY, hours=3.3, note=""
        )


async def test_quarter_hour_increment_is_accepted(odoo_client, entry_service, session_factory, make_task):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, project_id=2, task_id=await make_task(2, "q"), date=TODAY, hours=3.25, note=""
    )
    try:
        assert entry.hours == 3.25
    finally:
        await _cleanup(odoo_client, session_factory, entry)
