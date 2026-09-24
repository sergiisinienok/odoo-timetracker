"""audit_log — step 2.8. One row per mutation attempt, allowed or refused.

Holds who did what to which target and how it ended, and nothing else: no
hours, notes, rates or amounts — the entry itself lives in Odoo, and the
outbox holds the payload while it is in flight.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from tti.db.base import Base


class AuditLogRow(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_employee_occurred", "employee_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee_id: Mapped[int | None] = mapped_column()  # null only when no session could be resolved
    action: Mapped[str] = mapped_column(Text, nullable=False)  # entry.create | entry.update | entry.delete
    target: Mapped[str | None] = mapped_column(Text)  # odoo line id, or "new"
    outcome: Mapped[str] = mapped_column(Text, nullable=False)  # synced | pending | the refusal's error code
