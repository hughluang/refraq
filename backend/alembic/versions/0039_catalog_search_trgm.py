"""pg_trgm GIN indexes for Catalog Search ILIKE (ADR 0041).

Revision ID: 0039_catalog_search_trgm
Revises: 0038_model_services
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0039_catalog_search_trgm"
down_revision: Union[str, None] = "0038_model_services"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    (
        "ix_catalog_objects_name_trgm",
        "catalog_objects",
        "name",
    ),
    (
        "ix_catalog_objects_locator_key_trgm",
        "catalog_objects",
        "locator_key",
    ),
    (
        "ix_catalog_objects_schema_name_trgm",
        "catalog_objects",
        "schema_name",
    ),
    (
        "ix_catalog_objects_business_name_trgm",
        "catalog_objects",
        "business_name",
    ),
    (
        "ix_catalog_objects_business_description_trgm",
        "catalog_objects",
        "business_description",
    ),
    (
        "ix_catalog_columns_name_trgm",
        "catalog_columns",
        "name",
    ),
    (
        "ix_catalog_columns_locator_key_trgm",
        "catalog_columns",
        "locator_key",
    ),
    (
        "ix_catalog_columns_business_name_trgm",
        "catalog_columns",
        "business_name",
    ),
    (
        "ix_catalog_columns_business_description_trgm",
        "catalog_columns",
        "business_description",
    ),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _INDEXES:
        op.execute(
            f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)"
        )


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
