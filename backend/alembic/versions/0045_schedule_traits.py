"""Split Scheduled Task system into independent traits.

Revision ID: 0045_schedule_traits
Revises: 0044_model_service_timeout

hidden, locked, undeletable, and store_only replace the single system flag.
The site catalog-embed schedule is seeded as undeletable only.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_schedule_traits"
down_revision: Union[str, None] = "0044_model_service_timeout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "undeletable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "store_only", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute(
        """
        UPDATE scheduled_tasks
        SET hidden = system,
            locked = system,
            undeletable = system,
            store_only = system
        """
    )
    op.drop_column("scheduled_tasks", "system")
    op.execute(
        """
        INSERT INTO scheduled_tasks (
            id, key, name, enabled, interval_seconds, cron, schedule_timezone,
            running_timeout_sec, task_name, args_json, kwargs_json,
            hidden, locked, undeletable, store_only, owner_ref,
            last_run_at, next_run_at, created_at, updated_at
        )
        SELECT
            'sched_catalog_embed_site',
            'catalog_embed:site',
            'catalog embed',
            true,
            NULL,
            '0 3 * * *',
            'UTC',
            NULL,
            'backend.metadata.catalog_embed_jobs.schedule.fire_scheduled_catalog_embed',
            '[]'::jsonb,
            '{"schedule_id": "sched_catalog_embed_site"}'::jsonb,
            false,
            false,
            true,
            false,
            'admin:model_services:embedding',
            now(),
            now(),
            now(),
            now()
        WHERE NOT EXISTS (
            SELECT 1 FROM scheduled_tasks WHERE key = 'catalog_embed:site'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_tasks WHERE key = 'catalog_embed:site'")
    op.add_column(
        "scheduled_tasks",
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE scheduled_tasks
        SET system = (hidden AND locked AND undeletable AND store_only)
        """
    )
    op.drop_column("scheduled_tasks", "store_only")
    op.drop_column("scheduled_tasks", "undeletable")
    op.drop_column("scheduled_tasks", "locked")
    op.drop_column("scheduled_tasks", "hidden")
