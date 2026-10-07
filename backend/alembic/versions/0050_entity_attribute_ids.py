"""Assign a stable attribute_id to every published Entity attribute.

Revision ID: 0050_entity_attribute_ids
Revises: 0049_entity_reference_snapshots

Published versions are walked in version order per Entity. An attribute takes
the id of the same-named attribute in the previous published version, or a new
id. Unpublished and publishing versions store no id; publish assigns one.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0050_entity_attribute_ids"
down_revision: Union[str, None] = "0049_entity_reference_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_versions = sa.table(
    "entity_versions",
    sa.column("id", sa.String),
    sa.column("entity_id", sa.String),
    sa.column("version", sa.Integer),
    sa.column("publish_status", sa.String),
    sa.column("attributes", JSONB),
    sa.column("materialized_attributes", JSONB),
)


def _new_attribute_id() -> str:
    return f"att_{uuid.uuid4().hex[:12]}"


def assign_ids(
    rows: list[dict[str, Any]],
    new_id: Any = _new_attribute_id,
) -> list[dict[str, Any]]:
    """Return rows with ids stamped; ``rows`` is one Entity's versions in any order."""
    carried: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item["version"], item["id"])):
        if row["publish_status"] != "published":
            out.append(row)
            continue
        ids: dict[str, str] = {}
        attributes = []
        for attr in row["attributes"]:
            name = str(attr["name"])
            attribute_id = attr.get("attribute_id") or carried.get(name) or new_id()
            ids[name] = attribute_id
            attributes.append({**attr, "attribute_id": attribute_id})
        materialized = []
        for attr in row["materialized_attributes"]:
            name = str(attr["name"])
            if name not in ids:
                ids[name] = attr.get("attribute_id") or carried.get(name) or new_id()
            materialized.append({**attr, "attribute_id": ids[name]})
        carried = ids
        out.append(
            {**row, "attributes": attributes, "materialized_attributes": materialized}
        )
    return out


def upgrade() -> None:
    bind = op.get_bind()
    rows = [
        dict(item)
        for item in bind.execute(
            sa.select(
                _versions.c.id,
                _versions.c.entity_id,
                _versions.c.version,
                _versions.c.publish_status,
                _versions.c.attributes,
                _versions.c.materialized_attributes,
            )
        ).mappings()
    ]
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_entity.setdefault(row["entity_id"], []).append(row)
    for group in by_entity.values():
        for row in assign_ids(group):
            if row["publish_status"] != "published":
                continue
            bind.execute(
                _versions.update()
                .where(_versions.c.id == row["id"])
                .values(
                    attributes=row["attributes"],
                    materialized_attributes=row["materialized_attributes"],
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    for column in ("attributes", "materialized_attributes"):
        bind.execute(
            sa.text(
                f"UPDATE entity_versions SET {column} = COALESCE(("
                f"SELECT jsonb_agg(item - 'attribute_id' ORDER BY ord) "
                f"FROM jsonb_array_elements({column}) WITH ORDINALITY AS t(item, ord)"
                f"), '[]'::jsonb)"
            )
        )
