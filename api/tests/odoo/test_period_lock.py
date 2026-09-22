import datetime

import pytest
from sqlalchemy import delete

from tti.outbox.models import OutboxRow
from tti.periods.errors import PeriodLocked

pytestmark = pytest.mark.odoo

TM_EMPLOYEE_ID = 1

_TODAY = datetime.date.today()
_FIRST_OF_THIS_MONTH = _TODAY.replace(day=1)
_LAST_OF_PREV_MONTH = _FIRST_OF_THIS_MONTH - datetime.timedelta(days=1)


@pytest.fixture
async def validated_through_prev_month(odoo_client):
    """Validate employee 1 through the last day of the previous month —
    locks that month and everything before it, leaves this month open.
    Restores the original (unset) value afterward."""
    [before] = await odoo_client.execute_kw(
        "hr.employee", "read", [[TM_EMPLOYEE_ID]], {"fields": ["last_validated_timesheet_date"]}
    )
    original = before["last_validated_timesheet_date"] or False
    await odoo_client.execute_kw(
        "hr.employee",
        "write",
        [[TM_EMPLOYEE_ID], {"last_validated_timesheet_date": _LAST_OF_PREV_MONTH.isoformat()}],
    )
    try:
        yield _LAST_OF_PREV_MONTH
    finally:
        await odoo_client.execute_kw(
            "hr.employee", "write", [[TM_EMPLOYEE_ID], {"last_validated_timesheet_date": original}]
        )


async def test_create_in_a_validated_month_is_refused(entry_service, validated_through_prev_month):
    with pytest.raises(PeriodLocked):
        await entry_service.create_entry(
            employee_id=TM_EMPLOYEE_ID,
            assignment_id="internal",
            date=_LAST_OF_PREV_MONTH.isoformat(),
            hours=1.0,
            note="should be refused, period locked",
        )


async def test_create_in_the_following_month_still_works(
    odoo_client, entry_service, session_factory, validated_through_prev_month
):
    entry = await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID,
        assignment_id="internal",
        date=_TODAY.isoformat(),
        hours=1.0,
        note="following month, should still work",
    )
    try:
        assert entry.date == _TODAY.isoformat()
    finally:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [[entry.id]])
        async with session_factory() as session:
            await session.execute(delete(OutboxRow).where(OutboxRow.id == entry.outbox_id))
            await session.commit()


async def test_periods_listing_reflects_the_lock(period_service, validated_through_prev_month):
    months = await period_service.months_for(TM_EMPLOYEE_ID, _TODAY)
    by_month = {m.month: m.state.value for m in months}

    locked_key = f"{_LAST_OF_PREV_MONTH.year:04d}-{_LAST_OF_PREV_MONTH.month:02d}"
    open_key = f"{_TODAY.year:04d}-{_TODAY.month:02d}"

    assert by_month[locked_key] == "locked"
    assert by_month[open_key] == "open"
