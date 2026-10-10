"""baseline

Revision ID: 7dafe3b051d8
Revises:
Create Date: 2026-09-20 16:08:51.670986

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7dafe3b051d8"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
