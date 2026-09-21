import pytest

from tti.auth.employees import EmployeeResolver
from tti.auth.errors import EmployeeAmbiguous, EmployeeNotFound
from tti.auth.session import create_session_jwt, decode_session_jwt

pytestmark = pytest.mark.odoo


@pytest.fixture
def resolver(odoo_client):
    return EmployeeResolver(odoo_client)


async def test_unknown_email_returns_employee_not_found(resolver):
    with pytest.raises(EmployeeNotFound):
        await resolver.resolve("no-such-person-xyz@particlesglobal.com")


async def test_duplicate_work_email_returns_employee_ambiguous(odoo_client, resolver):
    shared_email = "polina@particlesglobal.com"
    dup_id = await odoo_client.execute_kw(
        "hr.employee",
        "create",
        [{"name": "TEMP duplicate for test_employee_resolution", "work_email": shared_email}],
    )
    try:
        with pytest.raises(EmployeeAmbiguous):
            await resolver.resolve(shared_email)
    finally:
        await odoo_client.execute_kw("hr.employee", "unlink", [[dup_id]])


async def test_valid_employee_resolves_and_session_matches_odoo(odoo_client, resolver):
    email = "s.sinienok@particlesglobal.com"
    [expected] = await odoo_client.execute_kw(
        "hr.employee",
        "search_read",
        [[("work_email", "=", email), ("active", "=", True)]],
        {"fields": ["id", "name", "tz"]},
    )

    resolved = await resolver.resolve(email)
    assert resolved.employee_id == expected["id"]
    assert resolved.name == expected["name"]

    secret = "test-secret-0123456789abcdef0123456789"  # 32+ bytes, avoids jwt's InsecureKeyLengthWarning
    token = create_session_jwt(resolved.employee_id, resolved.timezone, secret=secret)
    payload = decode_session_jwt(token, secret=secret)
    assert payload.employee_id == expected["id"]
