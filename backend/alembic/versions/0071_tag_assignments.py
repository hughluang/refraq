"""Tag assignments and per-subject revisions.

Revision ID: 0071_tag_assignments
Revises: 0070_tags
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_tag_assignments"
down_revision: Union[str, None] = "0070_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tag_assignments",
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], name="fk_tag_assignments_tag_id"),
        sa.PrimaryKeyConstraint(
            "subject_kind", "subject_id", "tag_id", name="pk_tag_assignments"
        ),
        sa.CheckConstraint(
            "subject_kind IN ('entity', 'channel')",
            name="ck_tag_assignments_kind",
        ),
    )
    op.create_index("ix_tag_assignments_tag_id", "tag_assignments", ["tag_id"])
    op.create_index(
        "ix_tag_assignments_kind_tag",
        "tag_assignments",
        ["subject_kind", "tag_id"],
    )
    op.create_table(
        "tag_subject_revisions",
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "subject_kind", "subject_id", name="pk_tag_subject_revisions"
        ),
        sa.CheckConstraint(
            "subject_kind IN ('entity', 'channel')",
            name="ck_tag_subject_revisions_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("tag_subject_revisions")
    op.drop_index("ix_tag_assignments_kind_tag", table_name="tag_assignments")
    op.drop_index("ix_tag_assignments_tag_id", table_name="tag_assignments")
    op.drop_table("tag_assignments")
