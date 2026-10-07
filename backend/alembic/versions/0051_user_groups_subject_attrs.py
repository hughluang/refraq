"""User Groups, membership, and Subject Attribute definitions and values.

Revision ID: 0051_user_groups_subject_attrs
Revises: 0050_entity_attribute_ids

Subject Attribute values are keyed by (subject_type, subject_id) without a
foreign key: the subject is a User or a User Group.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_user_groups_subject_attrs"
down_revision: Union[str, None] = "0050_entity_attribute_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_groups",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_group_members",
        sa.Column(
            "group_id",
            sa.String(64),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_group_members_user_id", "user_group_members", ["user_id"]
    )
    op.create_table(
        "subject_attribute_defs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("dictionary_id", sa.String(64), nullable=True),
        sa.Column("multi_value", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "subject_attribute_values",
        sa.Column(
            "definition_id",
            sa.String(64),
            sa.ForeignKey("subject_attribute_defs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("subject_type", sa.String(16), primary_key=True),
        sa.Column("subject_id", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(256), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_subject_attribute_values_subject",
        "subject_attribute_values",
        ["subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subject_attribute_values_subject", table_name="subject_attribute_values"
    )
    op.drop_table("subject_attribute_values")
    op.drop_table("subject_attribute_defs")
    op.drop_index("ix_user_group_members_user_id", table_name="user_group_members")
    op.drop_table("user_group_members")
    op.drop_table("user_groups")
