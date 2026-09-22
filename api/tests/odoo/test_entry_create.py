import datetime

import pytest
from sqlalchemy import delete

from tti.domain.errors import InvalidIncrement
from tti.entries.errors import AssignmentNotHeld
from tti.outbox.models import OutboxRow

pytestmark = pytest.mark.odoo

# Live trial data as of step 1.4/1.5: employee 1 (Sergii) is mapped to
# project 2 (S00001), sale line 1.
TM_EMPLOYEE_ID = 1
TODAY = datetime.date.today().isoformat()


async def _cleanup(odoo_client, session_factory, entry):
    await odoo_client.execute_kw("account.analytic.line", "unlink", [[entry.id]])
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id == entry.outbox_id))
        await session.commit()


async def test_paid_entry_lands_with_correct_so_line(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="project:2:paid", date=TODAY, hours=1.0, note="paid test"
    )
    try:
        assert entry.so_line_id == 1
        assert entry.project_id == 2
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_unpaid_entry_stays_unpaid_after_a_subsequent_unrelated_write(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="project:2:unpaid", date=TODAY, hours=1.0, note="unpaid test"
    )
    try:
        assert entry.so_line_id is None

        # An unrelated write — just the description — shouldn't resurrect
        # so_line via any auto-fill logic on the Odoo side.
        await odoo_client.execute_kw("account.analytic.line", "write", [[entry.id], {"name": "unpaid test, edited"}])
        [record] = await odoo_client.execute_kw(
            "account.analytic.line", "read", [[entry.id]], {"fields": ["so_line"]}
        )
        assert record["so_line"] is False
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_internal_entry_lands_on_the_internal_project(entry_service, odoo_client, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="internal", date=TODAY, hours=1.0, note="internal test"
    )
    try:
        assert entry.project_id == 1  # INTERNAL_PROJECT_ID
        assert entry.so_line_id is None
    finally:
        await _cleanup(odoo_client, session_factory, entry)


async def test_assignment_not_held_is_refused(entry_service):
    with pytest.raises(AssignmentNotHeld):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID, assignment_id="project:9999:paid", date=TODAY, hours=1.0, note=""
        )


async def test_invalid_increment_is_refused(entry_service):
    with pytest.raises(InvalidIncrement):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID, assignment_id="project:2:paid", date=TODAY, hours=3.3, note=""
        )


async def test_quarter_hour_increment_is_accepted(odoo_client, entry_service, session_factory):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id="project:2:paid", date=TODAY, hours=3.25, note=""
    )
    try:
        assert entry.hours == 3.25
    finally:
        await _cleanup(odoo_client, session_factory, entry)
