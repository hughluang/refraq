"""Add sources, connections, and catalog tables for Slice A.

Revision ID: 0004_sources_catalog
Revises: 0003_jobs_generic_input
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_sources_catalog"
down_revision: Union[str, None] = "0003_jobs_generic_input"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("database_name", sa.String(length=256), nullable=True),
        sa.Column("schema_filter", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sources_key", "sources", ["key"], unique=True)

    op.create_table(
        "connections",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=512), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", name="uq_connections_source_id"),
    )

    op.create_table(
        "catalog_objects",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("collected_from_connection_id", sa.String(length=64), nullable=True),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("ddl", sa.Text(), nullable=True),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("business_name", sa.String(length=256), nullable=True),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column("last_structure_job_id", sa.String(length=64), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_id",
            "schema_name",
            "name",
            "object_type",
            name="uq_catalog_objects_natural_key",
        ),
    )
    op.create_index("ix_catalog_objects_source_id", "catalog_objects", ["source_id"])

    op.create_table(
        "catalog_columns",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(length=256), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("business_name", sa.String(length=256), nullable=True),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id"], ["catalog_objects.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "object_id",
            "name",
            name="uq_catalog_columns_object_name",
        ),
    )
    op.create_index("ix_catalog_columns_object_id", "catalog_columns", ["object_id"])


def downgrade() -> None:
    op.drop_index("ix_catalog_columns_object_id", table_name="catalog_columns")
    op.drop_table("catalog_columns")
    op.drop_index("ix_catalog_objects_source_id", table_name="catalog_objects")
    op.drop_table("catalog_objects")
    op.drop_table("connections")
    op.drop_index("ix_sources_key", table_name="sources")
    op.drop_table("sources")
