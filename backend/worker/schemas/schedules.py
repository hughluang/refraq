"""Mechanism Scheduled Task API schemas."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from pydantic import BaseModel, ConfigDict


class ScheduleTargetOut(BaseModel):
    source_id: str | None = None
    source_key: str | None = None


class ScheduleRecentJobOut(BaseModel):
    id: str
    status: str
    created_at: Instant | None = None
    started_at: Instant | None = None
    finished_at: Instant | None = None
    error_code: str | None = None


class ScheduleOut(BaseModel):
    id: str
    key: str
    name: str
    enabled: bool
    work_kind: str | None
    target: ScheduleTargetOut | None
    interval_seconds: int | None
    cron: str | None
    running_timeout_sec: int | None = None
    start_at: Instant | None = None
    deletable: bool = True
    last_run_at: Instant | None
    next_run_at: Instant | None = None
    recent_jobs: list[ScheduleRecentJobOut] = []
    created_at: Instant
    updated_at: Instant


class ScheduleListResponse(OffsetPage[ScheduleOut]):
    cron_timezone: str


class ScheduleResponse(BaseModel):
    schedule: ScheduleOut


class SchedulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    running_timeout_sec: int | None = None
    start_at: Instant | None = None


class CronPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str
    start_at: Instant | None = None


class CronPreviewResponse(BaseModel):
    cron_timezone: str
    next_run_ats: list[Instant]
