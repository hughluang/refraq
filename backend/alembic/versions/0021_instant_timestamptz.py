"""Convert Instant columns to timestamptz (historical naive = UTC).

Revision ID: 0021_instant_timestamptz
Revises: 0020_catalog_scope_in_access
Create Date: 2026-08-12
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0021_instant_timestamptz"
down_revision: Union[str, None] = "0020_catalog_scope_in_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Absolute-moment columns previously stored as timestamp without time zone via utcnow.
_INSTANT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "last_login_at"),
    ("users", "created_at"),
    ("user_pats", "expires_at"),
    ("user_pats", "revoked_at"),
    ("user_pats", "deleted_at"),
    ("user_pats", "created_at"),
    ("user_pats", "last_used_at"),
    ("audit_events", "created_at"),
    ("jobs", "log_updated_at"),
    ("jobs", "created_at"),
    ("jobs", "started_at"),
    ("jobs", "finished_at"),
    ("scheduled_tasks", "last_run_at"),
    ("scheduled_tasks", "created_at"),
    ("scheduled_tasks", "updated_at"),
    ("business_domains", "created_at"),
    ("business_domains", "updated_at"),
    ("sources", "access_updated_at"),
    ("sources", "created_at"),
    ("sources", "updated_at"),
    ("catalog_objects", "semantics_updated_at"),
    ("catalog_objects", "collected_at"),
    ("catalog_objects", "created_at"),
    ("catalog_objects", "updated_at"),
    ("catalog_columns", "created_at"),
    ("catalog_columns", "updated_at"),
    ("catalog_foreign_keys", "created_at"),
    ("catalog_foreign_keys", "updated_at"),
    ("catalog_indexes", "created_at"),
    ("catalog_indexes", "updated_at"),
    ("catalog_joins", "created_at"),
)


def upgrade() -> None:
    for table, column in _INSTANT_COLUMNS:
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE timestamptz
            USING {column} AT TIME ZONE 'UTC'
            """
        )


def downgrade() -> None:
    for table, column in reversed(_INSTANT_COLUMNS):
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE timestamp without time zone
            USING {column} AT TIME ZONE 'UTC'
            """
        )
