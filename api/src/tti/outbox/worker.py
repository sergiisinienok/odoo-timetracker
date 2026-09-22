"""Outbox worker — step 2.3.

Polls every 10 seconds, one row per transaction (SELECT ... FOR UPDATE
SKIP LOCKED), so a row's lock is held for exactly as long as one attempt
takes and two workers never process the same row twice — see
outbox/service.py's attempt_row for why the lock has to span the Odoo
call itself, not just the dequeue.

Also prunes synced rows older than 7 days, once a day. Failed rows are
never auto-deleted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.config import OdooProfile
from tti.odoo.client import OdooClient
from tti.outbox.models import OutboxRow, OutboxState
from tti.outbox.service import attempt_row
from tti.periods.service import PeriodService

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
PRUNE_INTERVAL_SECONDS = 24 * 60 * 60
PRUNE_AGE = timedelta(days=7)


async def process_one_pending_row(
    session_factory: async_sessionmaker[AsyncSession],
    odoo: OdooClient,
    profile: OdooProfile,
    periods: PeriodService,
) -> bool:
    """Locks and processes at most one due pending row.

    Returns True if a row was found (whether or not it fully synced),
    False if nothing is currently due.
    """
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        row = (
            await session.execute(
                select(OutboxRow)
                .where(OutboxRow.state == OutboxState.PENDING.value, OutboxRow.next_attempt <= now)
                .order_by(OutboxRow.next_attempt)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

        if row is None:
            return False

        await attempt_row(session, row, odoo, profile, periods, reconcile_first=row.attempts > 0)
        return True


async def prune_old_synced_rows(session_factory: async_sessionmaker[AsyncSession]) -> int:
    cutoff = datetime.now(timezone.utc) - PRUNE_AGE
    async with session_factory() as session:
        result = await session.execute(
            delete(OutboxRow).where(OutboxRow.state == OutboxState.SYNCED.value, OutboxRow.updated_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0


async def run_worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    odoo: OdooClient,
    profile: OdooProfile,
    periods: PeriodService,
) -> None:
    last_prune = datetime.now(timezone.utc)
    while True:
        try:
            while await process_one_pending_row(session_factory, odoo, profile, periods):
                pass  # drain everything currently due before sleeping
        except Exception:
            logger.exception("outbox worker: error processing a row")

        now = datetime.now(timezone.utc)
        if now - last_prune >= timedelta(seconds=PRUNE_INTERVAL_SECONDS):
            try:
                pruned = await prune_old_synced_rows(session_factory)
                if pruned:
                    logger.info("outbox: pruned old synced rows", extra={"count": pruned})
            except Exception:
                logger.exception("outbox worker: error pruning")
            last_prune = now

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
