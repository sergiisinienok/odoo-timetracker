import dataclasses

import pytest

pytestmark = pytest.mark.odoo

# Live trial data as of step 1.4: employees 1 (Sergii, T&M) and 3
# (flat-rate) are both mapped to project 2 (S00001, customer
# "Alpha Inc - Test"), sale lines 1 and 3 respectively.
TM_EMPLOYEE_ID = 1
FLAT_RATE_EMPLOYEE_ID = 3
ALPHA_PARTNER_ID = 11


async def test_mapped_employee_gets_one_paid_one_unpaid_and_internal(assignment_service):
    assignments = await assignment_service.list_for_employee(TM_EMPLOYEE_ID)
    assert sorted(a.kind for a in assignments) == ["internal", "paid", "unpaid"]


async def test_flat_rate_assignment_shape_matches_tm(assignment_service):
    tm_paid = next(a for a in await assignment_service.list_for_employee(TM_EMPLOYEE_ID) if a.kind == "paid")
    flat_paid = next(
        a for a in await assignment_service.list_for_employee(FLAT_RATE_EMPLOYEE_ID) if a.kind == "paid"
    )

    assert {f.name for f in dataclasses.fields(tm_paid)} == {f.name for f in dataclasses.fields(flat_paid)}
    assert isinstance(flat_paid.so_line_id, int)


async def test_customer_with_two_projects_gets_disambiguated_labels(odoo_client, assignment_service):
    # Employee 1 is already mapped to project 2 (S00001, "Alpha Inc -
    # Test"). Add a second project under the same customer, mapped to the
    # same employee — only the label logic is under test, so reusing an
    # existing sale order line is fine; nothing here touches invoicing.
    project_id = await odoo_client.execute_kw(
        "project.project", "create", [{"name": "TEMP second project for label test"}]
    )
    try:
        # Order matters here: writing partner_id *before* creating the
        # mapping row gets silently reset back to False by the time the row
        # exists — reproducible, undiagnosed. Creating the mapping row
        # first, then writing partner_id, sticks reliably.
        map_id = await odoo_client.execute_kw(
            "project.sale.line.employee.map",
            "create",
            [{"project_id": project_id, "employee_id": TM_EMPLOYEE_ID, "sale_line_id": 1}],
        )
        try:
            await odoo_client.execute_kw("project.project", "write", [[project_id], {"partner_id": ALPHA_PARTNER_ID}])
            assignments = await assignment_service.list_for_employee(TM_EMPLOYEE_ID)
            paid_labels = {a.project_id: a.label for a in assignments if a.kind == "paid"}
            assert len(paid_labels) == 2
            assert len(set(paid_labels.values())) == 2
            for label in paid_labels.values():
                assert "Alpha Inc - Test" in label
        finally:
            await odoo_client.execute_kw("project.sale.line.employee.map", "unlink", [[map_id]])
    finally:
        await odoo_client.execute_kw("project.project", "unlink", [[project_id]])


async def test_employee_with_no_mapping_gets_only_internal(odoo_client, assignment_service):
    temp_id = await odoo_client.execute_kw(
        "hr.employee", "create", [{"name": "TEMP unmapped employee for assignments test"}]
    )
    try:
        assignments = await assignment_service.list_for_employee(temp_id)
        assert len(assignments) == 1
        assert assignments[0].kind == "internal"
    finally:
        await odoo_client.execute_kw("hr.employee", "unlink", [[temp_id]])


async def test_default_pointing_at_unmapped_project_is_dropped_with_warning(odoo_client, assignment_service, caplog):
    # project 2 (S00001) is a real project, just not one this employee is
    # paid-mapped to — exactly the "default points somewhere they can't
    # actually use" scenario.
    temp_id = await odoo_client.execute_kw(
        "hr.employee",
        "create",
        [{"name": "TEMP employee with bad default for assignments test", "x_studio_default_project": 2}],
    )
    try:
        with caplog.at_level("WARNING"):
            assignments = await assignment_service.list_for_employee(temp_id)
        assert len(assignments) == 1
        assert not any(a.is_default for a in assignments)
        assert any("default project is not in their assignment list" in r.message for r in caplog.records)
    finally:
        await odoo_client.execute_kw("hr.employee", "unlink", [[temp_id]])
