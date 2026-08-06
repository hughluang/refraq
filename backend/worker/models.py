"""ORM for platform Scheduled Task rows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base

REAPER_SCHEDULE_KEY = "ingestion_reap_stuck_running"
REAPER_TASK_NAME = "backend.worker.tasks.reap_stuck_ingestion_jobs"


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_name: Mapped[str] = mapped_column(String(256), nullable=False)
    args_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    kwargs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
