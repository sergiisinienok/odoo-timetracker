"""Daily digest scheduling — step 2.7. Sleeps until the next DIGEST_HOUR_UTC,
so a worker restart never re-sends today's digest."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.odoo.client import OdooClient
from tti.ops.digest import gather, render, send

logger = logging.getLogger(__name__)


def seconds_until(now: datetime, hour_utc: int) -> float:
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def send_digest_now(
    odoo: OdooClient, session_factory: async_sessionmaker[AsyncSession], recipients: str
) -> int:
    now = datetime.now(timezone.utc)
    digest = await gather(odoo, session_factory, now)
    subject, body = render(digest, now.date())
    mail_id = await send(odoo, recipients, subject, body)
    logger.info("ops digest queued in odoo", extra={"mail_id": mail_id, "empty": digest.is_empty})
    return mail_id


async def run_digest_loop(
    session_factory: async_sessionmaker[AsyncSession], odoo: OdooClient, recipients: str, hour_utc: int
) -> None:
    if not recipients:
        logger.warning("OPS_DIGEST_TO is empty — daily digest disabled")
        return
    while True:
        await asyncio.sleep(seconds_until(datetime.now(timezone.utc), hour_utc))
        try:
            await send_digest_now(odoo, session_factory, recipients)
        except Exception:  # a failed digest must not take the outbox worker down with it
            logger.error("ops digest failed", exc_info=True)
