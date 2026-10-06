"""Add the optional Scheduled Task start anchor.

Revision ID: 0048_schedule_start_at
Revises: 0047_jobs_trigger_index

Existing rows stay null (start immediately), so stored commitments are unchanged.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_schedule_start_at"
down_revision: Union[str, None] = "0047_jobs_trigger_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "start_at")
