import os

import pytest

from tti.catalog.service import CatalogService
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
def entry_service(odoo_client, profile, make_catalog_service, period_service, outbox_service):
    settings = Settings.from_env()
    return EntryService(
        odoo_client,
        profile,
        make_catalog_service(),
        period_service,
        outbox_service,
        settings.internal_project_id,
        settings.daily_hour_cap,
    )


@pytest.fixture
def make_catalog_service(odoo_client, profile):
    """A fresh CatalogService per call, so each sees Odoo uncached."""
    settings = Settings.from_env()

    def make(odoo=None):
        return CatalogService(odoo or odoo_client, profile, settings.internal_project_id)

    return make


@pytest.fixture
async def temp_records(odoo_client):
    """Create records through `make(model, vals)`; remove them all afterwards."""
    created: list[tuple[str, int]] = []

    async def make(model, vals):
        rid = await odoo_client.execute_kw(model, "create", [vals])
        rid = rid[0] if isinstance(rid, list) else rid
        created.append((model, rid))
        return rid

    yield make
    for model, rid in reversed(created):
        await odoo_client.execute_kw(model, "unlink", [[rid]])


@pytest.fixture
def make_task(temp_records, profile):
    """A throwaway task on `project_id`. `override` is "same", "yes" or "no"
    (the profile's three value names); extra Odoo values pass through."""

    async def make(project_id, name="task", override=None, **extra):
        vals = {"name": f"TEMP {name}", "project_id": project_id, **extra}
        if override is not None:
            vals[profile.task_billable_field] = {
                "same": profile.task_billable_same_as_project_value,
                "yes": profile.task_billable_yes_value,
                "no": profile.task_billable_no_value,
            }[override]
        return await temp_records("project.task", vals)

    return make


@pytest.fixture
async def internal_target(make_task):
    """Where tests that just need *an* entry log it: a Not-billable task on
    the internal project (the way ops sets PTO, Bench and so on)."""
    settings = Settings.from_env()
    return {
        "project_id": settings.internal_project_id,
        "task_id": await make_task(settings.internal_project_id, "internal", "no"),
    }
