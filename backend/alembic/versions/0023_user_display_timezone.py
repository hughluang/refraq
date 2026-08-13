"""Add users.display_timezone for Console Instant formatting.

Revision ID: 0023_user_display_timezone
Revises: 0022_schedule_timezone
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_user_display_timezone"
down_revision: Union[str, None] = "0022_schedule_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "display_timezone")
