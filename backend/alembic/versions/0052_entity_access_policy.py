"""Entity access policy: ladders, profiles, grants, restrictions, bindings, log.

Revision ID: 0052_entity_access_policy
Revises: 0051_user_groups_subject_attrs

Profile view bindings are stored here. This migration does not create views
in the entity database.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_entity_access_policy"
down_revision: Union[str, None] = "0051_user_groups_subject_attrs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_presentation_ladders",
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attribute_id", sa.String(64), primary_key=True),
        sa.Column("levels", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "entity_access_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(63), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_id", "key", name="uq_entity_access_profiles_key"),
    )
    op.create_table(
        "entity_access_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(64), sa.ForeignKey("entity_access_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("row_rule", postgresql.JSONB(), nullable=True),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_entity_access_grants_entity", "entity_access_grants", ["entity_id", "created_at", "id"])
    op.create_table(
        "entity_access_restrictions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("applies_to", postgresql.JSONB(), nullable=False),
        sa.Column("row_rule", postgresql.JSONB(), nullable=True),
        sa.Column("deny_columns", postgresql.JSONB(), nullable=False),
        sa.Column("ceilings", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_entity_access_restrictions_entity",
        "entity_access_restrictions",
        ["entity_id", "created_at", "id"],
    )
    op.create_table(
        "entity_access_revisions",
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "entity_profile_view_bindings",
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("business_entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("shape_key", sa.String(64), primary_key=True),
        sa.Column("head_version_id", sa.String(64), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("combo_key", sa.Text(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("view_name", sa.String(63), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("ddl_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
    )
    op.create_table(
        "entity_access_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("pat_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("verb", sa.String(32), nullable=False),
        sa.Column("effective_grant_ids", postgresql.JSONB(), nullable=False),
        sa.Column("narrowing", postgresql.JSONB(), nullable=True),
        sa.Column("view_name", sa.String(63), nullable=True),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("outcome_code", sa.String(64), nullable=False),
        sa.Column("preview_subject_user_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_entity_access_logs_created_at", "entity_access_logs", ["created_at"])
    op.create_index("ix_entity_access_logs_entity_id", "entity_access_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_access_logs_entity_id", table_name="entity_access_logs")
    op.drop_index("ix_entity_access_logs_created_at", table_name="entity_access_logs")
    op.drop_table("entity_access_logs")
    op.drop_table("entity_profile_view_bindings")
    op.drop_table("entity_access_revisions")
    op.drop_index("ix_entity_access_restrictions_entity", table_name="entity_access_restrictions")
    op.drop_table("entity_access_restrictions")
    op.drop_index("ix_entity_access_grants_entity", table_name="entity_access_grants")
    op.drop_table("entity_access_grants")
    op.drop_table("entity_access_profiles")
    op.drop_table("entity_presentation_ladders")
