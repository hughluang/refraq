"""Batch limit, control revision, and processing contract on Model Service.

Revision ID: 0087_model_service_shared_controls
Revises: 0086_access_log_sql_fields

Existing services take a batch limit of 32. Existing purpose rows keep generation
and start at control revision 0 with the current projection contract, so shipping
this revision does not itself advance generation.

The revision id is longer than Alembic's default varchar(32) version column.
Widen that column before the stamp, or this upgrade rolls back and later
revisions never run. Downgrade leaves the wider column in place.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0087_model_service_shared_controls"
down_revision: Union[str, None] = "0086_access_log_sql_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64)"
    )
    op.add_column(
        "model_services",
        sa.Column("batch_limit", sa.Integer(), nullable=False, server_default="32"),
    )
    op.alter_column("model_services", "batch_limit", server_default=None)
    op.add_column(
        "model_service_purposes",
        sa.Column(
            "control_revision", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("model_service_purposes", "control_revision", server_default=None)
    op.add_column(
        "model_service_purposes",
        sa.Column(
            "processing_contract",
            sa.String(length=64),
            nullable=False,
            server_default="prefix-1024-l2-v1",
        ),
    )
    op.alter_column(
        "model_service_purposes", "processing_contract", server_default=None
    )


def downgrade() -> None:
    op.drop_column("model_service_purposes", "processing_contract")
    op.drop_column("model_service_purposes", "control_revision")
    op.drop_column("model_services", "batch_limit")
