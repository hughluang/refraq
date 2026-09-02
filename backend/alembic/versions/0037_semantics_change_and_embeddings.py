"""Semantics Change ledger and catalog embeddings.

Revision ID: 0037_semantics_change_embed
Revises: 0036_object_identity_text
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_semantics_change_embed"
down_revision: Union[str, None] = "0036_object_identity_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_semantics_changes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("column_id", sa.String(length=64), nullable=True),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("semantic_source", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["catalog_objects.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_catalog_semantics_changes_object_id",
        "catalog_semantics_changes",
        ["object_id"],
    )
    op.create_index(
        "ix_catalog_semantics_changes_column_id",
        "catalog_semantics_changes",
        ["column_id"],
    )
    op.create_table(
        "catalog_embeddings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("locator_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "target_id", name="uq_catalog_embeddings_kind_target"),
    )


def downgrade() -> None:
    op.drop_table("catalog_embeddings")
    op.drop_index(
        "ix_catalog_semantics_changes_column_id",
        table_name="catalog_semantics_changes",
    )
    op.drop_index(
        "ix_catalog_semantics_changes_object_id",
        table_name="catalog_semantics_changes",
    )
    op.drop_table("catalog_semantics_changes")
