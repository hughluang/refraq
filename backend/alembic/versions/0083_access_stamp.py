"""Opaque access stamp on Jobs and Scheduled Tasks.

Revision ID: 0083_access_stamp
Revises: 0082_source_memberships

Backfill copies a non-empty Source id already stored in Job input or schedule
kwargs. It does not copy owner_ref. Other Job kinds stay null.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0083_access_stamp"
down_revision: Union[str, None] = "0082_source_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("access_stamp", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_jobs_access_stamp", "jobs", ["access_stamp"])
    op.add_column(
        "scheduled_tasks",
        sa.Column("access_stamp", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_scheduled_tasks_access_stamp", "scheduled_tasks", ["access_stamp"]
    )
    op.execute(
        """
        UPDATE jobs
        SET access_stamp = input->>'source_id'
        WHERE kind IN ('structure', 'join_detection')
          AND COALESCE(input->>'source_id', '') <> ''
        """
    )
    op.execute(
        """
        UPDATE scheduled_tasks
        SET access_stamp = kwargs_json->>'source_id'
        WHERE COALESCE(kwargs_json->>'source_id', '') <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_access_stamp", table_name="scheduled_tasks")
    op.drop_column("scheduled_tasks", "access_stamp")
    op.drop_index("ix_jobs_access_stamp", table_name="jobs")
    op.drop_column("jobs", "access_stamp")
