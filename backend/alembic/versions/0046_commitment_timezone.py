"""Rename schedule timezone to the commitment zone and fold the site parameter.

Revision ID: 0046_commitment_timezone
Revises: 0045_schedule_traits

scheduled_tasks.schedule_timezone becomes commitment_timezone. Stored
next_run_at values are not rewritten: the column records which zone produced
that Instant.

Cron rows that share one current zone id (aliases included) initialize
system_parameters.schedule_timezone when that key is absent. UTC is source
seed; any other single id is source user so reset still restores the product
seed. No cron rows leave the key absent for seed occupy. Several zones, or a
zone that is not a current id or alias, fail the migration. Interval rows do
not vote.

users.display_timezone is rewritten to the current IANA id; unknown values
become null (follow browser).
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_commitment_timezone"
down_revision: Union[str, None] = "0045_schedule_traits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "scheduled_tasks",
        "schedule_timezone",
        new_column_name="commitment_timezone",
    )
    from backend.core.time import utc_now
    from backend.core.time_zones import canonical_zone_id
    from backend.worker.commitment_fold import parameter_row_for_commitment_zones

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, display_timezone FROM users WHERE display_timezone IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        canon = canonical_zone_id(row.display_timezone)
        if canon == row.display_timezone:
            continue
        bind.execute(
            sa.text("UPDATE users SET display_timezone = :tz WHERE id = :id"),
            {"tz": canon, "id": row.id},
        )

    cron_zones = [
        row.commitment_timezone
        for row in bind.execute(
            sa.text(
                "SELECT commitment_timezone FROM scheduled_tasks "
                "WHERE cron IS NOT NULL AND btrim(cron) <> '' "
                "AND interval_seconds IS NULL"
            )
        ).fetchall()
    ]
    present = bind.execute(
        sa.text("SELECT 1 FROM system_parameters WHERE key = 'schedule_timezone'")
    ).first()
    folded = parameter_row_for_commitment_zones(
        cron_zones, parameter_present=present is not None
    )
    if folded is None:
        return
    zone, source = folded
    bind.execute(
        sa.text(
            "INSERT INTO system_parameters "
            "(key, value, previous_value, source, updated_at, updated_by_user_id) "
            "VALUES ("
            "'schedule_timezone', CAST(:value AS jsonb), NULL, "
            ":source, :updated_at, NULL)"
        ),
        {"value": json.dumps(zone), "source": source, "updated_at": utc_now()},
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM system_parameters WHERE key = 'schedule_timezone'"))
    op.alter_column(
        "scheduled_tasks",
        "commitment_timezone",
        new_column_name="schedule_timezone",
    )
