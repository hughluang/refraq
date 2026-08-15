"""Point structure schedules at the source_jobs minting task.

Revision ID: 0026_structure_enqueue_task_name
Revises: 0025_type_mappings
Create Date: 2026-08-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0026_structure_enqueue_task_name"
down_revision: Union[str, None] = "0025_type_mappings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_NAME = "backend.metadata.tasks.enqueue_scheduled_structure"
_NEW_NAME = "backend.metadata.source_jobs.fire_scheduled_structure"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE scheduled_tasks
        SET task_name = '{_NEW_NAME}'
        WHERE task_name = '{_OLD_NAME}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE scheduled_tasks
        SET task_name = '{_OLD_NAME}'
        WHERE task_name = '{_NEW_NAME}'
        """
    )
