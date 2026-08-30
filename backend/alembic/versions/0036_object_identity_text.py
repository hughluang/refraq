"""Store Catalog Object identity as Text (not identifier width).

Revision ID: 0036_object_identity_text
Revises: 0035_branding_show_logo

Object `name` is the identity string (PostgreSQL routines may include the
identity argument list). `locator_key` is derived from that string.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_object_identity_text"
down_revision: Union[str, None] = "0035_branding_show_logo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "catalog_objects",
        "name",
        existing_type=sa.String(length=256),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "catalog_objects",
        "locator_key",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "catalog_objects",
        "locator_key",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
    op.alter_column(
        "catalog_objects",
        "name",
        existing_type=sa.Text(),
        type_=sa.String(length=256),
        existing_nullable=False,
    )
