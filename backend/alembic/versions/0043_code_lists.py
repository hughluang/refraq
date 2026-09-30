"""Dictionaries and dictionary publish snapshots.

Revision ID: 0043_code_lists
Revises: 0042_entity_table_name_len

Inline dictionary entries are not converted. A stored ``entries`` key is
removed; the attribute must be saved again with ``dictionary_id``.
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0043_code_lists"
down_revision: Union[str, None] = "0042_entity_table_name_len"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictionaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_dictionaries_name"),
    )
    op.create_table(
        "dictionary_entries",
        sa.Column("dictionary_id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dictionary_id"],
            ["dictionaries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dictionary_id", "code", name="dictionary_entries_pkey"),
    )
    op.add_column(
        "entity_versions",
        sa.Column(
            "dictionary_snapshots",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    _strip_inline_entries()


def _strip_inline_entries() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, attributes, materialized_attributes FROM entity_versions")
    ).fetchall()
    for row in rows:
        attributes, attributes_changed = _strip(row.attributes)
        materialized, materialized_changed = _strip(row.materialized_attributes)
        if not attributes_changed and not materialized_changed:
            continue
        conn.execute(
            sa.text(
                "UPDATE entity_versions "
                "SET attributes = CAST(:attributes AS jsonb), "
                "materialized_attributes = CAST(:materialized AS jsonb) "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "attributes": json.dumps(attributes),
                "materialized": json.dumps(materialized),
            },
        )


def _strip(raw: object) -> tuple[list, bool]:
    if not isinstance(raw, list):
        return [], False
    changed = False
    cleaned: list = []
    for item in raw:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        if item.get("type") not in {"dictionary", "enumeration"}:
            cleaned.append(item)
            continue
        config = item.get("config")
        dictionary_id = None
        if isinstance(config, dict):
            dictionary_id = config.get("dictionary_id")
            if dictionary_id is None:
                dictionary_id = config.get("code_list_id")
        dirty = (
            item.get("type") != "dictionary"
            or not isinstance(config, dict)
            or "entries" in config
            or "code_list_id" in config
            or "dictionary_id" not in config
        )
        if dirty:
            changed = True
            nxt = dict(item)
            nxt["type"] = "dictionary"
            nxt["config"] = {"dictionary_id": dictionary_id}
            cleaned.append(nxt)
            continue
        cleaned.append(item)
    return cleaned, changed


def downgrade() -> None:
    op.drop_column("entity_versions", "dictionary_snapshots")
    op.drop_table("dictionary_entries")
    op.drop_table("dictionaries")
