import dataclasses
from types import SimpleNamespace

import pytest
from switchable import SwitchableOdoo

pytestmark = pytest.mark.odoo

# Live trial data (2b.4): employee 1 is mapped to project 2 ("S00001", customer
# "Alpha Inc - Test"), 28 (Beta INC Effort Project) and 32 (Unbillable Test).
# Unbillable projects are open to everyone (decision 0014): 32 is mapped to employee 1, 33 and 1 are not.
EMPLOYEE_ID = 1
PROJECT_ID = 2
OTHER_PROJECT_ID = 28
FAR_FUTURE = "2099-06-"  # lines dated here are always the employee's most recent


async def _task(temp_records, project_id, name, **extra):
    return await temp_records("project.task", {"name": f"TEMP catalog {name}", "project_id": project_id, **extra})


async def _line(temp_records, project_id, task_id, day):
    return await temp_records(
        "account.analytic.line",
        {
            "employee_id": EMPLOYEE_ID,
            "project_id": project_id,
            "task_id": task_id,
            "date": f"{FAR_FUTURE}{day:02d}",
            "unit_amount": 1.0,
            "name": "TEMP catalog line",
            "so_line": False,
        },
    )


def _by_id(catalog):
    return {p.id: p for p in catalog}


async def test_mapped_employee_sees_each_project_once(make_catalog_service):
    catalog = await make_catalog_service().list_for_employee(EMPLOYEE_ID)
    ids = [p.id for p in catalog]

    assert len(ids) == len(set(ids))  # no paid/unpaid twins, and no duplicate when mapped *and* unbillable
    assert {PROJECT_ID, OTHER_PROJECT_ID} <= set(ids)
    assert not any("unpaid" in p.label.lower() for p in catalog)


async def test_every_unbillable_project_is_listed_by_its_own_name(make_catalog_service, unbillable_target):
    catalog = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))
    project = catalog[unbillable_target["project_id"]]  # employee 1 is not mapped to it
    assert project.label == "TEMP unbillable project"
    assert unbillable_target["task_id"] in {t.id for t in project.tasks}
    assert catalog[32].label == "Unbillable Test"


async def test_a_billable_project_the_employee_is_not_mapped_to_is_not_listed(make_catalog_service):
    # Project 29 is billable and employee 1 has no mapping on it.
    assert 29 not in _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))


async def test_an_unbillable_project_with_no_tasks_is_listed_empty(make_catalog_service, temp_records):
    project_id = await temp_records(
        "project.project", {"name": "TEMP empty unbillable", "allow_billable": False, "allow_timesheets": True}
    )
    project = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[project_id]
    assert project.tasks == ()


async def test_an_archived_or_timesheetless_unbillable_project_is_not_listed(make_catalog_service, temp_records):
    archived = await temp_records(
        "project.project", {"name": "TEMP archived", "allow_billable": False, "allow_timesheets": True, "active": False}
    )
    no_timesheets = await temp_records(
        "project.project", {"name": "TEMP no timesheets", "allow_billable": False, "allow_timesheets": False}
    )
    ids = {p.id for p in await make_catalog_service().list_for_employee(EMPLOYEE_ID)}
    assert archived not in ids and no_timesheets not in ids


async def test_mapped_projects_come_first_then_the_other_unbillable_ones_by_name(make_catalog_service):
    labels_in_order = [p.id for p in await make_catalog_service().list_for_employee(EMPLOYEE_ID)]
    mapped = [pid for pid in labels_in_order if pid in (PROJECT_ID, OTHER_PROJECT_ID, 32)]
    assert labels_in_order[: len(mapped)] == mapped


async def test_a_closed_task_is_absent_and_an_open_one_present(make_catalog_service, temp_records):
    open_id = await _task(temp_records, PROJECT_ID, "open")
    done_id = await _task(temp_records, PROJECT_ID, "done", state="1_done")
    cancelled_id = await _task(temp_records, PROJECT_ID, "cancelled", state="1_canceled")

    task_ids = {t.id for t in _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].tasks}

    assert open_id in task_ids
    assert done_id not in task_ids
    assert cancelled_id not in task_ids


async def test_an_archived_task_is_absent(make_catalog_service, temp_records):
    archived_id = await _task(temp_records, PROJECT_ID, "archived", active=False)
    task_ids = {t.id for t in _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].tasks}
    assert archived_id not in task_ids


async def test_a_task_from_another_project_never_appears_under_this_one(
    odoo_client, make_catalog_service, temp_records
):
    other_task_id = await _task(temp_records, OTHER_PROJECT_ID, "belongs to the other project")
    catalog = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))

    assert other_task_id in {t.id for t in catalog[OTHER_PROJECT_ID].tasks}
    assert other_task_id not in {t.id for t in catalog[PROJECT_ID].tasks}
    for project in catalog.values():
        rows = await odoo_client.execute_kw(
            "project.task", "read", [[t.id for t in project.tasks]], {"fields": ["project_id"]}
        )
        assert {r["project_id"][0] for r in rows} <= {project.id}


async def test_a_task_ops_adds_appears_on_the_next_uncached_call(make_catalog_service, temp_records):
    before = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].tasks
    new_id = await _task(temp_records, PROJECT_ID, "added by ops")
    after = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].tasks
    assert new_id not in {t.id for t in before}
    assert new_id in {t.id for t in after}


async def test_last_used_task_follows_the_most_recent_line(make_catalog_service, temp_records):
    first = await _task(temp_records, PROJECT_ID, "first")
    second = await _task(temp_records, PROJECT_ID, "second")
    await _line(temp_records, PROJECT_ID, first, 1)
    await _line(temp_records, PROJECT_ID, second, 2)
    assert _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].last_used_task_id == second

    await _line(temp_records, PROJECT_ID, first, 3)  # now the most recent
    assert _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID].last_used_task_id == first


async def test_last_used_is_per_project(make_catalog_service, temp_records):
    here = await _task(temp_records, PROJECT_ID, "here")
    there = await _task(temp_records, OTHER_PROJECT_ID, "there")
    await _line(temp_records, PROJECT_ID, here, 4)
    await _line(temp_records, OTHER_PROJECT_ID, there, 5)
    catalog = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))
    assert catalog[PROJECT_ID].last_used_task_id == here
    assert catalog[OTHER_PROJECT_ID].last_used_task_id == there


async def test_a_closed_last_used_task_is_not_offered(odoo_client, make_catalog_service, temp_records):
    task_id = await _task(temp_records, PROJECT_ID, "closed later")
    await _line(temp_records, PROJECT_ID, task_id, 6)
    project = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID]
    assert project.last_used_task_id == task_id

    await odoo_client.execute_kw("project.task", "write", [[task_id], {"state": "1_done"}])
    project = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))[PROJECT_ID]
    assert task_id not in {t.id for t in project.tasks}
    assert project.last_used_task_id is None


async def test_the_catalog_carries_no_billing_field_of_any_kind(make_catalog_service):
    catalog = await make_catalog_service().list_for_employee(EMPLOYEE_ID)
    names = {f.name for f in dataclasses.fields(catalog[0])} | {f.name for f in dataclasses.fields(catalog[0].tasks[0])}
    assert names == {"id", "label", "tasks", "is_default", "last_used_task_id", "name"}

    # ...and the route's serialisation (routes/catalog.py) adds nothing either.
    import tti.routes.catalog as route_module

    class _Service:
        async def list_for_employee(self, employee_id):
            return catalog

    async def _session(_request):
        return SimpleNamespace(employee_id=EMPLOYEE_ID)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_state={"catalog_service": _Service()})))
    original = route_module.get_current_session
    route_module.get_current_session = _session
    try:
        body = await route_module.get_catalog(request)
    finally:
        route_module.get_current_session = original

    # Keys only: task *names* are ops' data and may say "billable".
    keys = {k for project in body for k in project} | {k for project in body for t in project["tasks"] for k in t}
    assert keys == {"project_id", "label", "is_default", "last_used_task_id", "tasks", "id", "name"}


async def test_an_outage_serves_the_last_known_catalog(odoo_client, profile):
    from tti.catalog.service import CatalogService

    switch = SwitchableOdoo(odoo_client)
    service = CatalogService(switch, profile)
    warm = await service.snapshot(EMPLOYEE_ID)

    service._cache._entries[EMPLOYEE_ID] = (warm, 0.0, 0.0)  # expire freshness, keep last-known
    switch.down = True
    assert await service.snapshot(EMPLOYEE_ID) == warm


async def test_a_cold_cache_during_an_outage_refuses(odoo_client, profile):
    from tti.catalog.service import CatalogService
    from tti.odoo.errors import OdooUnavailable

    switch = SwitchableOdoo(odoo_client)
    switch.down = True
    service = CatalogService(switch, profile)
    with pytest.raises(OdooUnavailable):
        await service.list_for_employee(EMPLOYEE_ID)


async def test_an_employee_with_no_mapping_sees_only_unbillable_projects(
    odoo_client, make_catalog_service, unbillable_target
):
    temp_id = await odoo_client.execute_kw(
        "hr.employee", "create", [{"name": "TEMP unmapped employee for catalog test"}]
    )
    temp_id = temp_id[0] if isinstance(temp_id, list) else temp_id
    try:
        catalog = await make_catalog_service().list_for_employee(temp_id)
        assert unbillable_target["project_id"] in {p.id for p in catalog}
        assert PROJECT_ID not in {p.id for p in catalog}  # billable: only through a mapping
        assert all(p.last_used_task_id is None for p in catalog)
    finally:
        await odoo_client.execute_kw("hr.employee", "unlink", [[temp_id]])


async def test_default_project_is_flagged_and_an_unlisted_default_is_dropped(odoo_client, make_catalog_service, caplog):
    default_field = "x_studio_default_project"
    catalog = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))
    original = (await odoo_client.execute_kw("hr.employee", "read", [[EMPLOYEE_ID]], {"fields": [default_field]}))[0][
        default_field
    ]
    try:
        await odoo_client.execute_kw("hr.employee", "write", [[EMPLOYEE_ID], {default_field: OTHER_PROJECT_ID}])
        flagged = await make_catalog_service().list_for_employee(EMPLOYEE_ID)
        assert [p.id for p in flagged if p.is_default] == [OTHER_PROJECT_ID]

        await odoo_client.execute_kw("hr.employee", "write", [[EMPLOYEE_ID], {default_field: 29}])  # not mapped
        assert 29 not in catalog
        with caplog.at_level("WARNING"):
            dropped = await make_catalog_service().list_for_employee(EMPLOYEE_ID)
        assert not any(p.is_default for p in dropped)
        assert any("default project is not in their catalog" in r.message for r in caplog.records)
    finally:
        await odoo_client.execute_kw(
            "hr.employee", "write", [[EMPLOYEE_ID], {default_field: original[0] if original else False}]
        )


async def test_every_project_is_labelled_by_its_odoo_name_never_by_customer(
    odoo_client, make_catalog_service, temp_records
):
    # Two projects for one customer must be told apart by their own names.
    alpha_partner_id = 11  # "Alpha Inc - Test", also the customer of project 2
    project_id = await temp_records("project.project", {"name": "TEMP second Alpha project", "allow_billable": True})
    # Order matters: writing partner_id *before* the mapping row exists gets
    # silently reset to False (CLAUDE.md, step 1.4), so map first, then write it.
    await temp_records(
        "project.sale.line.employee.map",
        {"project_id": project_id, "employee_id": EMPLOYEE_ID, "sale_line_id": 1},
    )
    await odoo_client.execute_kw("project.project", "write", [[project_id], {"partner_id": alpha_partner_id}])

    catalog = _by_id(await make_catalog_service().list_for_employee(EMPLOYEE_ID))
    names = {
        r["id"]: r["name"]
        for r in await odoo_client.execute_kw(
            "project.project", "read", [[PROJECT_ID, project_id]], {"fields": ["name"]}
        )
    }
    assert catalog[PROJECT_ID].label == names[PROJECT_ID]
    assert catalog[project_id].label == "TEMP second Alpha project"
    assert "Alpha Inc" not in catalog[PROJECT_ID].label


async def test_odoos_built_in_internal_project_is_not_listed(odoo_client, make_catalog_service, profile):
    # Odoo hides its own company "Internal" project in its UI (is_internal_project); the app follows.
    internal_ids = await odoo_client.execute_kw(
        "project.project", "search", [[(profile.project_internal_field, "=", True)]]
    )
    assert internal_ids, "the sandbox is expected to have Odoo's built-in internal project"
    listed = {p.id for p in await make_catalog_service().list_for_employee(EMPLOYEE_ID)}
    assert not listed & set(internal_ids)
