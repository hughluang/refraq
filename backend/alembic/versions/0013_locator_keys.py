"""Add locator_key columns and backfill from natural keys.

Revision ID: 0013_locator_keys
Revises: 0012_catalog_joins
Create Date: 2026-08-09

Backfill uses the same percent-encoding as backend.metadata.locators.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from backend.metadata.locators import (
    format_column_locator,
    format_object_locator,
    format_source_locator,
)

revision: str = "0013_locator_keys"
down_revision: Union[str, None] = "0012_catalog_joins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("locator_key", sa.String(length=512), nullable=True))
    op.add_column(
        "catalog_objects",
        sa.Column("locator_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "catalog_columns",
        sa.Column("locator_key", sa.String(length=1024), nullable=True),
    )

    conn = op.get_bind()
    sources = conn.execute(
        sa.text("SELECT id, key, engine, kind FROM sources WHERE locator_key IS NULL")
    ).mappings().all()
    source_by_id: dict[str, dict[str, str | None]] = {}
    for row in sources:
        kind = row["kind"]
        if not (row["engine"] or "").strip() and not (kind or "").strip():
            raise RuntimeError(
                f"Source {row['id']} has empty engine and kind; cannot backfill locator"
            )
        locator = format_source_locator(
            engine=row["engine"], kind=kind or "", key=row["key"]
        )
        conn.execute(
            sa.text("UPDATE sources SET locator_key = :lk WHERE id = :id"),
            {"lk": locator, "id": row["id"]},
        )
        source_by_id[row["id"]] = {
            "key": row["key"],
            "engine": row["engine"],
            "kind": row["kind"],
        }

    all_sources = conn.execute(
        sa.text("SELECT id, key, engine, kind FROM sources")
    ).mappings().all()
    for row in all_sources:
        source_by_id[row["id"]] = {
            "key": row["key"],
            "engine": row["engine"],
            "kind": row["kind"],
        }

    orphan_objects = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n
            FROM catalog_objects o
            LEFT JOIN sources s ON s.id = o.source_id
            WHERE s.id IS NULL
            """
        )
    ).scalar_one()
    if orphan_objects:
        raise RuntimeError(
            f"Refusing locator backfill: {orphan_objects} catalog_objects lack sources"
        )

    objects = conn.execute(
        sa.text(
            """
            SELECT id, source_id, schema_name, object_type, name
            FROM catalog_objects
            WHERE locator_key IS NULL
            """
        )
    ).mappings().all()
    object_by_id: dict[str, dict[str, str]] = {}
    for row in objects:
        src = source_by_id.get(row["source_id"])
        if src is None:
            raise RuntimeError(
                f"Object {row['id']} references missing source {row['source_id']}"
            )
        kind = src["kind"] or ""
        if not (src["engine"] or "").strip() and not kind.strip():
            raise RuntimeError(
                f"Source {row['source_id']} has empty engine and kind"
            )
        locator = format_object_locator(
            engine=src["engine"],
            kind=kind,
            source_key=src["key"] or "",
            schema_name=row["schema_name"],
            object_type=row["object_type"],
            name=row["name"],
        )
        conn.execute(
            sa.text("UPDATE catalog_objects SET locator_key = :lk WHERE id = :id"),
            {"lk": locator, "id": row["id"]},
        )
        object_by_id[row["id"]] = {
            "source_id": row["source_id"],
            "schema_name": row["schema_name"],
            "object_type": row["object_type"],
            "name": row["name"],
        }

    all_objects = conn.execute(
        sa.text(
            "SELECT id, source_id, schema_name, object_type, name FROM catalog_objects"
        )
    ).mappings().all()
    for row in all_objects:
        object_by_id[row["id"]] = {
            "source_id": row["source_id"],
            "schema_name": row["schema_name"],
            "object_type": row["object_type"],
            "name": row["name"],
        }

    orphan_columns = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n
            FROM catalog_columns c
            LEFT JOIN catalog_objects o ON o.id = c.object_id
            WHERE o.id IS NULL
            """
        )
    ).scalar_one()
    if orphan_columns:
        raise RuntimeError(
            f"Refusing locator backfill: {orphan_columns} catalog_columns lack objects"
        )

    columns = conn.execute(
        sa.text(
            """
            SELECT id, object_id, name
            FROM catalog_columns
            WHERE locator_key IS NULL
            """
        )
    ).mappings().all()
    for row in columns:
        obj = object_by_id.get(row["object_id"])
        if obj is None:
            raise RuntimeError(
                f"Column {row['id']} references missing object {row['object_id']}"
            )
        src = source_by_id.get(obj["source_id"])
        if src is None:
            raise RuntimeError(
                f"Object {row['object_id']} references missing source {obj['source_id']}"
            )
        kind = src["kind"] or ""
        locator = format_column_locator(
            engine=src["engine"],
            kind=kind,
            source_key=src["key"] or "",
            schema_name=obj["schema_name"],
            object_type=obj["object_type"],
            name=obj["name"],
            column_name=row["name"],
            field_kind="column",
        )
        conn.execute(
            sa.text("UPDATE catalog_columns SET locator_key = :lk WHERE id = :id"),
            {"lk": locator, "id": row["id"]},
        )

    op.alter_column("sources", "locator_key", existing_type=sa.String(length=512), nullable=False)
    op.alter_column(
        "catalog_objects",
        "locator_key",
        existing_type=sa.String(length=1024),
        nullable=False,
    )
    op.alter_column(
        "catalog_columns",
        "locator_key",
        existing_type=sa.String(length=1024),
        nullable=False,
    )

    op.create_index("ix_sources_locator_key", "sources", ["locator_key"], unique=True)
    op.create_index(
        "ix_catalog_objects_locator_key",
        "catalog_objects",
        ["locator_key"],
        unique=True,
    )
    op.create_index(
        "ix_catalog_columns_locator_key",
        "catalog_columns",
        ["locator_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_columns_locator_key", table_name="catalog_columns")
    op.drop_index("ix_catalog_objects_locator_key", table_name="catalog_objects")
    op.drop_index("ix_sources_locator_key", table_name="sources")
    op.drop_column("catalog_columns", "locator_key")
    op.drop_column("catalog_objects", "locator_key")
    op.drop_column("sources", "locator_key")
