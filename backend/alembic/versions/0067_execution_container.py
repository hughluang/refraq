"""Container round on a node execution.

Revision ID: 0067_execution_container
Revises: 0066_channel_datasets
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0067_execution_container"
down_revision: Union[str, None] = "0066_channel_datasets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_node_executions",
        sa.Column("container_seq", sa.Integer(), nullable=True),
    )
    op.add_column(
        "channel_node_executions",
        sa.Column("round", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_node_executions", "round")
    op.drop_column("channel_node_executions", "container_seq")
