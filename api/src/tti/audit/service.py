from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.audit.models import AuditLogRow

logger = logging.getLogger(__name__)

# audit_log.action for a save that resolved billable with no order line to bill
# against; `outcome` carries the warning name, `target` the outbox id.
BILLING_WARNING_ACTION = "entry.billing_warning"


async def record(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    employee_id: int | None,
    action: str,
    target: str | None,
    outcome: str,
) -> None:
    """Best-effort by design: the mutation has already happened (or been
    refused) by the time this runs, and losing an employee's input because the
    audit insert failed would be the worse outcome. A failure is logged at
    ERROR so ops sees it, not swallowed silently."""
    try:
        async with session_factory() as session:
            session.add(AuditLogRow(employee_id=employee_id, action=action, target=target, outcome=outcome))
            await session.commit()
    except Exception:
        logger.exception(
            "audit_log write failed",
            extra={"employee_id": employee_id, "action": action, "target": target, "outcome": outcome},
        )
