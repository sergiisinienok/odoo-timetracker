"""Test-only helper for web/e2e/month-view.spec.ts: seed or remove a
pending outbox row directly, so the Playwright pending-state test can
check *rendering* without needing to actually break Odoo connectivity for
the running api process (see CLAUDE.md / step 2.3's commit for why a
real, isolated network outage isn't achievable in this dev setup without
losing the api process's warm caches). The save->pending->drain mechanics
themselves are already proven for real by api/tests/odoo/test_outbox.py.

Usage:
    uv run python tools/outbox_test_seed.py insert <employee_id> <date> <hours> <note>
    uv run python tools/outbox_test_seed.py delete <outbox_id>
    uv run python tools/outbox_test_seed.py sweep-prefix <note_prefix>   # prints how many rows it removed
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date as date_type
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete

from tti.config import Settings
from tti.db.session import make_session_factory
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState


async def insert(employee_id: int, entry_date: date_type, hours: Decimal, note: str) -> UUID:
    settings = Settings.from_env()
    session_factory = make_session_factory(settings.database_url)
    outbox_id = uuid4()
    async with session_factory() as session:
        session.add(
            OutboxRow(
                id=outbox_id,
                employee_id=employee_id,
                op=OutboxOp.CREATE.value,
                entry_date=entry_date,
                hours=hours,
                assignment="internal",
                project_id=settings.internal_project_id,
                so_line_id=None,
                note=note,
                state=OutboxState.PENDING.value,
                attempts=1,
            )
        )
        await session.commit()
    return outbox_id


async def delete_row(outbox_id: UUID) -> None:
    settings = Settings.from_env()
    session_factory = make_session_factory(settings.database_url)
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id == outbox_id))
        await session.commit()


async def sweep_prefix(prefix: str) -> int:
    """Remove every outbox row whose note starts with `prefix` — the e2e suite
    tags all the rows it creates, so a leak from any earlier aborted run is
    cleaned up by prefix, with no clock or id bookkeeping."""
    settings = Settings.from_env()
    session_factory = make_session_factory(settings.database_url)
    async with session_factory() as session:
        result = await session.execute(delete(OutboxRow).where(OutboxRow.note.like(prefix + "%")))
        await session.commit()
        return result.rowcount or 0


def main() -> None:
    command = sys.argv[1]
    if command == "insert":
        employee_id, date_str, hours_str, note = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
        outbox_id = asyncio.run(insert(int(employee_id), date_type.fromisoformat(date_str), Decimal(hours_str), note))
        print(outbox_id)
    elif command == "delete":
        asyncio.run(delete_row(UUID(sys.argv[2])))
    elif command == "sweep-prefix":
        print(asyncio.run(sweep_prefix(sys.argv[2])))
    else:
        sys.exit(f"unknown command {command!r}")


if __name__ == "__main__":
    main()
