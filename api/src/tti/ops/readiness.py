"""Readiness checks behind /readyz — step 2.7.

/healthz says the process is alive; /readyz says it can do its job: Odoo
answers, the profile is loaded, Postgres answers, and the outbox is not
stuck. The stuck-outbox threshold is the plan's own 15 minutes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooError
from tti.outbox.models import OutboxRow, OutboxState

logger = logging.getLogger(__name__)

OLDEST_PENDING_LIMIT = timedelta(minutes=15)


@dataclass(frozen=True)
class Readiness:
    checks: dict[str, bool]
    oldest_pending_age_seconds: int | None

    @property
    def ready(self) -> bool:
        return all(self.checks.values())


def evaluate(
    *,
    odoo_reachable: bool,
    profile_loaded: bool,
    db_reachable: bool,
    oldest_pending_created_at: datetime | None,
    now: datetime,
) -> Readiness:
    age = None if oldest_pending_created_at is None else now - oldest_pending_created_at
    return Readiness(
        checks={
            "odoo": odoo_reachable,
            "profile": profile_loaded,
            "database": db_reachable,
            "outbox": age is None or age < OLDEST_PENDING_LIMIT,
        },
        oldest_pending_age_seconds=None if age is None else int(age.total_seconds()),
    )


async def check_readiness(
    odoo: OdooClient, profile_loaded: bool, session_factory: async_sessionmaker[AsyncSession]
) -> Readiness:
    try:
        await odoo.get_version()
        odoo_reachable = True
    except OdooError:
        logger.warning("readyz: odoo unreachable", exc_info=True)
        odoo_reachable = False

    db_reachable = True
    oldest: datetime | None = None
    try:
        async with session_factory() as session:
            await session.execute(text("select 1"))
            oldest = await session.scalar(
                select(func.min(OutboxRow.created_at)).where(OutboxRow.state == OutboxState.PENDING.value)
            )
    except Exception:  # any DB failure means "not ready", whatever its type
        logger.warning("readyz: database check failed", exc_info=True)
        db_reachable = False

    return evaluate(
        odoo_reachable=odoo_reachable,
        profile_loaded=profile_loaded,
        db_reachable=db_reachable,
        oldest_pending_created_at=oldest,
        now=datetime.now(timezone.utc),
    )
