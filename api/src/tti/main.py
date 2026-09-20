from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TypedDict

import httpx
from fastapi import FastAPI

from tti.config import OdooProfile, Settings
from tti.logging import configure_logging
from tti.odoo.version_check import get_odoo_version

logger = logging.getLogger(__name__)


class AppState(TypedDict):
    settings: Settings
    profile: OdooProfile | None
    http_client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    profile = OdooProfile.load(settings.profile_path)
    if profile is None:
        logger.warning("odoo_profile.json not found", extra={"path": str(settings.profile_path)})
    async with httpx.AsyncClient() as http_client:
        app.state.app_state = AppState(settings=settings, profile=profile, http_client=http_client)
        yield


app = FastAPI(title="Odoo Time Tracker API", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    state: AppState = app.state.app_state
    settings, profile, http_client = state["settings"], state["profile"], state["http_client"]

    odoo_version = await get_odoo_version(http_client, settings.odoo_url)
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
