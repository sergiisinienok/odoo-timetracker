"""Step 2b.7: entries carry a task, billing is derived, approver overrides are
never undone (decision 0011).

Truth-table rows (2b.5): 2 project values x 3 task values x mapped/unmapped.
Nine are reachable through the service, because a project is only *held* by an
employee through a mapping row: billable-mapped (project 2), unbillable-mapped
(project 32) and unbillable-unmapped (a throwaway project). The three
"billable project, employee unmapped" rows cannot occur for a held project;
the rule itself is asserted for them in tests/unit/test_billing_rule.py.
"""

import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from tti.audit.models import AuditLogRow
from tti.audit.service import BILLING_WARNING_ACTION
from tti.domain.billing import BILLABLE_WITHOUT_ORDER_LINE
from tti.entries.errors import (
    BillingSetByApprover,
    ProjectNotHeld,
    TaskNotInProject,
    TaskNotOpen,
    TaskRequired,
)
from tti.outbox.models import OutboxRow
from tti.routes.entries import _audit_billing_warning

pytestmark = pytest.mark.odoo

EMP = 1
TODAY = datetime.date.today().isoformat()
BILLABLE_PROJECT, BILLABLE_LINE = 2, 1  # S00001, employee 1's mapped order line
UNBILLABLE_MAPPED_PROJECT, UNBILLABLE_MAPPED_LINE = 32, 4  # Billable off, employee 1 mapped
UNMAPPED_UNBILLABLE = "unmapped unbillable"  # sentinel: the unbillable_target fixture's project


@pytest.fixture
async def cleanup(odoo_client, session_factory, temp_records):
    """Everything an entry created or edited: its Odoo line and outbox rows.
    Depends on temp_records so it tears down first: a task cannot be deleted
    while a line still references it."""
    lines: list[int] = []
    yield lines
    if lines:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [lines])
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.employee_id == EMP, OutboxRow.note.like("2b7 %")))
        await session.commit()


async def _create(entry_service, cleanup, project_id, task_id, note="2b7 test", hours=1.0):
    entry = await entry_service.create_entry(
        employee_id=EMP, project_id=project_id, task_id=task_id, date=TODAY, hours=hours, note=f"{note}"
    )
    cleanup.append(entry.id)
    return entry


async def _read(odoo_client, line_id):
    [r] = await odoo_client.execute_kw(
        "account.analytic.line",
        "read",
        [[line_id]],
        {"fields": ["so_line", "task_id", "project_id", "is_so_line_edited"]},
    )
    return r


def _so_line(record):
    return record["so_line"][0] if record["so_line"] else None


# --- the truth table, one create per reachable row -----------------------------------

TRUTH_TABLE = [
    # (project, task override, expected so_line, expected warning)
    (BILLABLE_PROJECT, "same", BILLABLE_LINE, None),
    (BILLABLE_PROJECT, "yes", BILLABLE_LINE, None),
    (BILLABLE_PROJECT, "no", None, None),
    (UNBILLABLE_MAPPED_PROJECT, "same", None, None),
    (UNBILLABLE_MAPPED_PROJECT, "yes", UNBILLABLE_MAPPED_LINE, None),
    (UNBILLABLE_MAPPED_PROJECT, "no", None, None),
    (UNMAPPED_UNBILLABLE, "same", None, None),
    (UNMAPPED_UNBILLABLE, "yes", None, BILLABLE_WITHOUT_ORDER_LINE),
    (UNMAPPED_UNBILLABLE, "no", None, None),
]


@pytest.mark.parametrize("project_id,override,expected_so_line,expected_warning", TRUTH_TABLE)
async def test_every_reachable_truth_table_row_lands_right(
    odoo_client,
    entry_service,
    cleanup,
    make_task,
    unbillable_target,
    project_id,
    override,
    expected_so_line,
    expected_warning,
):
    if project_id == UNMAPPED_UNBILLABLE:
        project_id = unbillable_target["project_id"]
    task_id = await make_task(project_id, f"row {override}", override)
    entry = await _create(entry_service, cleanup, project_id, task_id)

    record = await _read(odoo_client, entry.id)
    assert _so_line(record) == expected_so_line
    assert entry.billing_warning == expected_warning
    assert record["task_id"][0] == task_id
    # Whatever was decided, an unbillable line is truly unbillable in Odoo.
    if expected_so_line is None:
        assert record["so_line"] is False


# --- unbillable lines stay unbillable; edits do not disturb billing ----------------------


async def test_an_unbillable_line_with_a_task_stays_unbillable_after_hours_and_note_edits(
    odoo_client, entry_service, cleanup, make_task
):
    task_id = await make_task(BILLABLE_PROJECT, "rework", "no")
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, task_id)

    await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=task_id,
        date=TODAY, hours=2.5, note="2b7 hours edit",
    )  # fmt: skip
    await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=task_id,
        date=TODAY, hours=2.5, note="2b7 note edit",
    )  # fmt: skip

    record = await _read(odoo_client, entry.id)
    assert record["so_line"] is False and record["is_so_line_edited"] is False


async def test_changing_the_task_re_resolves_billing_on_an_unmarked_line(
    odoo_client, entry_service, cleanup, make_task
):
    billable_task = await make_task(BILLABLE_PROJECT, "billable", "same")
    rework_task = await make_task(BILLABLE_PROJECT, "rework", "no")
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, billable_task)
    assert _so_line(await _read(odoo_client, entry.id)) == BILLABLE_LINE

    await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=rework_task,
        date=TODAY, hours=1.0, note="2b7 moved to rework",
    )  # fmt: skip
    record = await _read(odoo_client, entry.id)
    assert record["so_line"] is False and record["task_id"][0] == rework_task

    await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=billable_task,
        date=TODAY, hours=1.0, note="2b7 moved back",
    )  # fmt: skip
    assert _so_line(await _read(odoo_client, entry.id)) == BILLABLE_LINE


# --- approver overrides ------------------------------------------------------------------


async def _approver_sets(odoo_client, line_id, so_line):
    """What the Odoo UI does when an approver changes a line's Sales Order
    Item: the value and the manual-edit marker. (Plain RPC does not set the
    marker, so the test sets both — the UI behaviour is hand-verified, 0013.)"""
    await odoo_client.execute_kw(
        "account.analytic.line", "write", [[line_id], {"so_line": so_line or False, "is_so_line_edited": True}]
    )


@pytest.mark.parametrize("direction", ["set", "cleared"])
async def test_an_approver_override_survives_an_employee_edit_of_hours_and_note(
    odoo_client, entry_service, cleanup, make_task, direction
):
    if direction == "set":
        task_id = await make_task(BILLABLE_PROJECT, "rework", "no")  # unbillable by rule...
        override_to, expected = BILLABLE_LINE, BILLABLE_LINE  # ...the approver bills this one
    else:
        task_id = await make_task(BILLABLE_PROJECT, "billable", "same")  # billable by rule...
        override_to, expected = None, None  # ...the approver unbills this one
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, task_id)
    await _approver_sets(odoo_client, entry.id, override_to)

    await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=task_id,
        date=TODAY, hours=3.0, note="2b7 employee edit after override",
    )  # fmt: skip

    record = await _read(odoo_client, entry.id)
    assert _so_line(record) == expected
    assert record["is_so_line_edited"] is True


async def test_changing_the_task_of_an_overridden_line_is_refused(odoo_client, entry_service, cleanup, make_task):
    task_id = await make_task(BILLABLE_PROJECT, "a", "no")
    other_task = await make_task(BILLABLE_PROJECT, "b", "same")
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, task_id)
    await _approver_sets(odoo_client, entry.id, BILLABLE_LINE)

    with pytest.raises(BillingSetByApprover):
        await entry_service.update_entry(
            employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=other_task,
            date=TODAY, hours=1.0, note="2b7 moving",
        )  # fmt: skip
    with pytest.raises(BillingSetByApprover):  # project moves are refused the same way
        await entry_service.update_entry(
            employee_id=EMP, odoo_line_id=entry.id, project_id=UNBILLABLE_MAPPED_PROJECT,
            task_id=await make_task(UNBILLABLE_MAPPED_PROJECT, "c"), date=TODAY, hours=1.0, note="2b7 moving",
        )  # fmt: skip
    record = await _read(odoo_client, entry.id)
    assert record["task_id"][0] == task_id and _so_line(record) == BILLABLE_LINE


# --- legacy lines (no task) ------------------------------------------------------------


async def test_a_legacy_line_cannot_be_edited_without_a_task_but_can_be_deleted(
    odoo_client, entry_service, temp_records, make_task
):
    task_id = await make_task(BILLABLE_PROJECT, "adopt", "same")  # first: torn down after the line below
    line_id = await temp_records(
        "account.analytic.line",
        {"employee_id": EMP, "project_id": BILLABLE_PROJECT, "date": TODAY, "unit_amount": 1.0, "name": "2b7 legacy",
         "so_line": False},
    )  # fmt: skip
    with pytest.raises(TaskRequired):
        await entry_service.update_entry(
            employee_id=EMP, odoo_line_id=line_id, project_id=BILLABLE_PROJECT, task_id=None,
            date=TODAY, hours=2.0, note="2b7 legacy edit",
        )  # fmt: skip

    # Giving it a task is how it becomes editable.
    edited = await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=line_id, project_id=BILLABLE_PROJECT, task_id=task_id,
        date=TODAY, hours=2.0, note="2b7 legacy adopted",
    )  # fmt: skip
    assert edited.task_id == task_id

    # Deleting a task-less line is always allowed. Created outside temp_records,
    # because the delete itself is the cleanup.
    other = await odoo_client.execute_kw(
        "account.analytic.line",
        "create",
        [
            {
                "employee_id": EMP,
                "project_id": BILLABLE_PROJECT,
                "date": TODAY,
                "unit_amount": 1.0,
                "name": "2b7 legacy 2",
            }
        ],
    )
    other = other[0] if isinstance(other, list) else other
    assert await entry_service.delete_entry(employee_id=EMP, odoo_line_id=other) == "synced"
    assert await odoo_client.execute_kw("account.analytic.line", "search", [[("id", "=", other)]]) == []


# --- refusals --------------------------------------------------------------------------


async def test_a_closed_task_is_refused(entry_service, make_task):
    closed = await make_task(BILLABLE_PROJECT, "closed", state="1_done")
    with pytest.raises(TaskNotOpen):
        await entry_service.create_entry(
            employee_id=EMP, project_id=BILLABLE_PROJECT, task_id=closed, date=TODAY, hours=1.0, note="2b7"
        )


async def test_a_task_from_another_project_is_refused(entry_service, make_task):
    elsewhere = await make_task(28, "belongs to project 28")
    with pytest.raises(TaskNotInProject):
        await entry_service.create_entry(
            employee_id=EMP, project_id=BILLABLE_PROJECT, task_id=elsewhere, date=TODAY, hours=1.0, note="2b7"
        )


async def test_a_project_the_employee_does_not_hold_is_refused(entry_service, make_task):
    task = await make_task(29, "on an unheld project")  # employee 1 has no mapping on project 29
    with pytest.raises(ProjectNotHeld):
        await entry_service.create_entry(
            employee_id=EMP, project_id=29, task_id=task, date=TODAY, hours=1.0, note="2b7"
        )


async def test_an_unmoved_line_stays_editable_after_its_task_closes(odoo_client, entry_service, cleanup, make_task):
    task_id = await make_task(BILLABLE_PROJECT, "closes later", "same")
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, task_id)
    await odoo_client.execute_kw("project.task", "write", [[task_id], {"state": "1_done"}])

    edited = await entry_service.update_entry(
        employee_id=EMP, odoo_line_id=entry.id, project_id=BILLABLE_PROJECT, task_id=task_id,
        date=TODAY, hours=2.0, note="2b7 fix after close",
    )  # fmt: skip
    assert edited.hours == 2.0 and _so_line(await _read(odoo_client, entry.id)) == BILLABLE_LINE


# --- the billable-without-order-line warning ---------------------------------------------


async def test_a_billable_task_with_no_order_line_saves_normally_and_is_audited(
    entry_service, cleanup, make_task, session_factory, unbillable_target
):
    project_id = unbillable_target["project_id"]
    task_id = await make_task(project_id, "billable, no mapping", "yes")
    entry = await _create(entry_service, cleanup, project_id, task_id)
    assert entry.sync_state == "synced" and entry.billing_warning == BILLABLE_WITHOUT_ORDER_LINE

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(app_state={"session_factory": session_factory}))
    )
    await _audit_billing_warning(request, EMP, entry)
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLogRow).where(
                        AuditLogRow.action == BILLING_WARNING_ACTION, AuditLogRow.target == entry.outbox_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [(r.employee_id, r.outcome) for r in rows] == [(EMP, BILLABLE_WITHOUT_ORDER_LINE)]
        await session.execute(delete(AuditLogRow).where(AuditLogRow.target == entry.outbox_id))
        await session.commit()


# --- the response carries no billing, only project and task ----------------------------


async def test_the_entry_response_names_project_and_task_and_nothing_about_billing(entry_service, cleanup, make_task):
    from tti.routes.entries import _serialize

    task_id = await make_task(BILLABLE_PROJECT, "shape", "same")
    entry = await _create(entry_service, cleanup, BILLABLE_PROJECT, task_id)
    body = _serialize(entry)
    assert set(body) == {
        "id", "outbox_id", "project_id", "project_label", "task_id", "task_name", "date", "hours", "note", "sync_state"
    }  # fmt: skip
    assert body["task_name"] == "TEMP shape" and body["project_label"]
