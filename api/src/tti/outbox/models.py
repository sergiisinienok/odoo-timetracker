"""The outbox table — step 2.3. Schema matches
docs/implementation-plan.md's own `create table outbox (...)` exactly.

The row's own `id` doubles as the Odoo-side app entry id
(`profile.app_entry_id_field`) — the same UUID that reconcile-before-create
searches Odoo for, so there's one identifier, not two kept in sync.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from tti.db.base import Base


class OutboxOp(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class OutboxState(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"


class OutboxRow(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("op in ('create','update','delete')", name="outbox_op_check"),
        CheckConstraint("state in ('pending','synced','failed')", name="outbox_state_check"),
        Index("ix_outbox_state_next_attempt", "state", "next_attempt"),
        Index(
            "ix_outbox_employee_pending",
            "employee_id",
            "entry_date",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[int] = mapped_column(nullable=False)
    op: Mapped[str] = mapped_column(Text, nullable=False)
    entry_date: Mapped[date] = mapped_column(nullable=False)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    project_id: Mapped[int | None] = mapped_column()
    # Null for rows queued before Phase 2b (no task) and for deletes.
    task_id: Mapped[int | None] = mapped_column()
    so_line_id: Mapped[int | None] = mapped_column()
    # Whether an update writes project, task and so_line at all. False when
    # the entry service decided billing must be left alone — the line carries
    # an approver's override, or project and task did not change (decision
    # 0011). Always true for creates and for rows queued before Phase 2b.
    write_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    note: Mapped[str | None] = mapped_column(Text)
    odoo_line_id: Mapped[int | None] = mapped_column()
    state: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    next_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
