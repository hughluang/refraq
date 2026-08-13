"""Mechanism Job API schemas."""

from __future__ import annotations

from backend.core.time import Instant
from typing import Any

from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    summary: str
    trigger_kind: str | None
    trigger_ref: str | None
    trigger_actor_name: str | None = None
    created_by_user_id: str | None
    created_at: Instant
    started_at: Instant | None
    finished_at: Instant | None
    error_code: str | None
    error_message: str | None
    log_updated_at: Instant | None = None


class JobListResponse(BaseModel):
    items: list[JobOut]


class JobResponse(BaseModel):
    job: JobOut


class JobLogsResponse(BaseModel):
    job_id: str
    body: str
    updated_at: Instant | None
