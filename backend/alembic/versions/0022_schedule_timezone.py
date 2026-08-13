"""Add Schedule Timezone (IANA) to scheduled_tasks.

Revision ID: 0022_schedule_timezone
Revises: 0021_instant_timestamptz
Create Date: 2026-08-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_schedule_timezone"
down_revision: Union[str, None] = "0021_instant_timestamptz"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "schedule_timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "schedule_timezone")
