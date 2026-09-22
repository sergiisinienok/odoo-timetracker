from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI

from tti.assignments.service import AssignmentService
from tti.auth.employees import EmployeeResolver
from tti.config import OdooProfile, Settings
from tti.entries.service import EntryService
from tti.logging import configure_logging
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooError
from tti.periods.service import PeriodService
from tti.routes.assignments import router as assignments_router
from tti.routes.auth import router as auth_router
from tti.routes.entries import router as entries_router
from tti.routes.periods import router as periods_router

logger = logging.getLogger(__name__)


class AppState(TypedDict):
    settings: Settings
    profile: OdooProfile | None
    odoo: OdooClient
    employee_resolver: EmployeeResolver
    assignment_service: AssignmentService | None
    period_service: PeriodService | None
    entry_service: EntryService | None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    profile = OdooProfile.load(settings.profile_path)
    if profile is None:
        logger.warning("odoo_profile.json not found", extra={"path": str(settings.profile_path)})

    odoo = OdooClient(settings.odoo_url, settings.odoo_db, settings.odoo_user, settings.odoo_key)
    try:
        await odoo.authenticate()
    except OdooError:
        # A transient Odoo outage at boot shouldn't stop the container from
        # starting — healthz will honestly report "unreachable" until a live
        # call succeeds. Bad credentials look the same at this point; there's
        # no way to tell them apart without trying again.
        logger.warning("odoo authentication failed at startup", exc_info=True)

    employee_resolver = EmployeeResolver(odoo)
    assignment_service = (
        AssignmentService(odoo, profile, settings.internal_project_id) if profile is not None else None
    )
    period_service = PeriodService(odoo, profile) if profile is not None else None
    entry_service = (
        EntryService(odoo, profile, assignment_service, period_service, settings.internal_project_id)
        if profile is not None and assignment_service is not None and period_service is not None
        else None
    )

    app.state.app_state = AppState(
        settings=settings,
        profile=profile,
        odoo=odoo,
        employee_resolver=employee_resolver,
        assignment_service=assignment_service,
        period_service=period_service,
        entry_service=entry_service,
    )
    try:
        yield
    finally:
        await odoo.aclose()


app = FastAPI(title="Odoo Time Tracker API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(assignments_router)
app.include_router(periods_router)
app.include_router(entries_router)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    state: AppState = app.state.app_state
    profile, odoo = state["profile"], state["odoo"]

    try:
        odoo_version = await odoo.get_version()
    except OdooError:
        logger.warning("odoo unreachable during health check", exc_info=True)
        odoo_version = None

    reachable = odoo_version is not None
    version_matches_profile = bool(
        profile is not None and odoo_version is not None and odoo_version == profile.odoo_version
    )

    return {
        "status": "ok",
        "odoo": "reachable" if reachable else "unreachable",
        "odoo_version": odoo_version,
        "version_matches_profile": version_matches_profile,
        "profile_loaded": profile is not None,
    }
