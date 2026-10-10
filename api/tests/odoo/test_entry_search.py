"""Step 2.6's own test list for EntryService.search: month filter,
project and task filters, note search, and pagination each return the
right set, independent of each other."""

from __future__ import annotations

import calendar
import datetime
import uuid

import pytest
from sqlalchemy import delete

from tti.config import Settings
from tti.outbox.models import OutboxRow

pytestmark = pytest.mark.odoo

# Live trial data as of step 1.4/1.5: employee 1 (Sergii) is mapped to
# project 2 (S00001), sale line 1.
TM_EMPLOYEE_ID = 1
_TODAY = datetime.date.today()


def _month_start(n_months_ago: int) -> tuple[int, int]:
    year, month = _TODAY.year, _TODAY.month
    for _ in range(n_months_ago):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return year, month


async def _day_with_room(odoo_client, n_months_ago: int, needed_hours: float = 2.0) -> datetime.date:
    """A day in that month where employee 1 has room under the daily cap. The
    sandbox is shared, so a fixed day (the old "5th") can already be full."""
    year, month = _month_start(n_months_ago)
    last = calendar.monthrange(year, month)[1]
    rows = await odoo_client.execute_kw(
        "account.analytic.line",
        "search_read",
        [
            [
                ("employee_id", "=", TM_EMPLOYEE_ID),
                ("date", ">=", f"{year}-{month:02d}-01"),
                ("date", "<=", f"{year}-{month:02d}-{last:02d}"),
            ]
        ],
        {"fields": ["date", "unit_amount"]},
    )
    used: dict[str, float] = {}
    for r in rows:
        used[r["date"]] = used.get(r["date"], 0.0) + r["unit_amount"]
    cap = float(Settings.from_env().daily_hour_cap)
    for day in range(min(last, _TODAY.day if (year, month) == (_TODAY.year, _TODAY.month) else last), 0, -1):
        d = datetime.date(year, month, day)
        if d.weekday() < 5 and used.get(d.isoformat(), 0.0) + needed_hours <= cap:
            return d
    raise RuntimeError(f"no day with {needed_hours}h of room in {year}-{month:02d}")


async def _create(entry_service, *, target: dict, date: datetime.date, note: str):
    return await entry_service.create_entry(
        employee_id=TM_EMPLOYEE_ID, **target, date=date.isoformat(), hours=1.0, note=note
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
async def three_months_of_entries(entry_service, odoo_client, session_factory, internal_target, make_task):
    paid_target = {"project_id": 2, "task_id": await make_task(2, "search paid", "same")}
    marker = uuid.uuid4().hex[:8]
    month_a = await _day_with_room(odoo_client, 2)
    month_b = await _day_with_room(odoo_client, 1)
    month_c = await _day_with_room(odoo_client, 0)

    # Created inside the try, so a failure halfway still removes what was made.
    entries = []
    try:
        for target, day, note in (
            (internal_target, month_a, "alpha entry"),
            (internal_target, month_b, "bravo entry"),
            (internal_target, month_c, "gamma one"),
            (paid_target, month_c, "gamma two"),
        ):
            entries.append(await _create(entry_service, target=target, date=day, note=f"{marker} {note}"))
        alpha, bravo, gamma_internal, gamma_paid = entries
        yield {
            "marker": marker,
            "month_a": month_a,
            "month_b": month_b,
            "month_c": month_c,
            "alpha": alpha,
            "bravo": bravo,
            "gamma_internal": gamma_internal,
            "gamma_paid": gamma_paid,
            "paid_target": paid_target,
            "internal_target": internal_target,
        }
    finally:
        await _cleanup_all(odoo_client, session_factory, entries)


async def test_month_filter_returns_only_that_month(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=f"{data['month_a'].year:04d}-{data['month_a'].month:02d}",
        project_id=None,
        task_id=None,
        q=data["marker"],
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["alpha"].id]


async def test_project_filter_returns_only_that_project(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=None,
        project_id=data["paid_target"]["project_id"],
        task_id=None,
        q=data["marker"],
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["gamma_paid"].id]


async def test_task_filter_returns_only_that_task(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=None,
        project_id=None,
        task_id=data["internal_target"]["task_id"],
        q=data["marker"],
        limit=50,
        offset=0,
    )
    assert total == 3
    assert {i.id for i in items} == {data[k].id for k in ("alpha", "bravo", "gamma_internal")}
    assert all(i.task_id == data["internal_target"]["task_id"] for i in items)


async def test_note_search_matches_substring(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID,
        month=None,
        project_id=None,
        task_id=None,
        q=f"{data['marker']} bravo",
        limit=50,
        offset=0,
    )
    assert total == 1
    assert [i.id for i in items] == [data["bravo"].id]


async def test_pagination_limit_and_offset_walk_the_full_set(entry_service, three_months_of_entries):
    data = three_months_of_entries
    page1, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, project_id=None, task_id=None, q=data["marker"], limit=2, offset=0
    )
    assert total == 4
    assert len(page1) == 2

    page2, total2 = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, project_id=None, task_id=None, q=data["marker"], limit=2, offset=2
    )
    assert total2 == 4
    assert len(page2) == 2

    all_ids = {i.id for i in page1} | {i.id for i in page2}
    expected_ids = {data["alpha"].id, data["bravo"].id, data["gamma_internal"].id, data["gamma_paid"].id}
    assert all_ids == expected_ids


async def test_no_filters_still_finds_seeded_entries_among_the_rest(entry_service, three_months_of_entries):
    data = three_months_of_entries
    items, total = await entry_service.search(
        employee_id=TM_EMPLOYEE_ID, month=None, project_id=None, task_id=None, q=None, limit=200, offset=0
    )
    assert total >= 4
    found_ids = {i.id for i in items}
    seeded_ids = {data["alpha"].id, data["bravo"].id, data["gamma_internal"].id, data["gamma_paid"].id}
    assert seeded_ids.issubset(found_ids)
