"""Mechanism Scheduled Task API schemas."""

from __future__ import annotations

from backend.core.time import Instant
from pydantic import BaseModel


class ScheduleTargetOut(BaseModel):
    source_id: str | None = None
    source_key: str | None = None


class ScheduleOut(BaseModel):
    id: str
    key: str
    name: str
    enabled: bool
    work_kind: str | None
    target: ScheduleTargetOut | None
    interval_seconds: int | None
    cron: str | None
    schedule_timezone: str
    last_run_at: Instant | None
    created_at: Instant
    updated_at: Instant


class ScheduleListResponse(BaseModel):
    items: list[ScheduleOut]


class ScheduleResponse(BaseModel):
    schedule: ScheduleOut


class SchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    schedule_timezone: str | None = None
