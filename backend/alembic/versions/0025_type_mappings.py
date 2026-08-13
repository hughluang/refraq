"""Type Mapping entity.

Revision ID: 0025_type_mappings
Revises: 0024_structure_diff_job_result
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_type_mappings"
down_revision: Union[str, None] = "0024_structure_diff_job_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "type_mappings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("native_type", sa.String(length=256), nullable=False),
        sa.Column("normalized_type", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("engine", "native_type", name="uq_type_mappings_engine_native"),
    )
    op.create_index("ix_type_mappings_engine", "type_mappings", ["engine"])


def downgrade() -> None:
    op.drop_index("ix_type_mappings_engine", table_name="type_mappings")
    op.drop_table("type_mappings")
