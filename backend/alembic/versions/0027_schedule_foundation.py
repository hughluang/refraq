"""Schedule foundation: owner_ref, next_run_at, job scheduled_for and occupancy.

Revision ID: 0027_schedule_foundation
Revises: 0026_structure_enqueue_task_name
Create Date: 2026-08-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_schedule_foundation"
down_revision: Union[str, None] = "0026_structure_enqueue_task_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("owner_ref", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column("next_run_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_tasks_owner_ref",
        "scheduled_tasks",
        ["owner_ref"],
    )
    op.create_index(
        "ix_scheduled_tasks_next_run_at",
        "scheduled_tasks",
        ["next_run_at"],
    )
    # Backfill: enabled rows get next_run_at = now so Beat does not treat
    # a past last_run_at as an overdue commitment (one due tick at upgrade
    # is enough; Beat must not storm).
    op.execute(
        """
        UPDATE scheduled_tasks
        SET next_run_at = now()
        WHERE enabled IS TRUE AND next_run_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE scheduled_tasks
        SET owner_ref = 'metadata:source:' || (kwargs_json->>'source_id')
        WHERE system IS FALSE
          AND owner_ref IS NULL
          AND kwargs_json ? 'source_id'
          AND COALESCE(kwargs_json->>'source_id', '') <> ''
        """
    )

    op.add_column(
        "jobs",
        sa.Column("scheduled_for", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("locked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_claimed_by", "jobs", ["claimed_by"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_jobs_trigger_scheduled_for
        ON jobs (trigger_ref, scheduled_for)
        WHERE scheduled_for IS NOT NULL AND trigger_kind = 'schedule'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_jobs_trigger_scheduled_for")
    op.drop_index("ix_jobs_claimed_by", table_name="jobs")
    op.drop_column("jobs", "locked_at")
    op.drop_column("jobs", "claimed_by")
    op.drop_column("jobs", "scheduled_for")
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_owner_ref", table_name="scheduled_tasks")
    op.drop_column("scheduled_tasks", "next_run_at")
    op.drop_column("scheduled_tasks", "owner_ref")
