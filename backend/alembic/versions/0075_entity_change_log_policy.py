"""Change-log policy state on entity versions.

Revision ID: 0075_entity_change_log_policy
Revises: 0074_entity_version_change_log

Null means the version never entered the policy step. pending and applied
are written by a Postgres Publish.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0075_entity_change_log_policy"
down_revision: Union[str, None] = "0074_entity_version_change_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_versions",
        sa.Column("change_log_policy", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_entity_versions_change_log_policy",
        "entity_versions",
        "change_log_policy IS NULL OR change_log_policy IN ('pending', 'applied')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_entity_versions_change_log_policy",
        "entity_versions",
        type_="check",
    )
    op.drop_column("entity_versions", "change_log_policy")
