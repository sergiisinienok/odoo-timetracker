import os

import pytest

from tti.assignments.service import AssignmentService
from tti.config import OdooProfile, Settings
from tti.db.session import make_session_factory
from tti.entries.service import EntryService
from tti.odoo.client import OdooClient
from tti.outbox.service import OutboxService
from tti.periods.service import PeriodService


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
def profile():
    settings = Settings.from_env()
    p = OdooProfile.load(settings.profile_path)
    assert p is not None, "odoo_profile.json must be present for these tests"
    return p


@pytest.fixture
def assignment_service(odoo_client, profile):
    settings = Settings.from_env()
    return AssignmentService(odoo_client, profile, settings.internal_project_id)


@pytest.fixture
def period_service(odoo_client, profile):
    return PeriodService(odoo_client, profile)


@pytest.fixture
def session_factory():
    settings = Settings.from_env()
    return make_session_factory(settings.database_url)


@pytest.fixture
def outbox_service(odoo_client, profile, period_service, session_factory):
    return OutboxService(session_factory, odoo_client, profile, period_service)


@pytest.fixture
def entry_service(odoo_client, profile, assignment_service, period_service, outbox_service):
    settings = Settings.from_env()
    return EntryService(
        odoo_client,
        profile,
        assignment_service,
        period_service,
        outbox_service,
        settings.internal_project_id,
        settings.daily_hour_cap,
    )
