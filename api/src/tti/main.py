from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.auth.employees import EmployeeResolver
from tti.catalog.service import CatalogService
from tti.config import OdooProfile, Settings
from tti.db.session import make_session_factory
from tti.entries.service import EntryService
from tti.logging import configure_logging
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooError, OdooRejected
from tti.ops.readiness import check_readiness
from tti.outbox.service import OutboxService
from tti.periods.service import PeriodService
from tti.routes.auth import router as auth_router
from tti.routes.catalog import router as catalog_router
from tti.routes.entries import router as entries_router
from tti.routes.periods import router as periods_router
from tti.security.middleware import install_security

logger = logging.getLogger(__name__)


class AppState(TypedDict):
    settings: Settings
    profile: OdooProfile | None
    odoo: OdooClient
    session_factory: async_sessionmaker[AsyncSession]
    employee_resolver: EmployeeResolver
    catalog_service: CatalogService | None
    period_service: PeriodService | None
    outbox_service: OutboxService | None
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
    catalog_service = CatalogService(odoo, profile, settings.internal_project_id) if profile is not None else None
    period_service = PeriodService(odoo, profile) if profile is not None else None
    session_factory = make_session_factory(settings.database_url)
    outbox_service = (
        OutboxService(session_factory, odoo, profile, period_service)
        if profile is not None and period_service is not None
        else None
    )
    entry_service = (
        EntryService(
            odoo,
            profile,
            catalog_service,
            period_service,
            outbox_service,
            settings.internal_project_id,
            settings.daily_hour_cap,
        )
        if profile is not None
        and catalog_service is not None
        and period_service is not None
        and outbox_service is not None
        else None
    )

    app.state.app_state = AppState(
        settings=settings,
        profile=profile,
        odoo=odoo,
        session_factory=session_factory,
        employee_resolver=employee_resolver,
        catalog_service=catalog_service,
        period_service=period_service,
        outbox_service=outbox_service,
        entry_service=entry_service,
    )
    try:
        yield
    finally:
        await odoo.aclose()


app = FastAPI(title="Odoo Time Tracker API", lifespan=lifespan)
install_security(app)
app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(periods_router)
app.include_router(entries_router)


@app.exception_handler(OdooError)
async def odoo_error_handler(request: Request, exc: OdooError) -> JSONResponse:
    # A safety net, not the primary path: POST /entries's own write already
    # goes through the outbox (OdooUnavailable/Uncertain there means 202
    # pending, never an uncaught exception). This catches OdooError from
    # the *reads* every route needs before or instead of a write —
    # the catalog, periods, the pre-write project/task/period-lock checks in
    # entries/service.py — none of which have anywhere else to queue to;
    # there's nothing to enqueue if we can't even read what to write.
    logger.warning("unhandled OdooError reached the route layer", exc_info=exc)
    if isinstance(exc, OdooRejected):
        return JSONResponse(status_code=422, content={"error": "odoo_rejected", "message": str(exc)})
    # The exception text stays in the log above: it can name internal hosts,
    # and it is not something an employee can act on.
    return JSONResponse(
        status_code=503,
        content={
            "error": "odoo_unavailable",
            "message": "Odoo can't be reached right now, so this can't be checked or saved yet. Please try again in a few minutes.",
        },
    )


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


@app.get("/readyz")
async def readyz() -> JSONResponse:
    state: AppState = app.state.app_state
    result = await check_readiness(state["odoo"], state["profile"] is not None, state["session_factory"])
    return JSONResponse(
        status_code=200 if result.ready else 503,
        content={
            "status": "ready" if result.ready else "not_ready",
            "checks": result.checks,
            "oldest_pending_age_seconds": result.oldest_pending_age_seconds,
        },
    )
