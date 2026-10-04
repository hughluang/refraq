"""Index jobs by trigger for recent-run lookups.

Revision ID: 0047_jobs_trigger_index
Revises: 0046_commitment_timezone
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0047_jobs_trigger_index"
down_revision: Union[str, None] = "0046_commitment_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_trigger",
        "jobs",
        ["trigger_kind", "trigger_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_trigger", table_name="jobs")
