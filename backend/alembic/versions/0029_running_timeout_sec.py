"""Optional Running Time Limit on schedules and Job snapshots.

Revision ID: 0029_running_timeout_sec
Revises: 0028_schedule_next_run_backfill
Create Date: 2026-08-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_running_timeout_sec"
down_revision: Union[str, None] = "0028_schedule_next_run_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("running_timeout_sec", sa.Integer(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("running_timeout_sec", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "running_timeout_sec")
    op.drop_column("scheduled_tasks", "running_timeout_sec")
