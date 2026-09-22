"""Outbox worker entrypoint — step 2.3. Real polling loop now, see
outbox/worker.py."""

from __future__ import annotations

import asyncio
import logging

from tti.config import OdooProfile, Settings
from tti.db.session import make_session_factory
from tti.logging import configure_logging
from tti.odoo.client import OdooClient
from tti.outbox.worker import run_worker_loop
from tti.periods.service import PeriodService

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    profile = OdooProfile.load(settings.profile_path)
    if profile is None:
        raise RuntimeError(f"odoo_profile.json not found at {settings.profile_path} — worker cannot run without it")

    odoo = OdooClient(settings.odoo_url, settings.odoo_db, settings.odoo_user, settings.odoo_key)
    await odoo.authenticate()

    session_factory = make_session_factory(settings.database_url)
    periods = PeriodService(odoo, profile)

    logger.info("outbox worker started")
    try:
        await run_worker_loop(session_factory, odoo, profile, periods)
    finally:
        await odoo.aclose()


if __name__ == "__main__":
    asyncio.run(main())
