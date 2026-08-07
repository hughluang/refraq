"""Embed reachability on sources; drop connections (with data backfill).

Revision ID: 0010_source_owns_access
Revises: 0006_user_pats_deleted_at
Create Date: 2026-08-07
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_source_owns_access"
down_revision: Union[str, None] = "0006_user_pats_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("engine", sa.String(length=64), nullable=True))
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

    _backfill_from_connections()

    op.drop_column("catalog_objects", "collected_from_connection_id")
    op.drop_table("connections")


def _backfill_from_connections() -> None:
    """Copy Connection reachability onto Source; rewrite secret JSON → password."""
    from backend.core.secrets import (
        SecretsDecryptError,
        SecretsMasterKeyMissing,
        decrypt_secret,
        encrypt_secret,
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT c.source_id, c.engine, c.host, c.port,
                   c.secret_ciphertext, c.secret_updated_at
            FROM connections c
            """
        )
    ).mappings().all()
    if not rows:
        return

    if any(r["secret_ciphertext"] for r in rows):
        try:
            encrypt_secret("__migration_probe__")
        except SecretsMasterKeyMissing as exc:
            raise RuntimeError(
                "REFRAQ_SECRETS_MASTER_KEY is required to migrate Connection secrets "
                "onto Sources"
            ) from exc

    sources = sa.table(
        "sources",
        sa.column("id", sa.String),
        sa.column("engine", sa.String),
        sa.column(
            "access",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        ),
        sa.column("secret_ciphertext", sa.Text),
        sa.column("secret_updated_at", sa.DateTime),
    )

    for row in rows:
        access: dict[str, Any] | None
        new_cipher: str | None
        secret_updated_at = row["secret_updated_at"]

        if row["secret_ciphertext"]:
            try:
                payload = json.loads(decrypt_secret(row["secret_ciphertext"]))
            except (SecretsDecryptError, json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError(
                    f"Failed to migrate secret for source_id={row['source_id']}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"Connection secret for source_id={row['source_id']} "
                    "is not a JSON object"
                )
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
            if not username or not password:
                raise RuntimeError(
                    f"Connection secret for source_id={row['source_id']} "
                    "missing username or password"
                )
            access = {
                "host": row["host"],
                "port": row["port"],
                "username": username,
            }
            new_cipher = encrypt_secret(password)
        else:
            # No credentials: keep engine only; operator must set access + secret.
            access = None
            new_cipher = None
            secret_updated_at = None

        bind.execute(
            sources.update()
            .where(sources.c.id == row["source_id"])
            .values(
                engine=row["engine"],
                access=access,
                secret_ciphertext=new_cipher,
                secret_updated_at=secret_updated_at,
            )
        )


def downgrade() -> None:
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
    op.add_column(
        "catalog_objects",
        sa.Column("collected_from_connection_id", sa.String(length=64), nullable=True),
    )
    op.drop_column("sources", "secret_updated_at")
    op.drop_column("sources", "secret_ciphertext")
    op.drop_column("sources", "access")
    op.drop_column("sources", "engine")
