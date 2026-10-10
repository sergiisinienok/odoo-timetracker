"""`python -m tti.ops` — send the digest right now (for the step 2.7 validation run)."""

import asyncio

from tti.config import OdooProfile, Settings
from tti.db.session import make_session_factory
from tti.logging import configure_logging
from tti.odoo.client import OdooClient
from tti.ops.scheduler import send_digest_now


async def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if not settings.ops_digest_to:
        raise SystemExit("OPS_DIGEST_TO is empty")
    profile = OdooProfile.load(settings.profile_path)
    if profile is None:
        raise SystemExit(f"odoo_profile.json not found at {settings.profile_path}")
    odoo = OdooClient(settings.odoo_url, settings.odoo_db, settings.odoo_user, settings.odoo_key)
    try:
        await send_digest_now(
            odoo,
            make_session_factory(settings.database_url),
            settings.ops_digest_to,
            profile,
        )
    finally:
        await odoo.aclose()


asyncio.run(main())
