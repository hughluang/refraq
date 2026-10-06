"""Store the Business Key snapshot for each Entity Reference.

Revision ID: 0049_entity_reference_snapshots
Revises: 0048_schedule_start_at

Existing versions have no reference snapshot. A head that declares a
reference is refused with ENTITY_NOT_SERVING until the next publish writes one.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0049_entity_reference_snapshots"
down_revision: Union[str, None] = "0048_schedule_start_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_versions",
        sa.Column(
            "reference_snapshots",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("entity_versions", "reference_snapshots", server_default=None)


def downgrade() -> None:
    op.drop_column("entity_versions", "reference_snapshots")
