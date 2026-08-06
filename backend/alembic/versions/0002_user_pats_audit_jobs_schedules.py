"""User PATs, audit events, ingestion jobs, scheduled tasks.

Revision ID: 0002_companion_base
Revises: 0001_initial
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_companion_base"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_pats",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_pats_user_id", "user_pats", ["user_id"])
    op.create_index("ix_user_pats_prefix", "user_pats", ["prefix"])
    op.create_index("ix_user_pats_token_hash", "user_pats", ["token_hash"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=64), nullable=True),
        sa.Column("actor_token_id", sa.String(length=64), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_resource_type", "audit_events", ["resource_type"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_system_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_connection_id", "ingestion_jobs", ["connection_id"])

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron", sa.String(length=128), nullable=True),
        sa.Column("task_name", sa.String(length=256), nullable=False),
        sa.Column("args_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("kwargs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scheduled_tasks_key", "scheduled_tasks", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_key", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
    op.drop_index("ix_ingestion_jobs_connection_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_type", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_user_pats_token_hash", table_name="user_pats")
    op.drop_index("ix_user_pats_prefix", table_name="user_pats")
    op.drop_index("ix_user_pats_user_id", table_name="user_pats")
    op.drop_table("user_pats")
