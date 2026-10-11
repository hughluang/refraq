"""Channel run records and node executions.

Revision ID: 0057_channel_runs
Revises: 0056_system_identity
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_channel_runs"
down_revision: Union[str, None] = "0056_system_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_runs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=True),
        sa.Column("graph", postgresql.JSONB(), nullable=True),
        sa.Column("trigger_node_id", sa.String(64), nullable=False),
        sa.Column("ignore_checkpoints", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("failed_node_id", sa.String(64), nullable=True),
        sa.Column("skipped_node_ids", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_channel_runs_channel_created",
        "channel_runs",
        ["channel_id", "created_at"],
    )
    op.create_table(
        "channel_node_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("channel_runs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("output_bytes", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_channel_node_executions_job_seq",
        "channel_node_executions",
        ["job_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_node_executions_job_seq", table_name="channel_node_executions")
    op.drop_table("channel_node_executions")
    op.drop_index("ix_channel_runs_channel_created", table_name="channel_runs")
    op.drop_table("channel_runs")
