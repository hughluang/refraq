"""Execution input and container rounds.

Revision ID: 0069_execution_input_rounds
Revises: 0068_retire_business_domain
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069_execution_input_rounds"
down_revision: Union[str, None] = "0068_retire_business_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_node_executions",
        sa.Column("input", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "channel_node_executions",
        sa.Column("input_totals", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "channel_container_rounds",
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("channel_runs.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("container_seq", sa.Integer(), primary_key=True),
        sa.Column("round", sa.Integer(), primary_key=True),
        sa.Column("step", postgresql.JSONB(), nullable=False),
        sa.Column("step_totals", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_container_rounds")
    op.drop_column("channel_node_executions", "input_totals")
    op.drop_column("channel_node_executions", "input")
