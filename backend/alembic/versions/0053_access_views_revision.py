"""Record which policy revision the profile views were built for.

Revision ID: 0053_access_views_revision
Revises: 0052_entity_access_policy

The policy revision advances when the policy is saved. views_revision advances
only after the entity database has the matching profile views.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_access_views_revision"
down_revision: Union[str, None] = "0052_entity_access_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_access_revisions",
        sa.Column(
            "views_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("entity_access_revisions", "views_revision")
