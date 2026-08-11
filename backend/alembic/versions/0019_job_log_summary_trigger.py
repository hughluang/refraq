"""Job log_body, summary, and trigger fields.

Revision ID: 0019_job_log_summary_trigger
Revises: 0018_business_domain
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_job_log_summary_trigger"
down_revision: Union[str, None] = "0018_business_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("summary", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "jobs",
        sa.Column("trigger_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("trigger_ref", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("log_body", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "jobs",
        sa.Column("log_updated_at", sa.DateTime(), nullable=True),
    )
    op.alter_column("jobs", "summary", server_default=None)
    op.alter_column("jobs", "log_body", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "log_updated_at")
    op.drop_column("jobs", "log_body")
    op.drop_column("jobs", "trigger_ref")
    op.drop_column("jobs", "trigger_kind")
    op.drop_column("jobs", "summary")
