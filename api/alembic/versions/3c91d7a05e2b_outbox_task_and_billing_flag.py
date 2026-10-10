"""outbox: task_id and write_billing replace assignment (Phase 2b, step 2b.7)

Rows queued in the old shape keep draining to the line they always would have:
project_id and so_line_id were already stored explicitly (a NULL so_line_id
means "write so_line=False", the unpaid recipe), and write_billing defaults to
true, which is what the old code did on every create and update. Only the
`assignment` string goes away; where a row somehow has no project_id, it is
recovered from `project:<id>:...`. task_id stays NULL: those lines had no task.

Revision ID: 3c91d7a05e2b
Revises: 211bfd794469
Create Date: 2026-10-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c91d7a05e2b"
down_revision: str | Sequence[str] | None = "211bfd794469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("task_id", sa.Integer(), nullable=True))
    op.add_column("outbox", sa.Column("write_billing", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.execute(
        "UPDATE outbox SET project_id = split_part(assignment, ':', 2)::integer "
        "WHERE project_id IS NULL AND assignment LIKE 'project:%'"
    )
    op.drop_column("outbox", "assignment")


def downgrade() -> None:
    op.add_column("outbox", sa.Column("assignment", sa.Text(), nullable=True))
    op.execute(
        "UPDATE outbox SET assignment = CASE "
        "WHEN project_id IS NULL THEN NULL "
        # chr(58) is ':' — written out because op.execute() reads ':word' as a bind parameter.
        "WHEN so_line_id IS NULL THEN 'project' || chr(58) || project_id || chr(58) || 'unpaid' "
        "ELSE 'project' || chr(58) || project_id || chr(58) || 'paid' END"
    )
    op.drop_column("outbox", "write_billing")
    op.drop_column("outbox", "task_id")
