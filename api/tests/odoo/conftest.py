import os

import pytest

from tti.odoo.client import OdooClient


@pytest.fixture
async def odoo_client():
    async with OdooClient(
        url=os.environ["ODOO_URL"],
        db=os.environ["ODOO_DB"],
        user=os.environ["ODOO_USER"],
        api_key=os.environ["ODOO_KEY"],
    ) as client:
        yield client
