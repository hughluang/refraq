"""Move Source catalog scope into encrypted access; drop top-level columns.

Revision ID: 0020_catalog_scope_in_access
Revises: 0019_job_log_summary_trigger
Create Date: 2026-08-12
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_catalog_scope_in_access"
down_revision: Union[str, None] = "0019_job_log_summary_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, engine, database_name, schema_filter, access_ciphertext
            FROM sources
            """
        )
    ).mappings().all()

    needs_crypto = any(
        (r["database_name"] or r["schema_filter"]) and r["access_ciphertext"]
        for r in rows
    )
    if needs_crypto or any(
        (r["database_name"] or r["schema_filter"]) and not r["access_ciphertext"]
        for r in rows
    ):
        from backend.core.secrets import SecretsMasterKeyMissing, encrypt_secret

        try:
            encrypt_secret("__migration_probe__")
        except SecretsMasterKeyMissing as exc:
            raise RuntimeError(
                "REFRAQ_SECRETS_MASTER_KEY is required to merge catalog scope "
                "into Source access blobs"
            ) from exc

    for row in rows:
        _merge_scope_into_access(bind, row)

    op.drop_column("sources", "database_name")
    op.drop_column("sources", "schema_filter")


def _merge_scope_into_access(bind: Any, row: Any) -> None:
    from backend.core.secrets import SecretsDecryptError, decrypt_secret, encrypt_secret
    from backend.metadata.sources.access import validate_access

    source_id = row["id"]
    engine = row["engine"]
    database_name = row["database_name"]
    schema_filter = row["schema_filter"]
    ciphertext = row["access_ciphertext"]

    has_scope = bool(database_name or schema_filter)
    if not has_scope:
        return

    if not ciphertext or not engine:
        raise RuntimeError(
            f"Source id={source_id} has catalog scope columns but missing "
            "engine/access_ciphertext; refuse to drop scope silently"
        )

    try:
        raw = decrypt_secret(ciphertext)
        access = json.loads(raw)
    except (SecretsDecryptError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            f"Failed to decrypt/parse access for source id={source_id}: {exc}"
        ) from exc
    if not isinstance(access, dict):
        raise RuntimeError(
            f"Access blob for source id={source_id} is not a JSON object"
        )

    if engine == "oracle":
        if database_name and "service_name" not in access:
            access["service_name"] = database_name
        if schema_filter and "owner" not in access:
            access["owner"] = schema_filter
    else:
        if database_name and "database" not in access:
            access["database"] = database_name
        if schema_filter and "schema" not in access:
            access["schema"] = schema_filter

    try:
        access = validate_access(engine, access)
    except Exception as exc:  # noqa: BLE001 — surface migration blocker clearly
        raise RuntimeError(
            f"Merged access for source id={source_id} failed Spec validation: {exc}"
        ) from exc

    new_cipher = encrypt_secret(
        json.dumps(access, separators=(",", ":"), ensure_ascii=False)
    )
    bind.execute(
        sa.text(
            """
            UPDATE sources
            SET access_ciphertext = :cipher
            WHERE id = :id
            """
        ),
        {"cipher": new_cipher, "id": source_id},
    )


def downgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("database_name", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("schema_filter", sa.String(length=256), nullable=True),
    )
