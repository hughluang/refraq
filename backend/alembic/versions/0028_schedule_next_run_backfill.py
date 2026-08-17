"""Repair 0027 next_run_at backfill that copied last_run_at.

Revision ID: 0028_schedule_next_run_backfill
Revises: 0027_schedule_foundation
Create Date: 2026-08-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0028_schedule_next_run_backfill"
down_revision: Union[str, None] = "0027_schedule_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0027 originally set next_run_at = COALESCE(last_run_at, now()). A past
    # last_run_at made every enabled row due at upgrade. Rows still showing
    # that fingerprint (next_run_at = last_run_at) get now(), matching 0027's
    # intended backfill. Legitimate next = last + interval is untouched.
    op.execute(
        """
        UPDATE scheduled_tasks
        SET next_run_at = now()
        WHERE enabled IS TRUE
          AND next_run_at IS NOT NULL
          AND last_run_at IS NOT NULL
          AND next_run_at = last_run_at
        """
    )


def downgrade() -> None:
    pass
