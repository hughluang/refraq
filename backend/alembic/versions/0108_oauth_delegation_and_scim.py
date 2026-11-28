"""Add OAuth delegation clients, SCIM tokens/group bindings, and soft-deprovision column."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0108_oauth_delegation_and_scim"
down_revision = "0107_subchannel_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_external_identities",
        sa.Column("scim_deprovisioned_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "provider_id",
            sa.String(64),
            sa.ForeignKey("identity_providers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("token_endpoint_auth_method", sa.String(32), nullable=False),
        sa.Column("jwks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("jwks_uri", sa.String(512), nullable=True),
        sa.Column("secret_hash", sa.String(64), nullable=True),
        sa.Column("secret_prefix", sa.String(32), nullable=True),
        sa.Column("allowed_grant_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "allowed_subject_audiences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("allowed_surfaces", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_ttl_sec", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True)
    op.create_index("ix_oauth_clients_provider_id", "oauth_clients", ["provider_id"])

    op.create_table(
        "scim_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(64),
            sa.ForeignKey("identity_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(32), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scim_tokens_provider_id", "scim_tokens", ["provider_id"])

    op.create_table(
        "scim_group_bindings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(64),
            sa.ForeignKey("identity_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column(
            "group_id",
            sa.String(64),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", "external_id", name="uq_scim_group_provider_external"),
        sa.UniqueConstraint("provider_id", "group_id", name="uq_scim_group_provider_group"),
    )
    op.create_index("ix_scim_group_bindings_provider_id", "scim_group_bindings", ["provider_id"])


def downgrade():
    op.drop_index("ix_scim_group_bindings_provider_id", table_name="scim_group_bindings")
    op.drop_table("scim_group_bindings")
    op.drop_index("ix_scim_tokens_provider_id", table_name="scim_tokens")
    op.drop_table("scim_tokens")
    op.drop_index("ix_oauth_clients_provider_id", table_name="oauth_clients")
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
    op.drop_column("user_external_identities", "scim_deprovisioned_at")
