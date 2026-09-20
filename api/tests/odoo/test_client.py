import pytest

from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooRejected, OdooUnavailable

pytestmark = pytest.mark.odoo


async def test_authenticate_succeeds(odoo_client):
    uid = await odoo_client.authenticate()
    assert isinstance(uid, int)
    assert uid > 0


async def test_read_res_users_returns_integration_uid(odoo_client):
    uid = await odoo_client.authenticate()
    [record] = await odoo_client.execute_kw("res.users", "read", [[uid]], {"fields": ["login"]})
    assert record["id"] == uid


async def test_malformed_call_raises_rejected_not_unavailable(odoo_client):
    with pytest.raises(OdooRejected):
        await odoo_client.execute_kw("not.a.real.model", "search_read", [[]], {})


async def test_unreachable_host_raises_unavailable_within_timeout():
    client = OdooClient(
        url="https://odoo-does-not-exist.invalid",
        db="doesnotmatter",
        user="doesnotmatter",
        api_key="doesnotmatter",
        timeout=15.0,
    )
    try:
        with pytest.raises(OdooUnavailable):
            await client.authenticate()
    finally:
        await client.aclose()
