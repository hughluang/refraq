"""Identity providers, external bindings, and pending federated identities.

Revision ID: 0033_federation
Revises: 0032_join_changes
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_federation"
down_revision: Union[str, None] = "0032_join_changes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.create_table(
        "identity_providers",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issuer", name="uq_identity_providers_issuer"),
    )
    op.create_table(
        "user_external_identities",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["identity_providers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
        sa.UniqueConstraint("user_id", name="uq_external_identity_user"),
    )
    op.create_table(
        "pending_federated_identities",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("account_hint", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("groups", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("admission_reason", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["identity_providers.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("issuer", "subject", name="uq_pending_federation_issuer_subject"),
    )


def downgrade() -> None:
    op.drop_table("pending_federated_identities")
    op.drop_table("user_external_identities")
    op.drop_table("identity_providers")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
