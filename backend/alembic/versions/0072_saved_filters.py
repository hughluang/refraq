"""Saved filters and the filter a user returns to on each list.

Revision ID: 0072_saved_filters
Revises: 0071_tag_assignments
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072_saved_filters"
down_revision: Union[str, None] = "0071_tag_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("list", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_key", sa.String(length=512), nullable=False),
        sa.Column("query", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "list IN ('entities', 'channels')",
            name="ck_saved_filters_list",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_saved_filters_user_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "list",
            "name_key",
            name="uq_saved_filters_user_list_name",
        ),
    )
    op.create_index(
        "ix_saved_filters_user_list",
        "saved_filters",
        ["user_id", "list"],
    )
    op.create_table(
        "saved_filter_defaults",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("list", sa.String(length=16), nullable=False),
        sa.Column("saved_filter_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "list IN ('entities', 'channels')",
            name="ck_saved_filter_defaults_list",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_saved_filter_defaults_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["saved_filter_id"],
            ["saved_filters.id"],
            ondelete="CASCADE",
            name="fk_saved_filter_defaults_filter_id",
        ),
        sa.PrimaryKeyConstraint("user_id", "list", name="pk_saved_filter_defaults"),
    )


def downgrade() -> None:
    op.drop_table("saved_filter_defaults")
    op.drop_index("ix_saved_filters_user_list", table_name="saved_filters")
    op.drop_table("saved_filters")
