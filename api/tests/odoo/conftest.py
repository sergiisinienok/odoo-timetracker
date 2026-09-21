import os

import pytest

from tti.assignments.service import AssignmentService
from tti.config import OdooProfile, Settings
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


@pytest.fixture
def assignment_service(odoo_client):
    settings = Settings.from_env()
    profile = OdooProfile.load(settings.profile_path)
    assert profile is not None, "odoo_profile.json must be present for these tests"
    return AssignmentService(odoo_client, profile, settings.internal_project_id)
