"""Embed encrypted access blob on sources; drop plaintext access + secret column.

Revision ID: 0011_encrypted_access_blob
Revises: 0010_source_owns_access
Create Date: 2026-08-07

No data migration: operators must re-enter connectivity (ADR 0011).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_encrypted_access_blob"
down_revision: Union[str, None] = "0010_source_owns_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("access_ciphertext", sa.Text(), nullable=True))
    op.add_column(
        "sources", sa.Column("access_updated_at", sa.DateTime(), nullable=True)
    )
    op.drop_column("sources", "access")
    op.drop_column("sources", "secret_ciphertext")
    op.drop_column("sources", "secret_updated_at")


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    op.add_column(
        "sources",
        sa.Column(
            "access",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column("sources", sa.Column("secret_ciphertext", sa.Text(), nullable=True))
    op.add_column(
        "sources", sa.Column("secret_updated_at", sa.DateTime(), nullable=True)
    )
    op.drop_column("sources", "access_updated_at")
    op.drop_column("sources", "access_ciphertext")
