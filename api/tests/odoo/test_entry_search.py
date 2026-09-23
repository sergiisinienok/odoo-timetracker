"""Step 2.6's own test list for EntryService.search: month filter,
assignment filter, note search, and pagination each return the right
set, independent of each other."""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import delete

from tti.outbox.models import OutboxRow

pytestmark = pytest.mark.odoo

# Live trial data as of step 1.4/1.5: employee 1 (Sergii) is mapped to
# project 2 (S00001), sale line 1.
TM_EMPLOYEE_ID = 1
_TODAY = datetime.date.today()


def _months_ago(n: int) -> datetime.date:
    year, month = _TODAY.year, _TODAY.month
    for _ in range(n):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return datetime.date(year, month, 5)


async def _create(entry_service, *, assignment_id: str, date: datetime.date, note: str):
    return await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, assignment_id=assignment_id, date=date.isoformat(), hours=1.0, note=note
    )


async def _cleanup_all(odoo_client, session_factory, entries):
    ids = [e.id for e in entries if e.id is not None]
    if ids:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [ids])
    outbox_ids = [e.outbox_id for e in entries if e.outbox_id is not None]
    if outbox_ids:
        async with session_factory() as session:
            await session.execute(delete(OutboxRow).where(OutboxRow.id.in_(outbox_ids)))
            await session.commit()


@pytest.fixture
async def three_months_of_entries(entry_service, odoo_client, session_factory):
    marker = uuid.uuid4().hex[:8]
    month_a, month_b, month_c = _months_ago(2), _months_ago(1), _months_ago(0)

    alpha = await _create(entry_service, assignment_id="internal", date=month_a, note=f"{marker} alpha entry")
    bravo = await _create(entry_service, assignment_id="internal", date=month_b, note=f"{marker} bravo entry")
    gamma_internal = await _create(entry_service, assignment_id="internal", date=month_c, note=f"{marker} gamma one")
    gamma_paid = await _create(entry_service, assignment_id="project:2:paid", date=month_c, note=f"{marker} gamma two")

    entries = [alpha, bravo, gamma_internal, gamma_paid]
    try:
        yield {
            "marker": marker,
            "month_a": month_a,
            "month_b": month_b,
            "month_c": month_c,
            "alpha": alpha,
            "bravo": bravo,
            "gamma_internal": gamma_internal,
            "gamma_paid": gamma_paid,
        }
    finally:
        await _cleanup_all(odoo_client, session_factory, entries)


async def test_month_filter_returns_only_that_month(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=f"{data['month_a'].year:04d}-{data['month_a'].month:02d}",
        assignment_id=None,
        q=data["marker"],
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["alpha"].id]


async def test_assignment_filter_returns_only_that_assignment(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=None,
        assignment_id="project:2:paid",
        q=data["marker"],
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["gamma_paid"].id]


async def test_note_search_matches_substring(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=None,
        assignment_id=None,
        q=f"{data['marker']} bravo",
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["bravo"].id]


async def test_pagination_limit_and_offset_walk_the_full_set(entry_service, three_months_of_entries):
    data = three_months_of_entries
    page1, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, assignment_id=None, q=data["marker"], limit=2, offset=0
    )
    assert total == 4
    assert len(page1) == 2

    page2, total2 = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, assignment_id=None, q=data["marker"], limit=2, offset=2
    )
    assert total2 == 4
    assert len(page2) == 2

    all_ids = {i.id for i in page1} | {i.id for i in page2}
    expected_ids = {data["alpha"].id, data["bravo"].id, data["gamma_internal"].id, data["gamma_paid"].id}
    assert all_ids == expected_ids


async def test_no_filters_still_finds_seeded_entries_among_the_rest(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, assignment_id=None, q=None, limit=200, offset=0
    )
    assert total >= 4
    found_ids = {i.id for i in items}
    seeded_ids = {data["alpha"].id, data["bravo"].id, data["gamma_internal"].id, data["gamma_paid"].id}
    assert seeded_ids.issubset(found_ids)
